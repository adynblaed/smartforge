import {
  ContactShadows,
  Edges,
  Environment,
  Float,
  GizmoHelper,
  GizmoViewport,
  Grid,
  Html,
  Instance,
  Instances,
  Lightformer,
  Line,
  MeshReflectorMaterial,
  OrbitControls,
  PerformanceMonitor,
  RoundedBox,
  useFBX,
} from "@react-three/drei"
import { Canvas, useFrame, useLoader, useThree } from "@react-three/fiber"
import {
  Bloom,
  EffectComposer,
  SMAA,
  Vignette,
} from "@react-three/postprocessing"
import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  Activity,
  Boxes,
  Cpu,
  Grid3x3,
  Maximize2,
  Minimize2,
  Minus,
  RotateCcw,
  Server,
  Sparkles,
  X,
} from "lucide-react"
import type { ReactNode } from "react"
import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"
import { ErrorBoundary } from "react-error-boundary"
import type { Group, Mesh, MeshStandardMaterial } from "three"
import { Color, QuadraticBezierCurve3, Vector3 } from "three"
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js"
import { useTheme } from "@/components/theme-provider"
import { Button } from "@/components/ui/button"
import { sf } from "@/smartforge/api"
import { HEX, healthHex, PageHeader } from "@/smartforge/components"
import { POLL } from "@/smartforge/constants"
import { type ForgeFocus, useForgeAgent } from "@/smartforge/ForgeAgent"
import { ProceduralModel, StationCore } from "@/smartforge/machineModels"
import type {
  InventoryItem,
  Machine,
  Page,
  PurchaseOrder,
  TelemetryEvent,
} from "@/smartforge/types"
import { useTelemetryStream } from "@/smartforge/useRealtime"
import { Gauge, Heartbeat } from "@/smartforge/widgets"

export const Route = createFileRoute("/_layout/factory-map")({
  validateSearch: (search: Record<string, unknown>): { machine?: string } => ({
    machine: typeof search.machine === "string" ? search.machine : undefined,
  }),
  component: FactorySimulationPage,
  head: () => ({ meta: [{ title: "Factory Simulation - SmartForge" }] }),
})

interface LiveMachine extends Machine {
  liveHealth: number
  liveStatus: string
  liveTemp?: number
  liveVibration?: number
}

// A shipment manifest carried on a pallet — built from real inventory + PO data.
interface Manifest {
  id: string
  sku: string
  name: string
  quantity: number
  belowThreshold: boolean
  poId?: string
  poNumber?: string
  amount?: number
  poStatus?: string
}

const STEEL = "#2b2f38"
const CHROME = "#aeb6c4"
const WHITE = "#f1f4f8"
const ACCENT = "#38bdf8"

// Scene palette per resolved theme. The 3D scene can't read CSS variables, so
// this is the single source of truth for scene colors — extend the map to add a
// new theme (e.g. a high-contrast or seasonal theme) and everything downstream
// (background, fog, floor, grid, lighting) picks it up automatically.
type SceneKey = "light" | "dark" | "future"
interface ScenePalette {
  bg: string
  floor: string
  cell: string
  section: string
  dark: boolean
}
const SCENE_THEME: Record<SceneKey, ScenePalette> = {
  light: {
    bg: "#e8edf3",
    floor: "#dfe5ec",
    cell: "#c2cad6",
    section: "#7c93b8",
    dark: false,
  },
  dark: {
    bg: "#070a0f",
    floor: "#090c11",
    cell: "#1b2230",
    section: "#2563eb",
    dark: true,
  },
  // "Future" — a true-black stage with on-brand indigo grid accents.
  future: {
    bg: "#04050a",
    floor: "#06070e",
    cell: "#1c1c33",
    section: "#6366f1",
    dark: true,
  },
}

/**
 * Optional external model registry — drop `.fbx` or `.stl` files into
 * `frontend/public/models/` and map a machine_type to one here to replace the
 * procedural model. Empty by default (procedural is used); the loader paths
 * below give the simulation first-class .fbx/.stl import support.
 */
const MODEL_REGISTRY: Record<string, string> = {
  // cnc_mill: "/models/cnc.fbx",
  // hydraulic_press: "/models/press.stl",
}

/* --------------------------------------------------------- model importers */

function FbxModel({ url }: { url: string }) {
  const fbx = useFBX(url)
  // Clone + shadow flags together, once per source model — mutating the
  // clone in the render body would re-traverse the whole hierarchy on
  // every render. Geometries/materials are SHARED with drei's cached FBX
  // (never disposed here — the cache owns them).
  const clone = useMemo(() => {
    const instance = fbx.clone()
    instance.traverse((o) => {
      o.castShadow = true
      o.receiveShadow = true
    })
    return instance
  }, [fbx])
  return <primitive object={clone} />
}

function StlModel({ url, color }: { url: string; color: string }) {
  const geom = useLoader(STLLoader, url)
  return (
    <mesh geometry={geom} castShadow receiveShadow scale={0.02}>
      <meshStandardMaterial color={color} metalness={0.8} roughness={0.3} />
    </mesh>
  )
}

function ImportedModel({ url, color }: { url: string; color: string }) {
  return url.toLowerCase().endsWith(".stl") ? (
    <StlModel url={url} color={color} />
  ) : (
    <FbxModel url={url} />
  )
}

/* ------------------------------------------------------ live entity stats */

type PanelKind = "machine" | "plc" | "server"

interface PanelStats {
  status: string
  bpm: number
  power: number
  throughput: number
  throughputMax: number
  defects: number
  defectsMax: number
  energy: number
  energyMax: number
  rows: { label: string; value: string }[]
}

// Stable 0..1 value derived from an id (no Math.random in render paths).
function hashUnit(id: string): number {
  let h = 0
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) % 997
  return h / 997
}

function machineStats(m: LiveMachine): PanelStats {
  const running = m.liveStatus === "running"
  const base =
    m.machine_type === "hydraulic_press"
      ? 11
      : m.machine_type === "cnc_mill"
        ? 7.5
        : 4.2
  const power = running ? base * (0.78 + (m.liveTemp ?? 55) / 220) : base * 0.18
  const tputMax =
    m.machine_type === "robotic_arm"
      ? 720
      : m.machine_type === "cnc_mill"
        ? 520
        : 380
  const throughput = Math.round(tputMax * (running ? m.liveHealth / 100 : 0.04))
  const defects = Math.round(
    ((100 - m.liveHealth) / 100) * 24 + hashUnit(m.id) * 5,
  )
  const energy = Math.round(power * 17)
  const bpm = running ? Math.round(58 + (100 - m.liveHealth) * 0.7) : 42
  return {
    status: m.liveStatus,
    bpm,
    power,
    throughput,
    throughputMax: tputMax,
    defects,
    defectsMax: 40,
    energy,
    energyMax: Math.round(base * 17 * 1.35),
    rows: [
      { label: "Health", value: `${Math.round(m.liveHealth)}` },
      {
        label: "Temp",
        value: m.liveTemp != null ? `${m.liveTemp.toFixed(0)}°C` : "—",
      },
      {
        label: "Vib",
        value: m.liveVibration != null ? m.liveVibration.toFixed(2) : "—",
      },
    ],
  }
}

function lineAggregate(machines: LiveMachine[]) {
  const stats = machines.map(machineStats)
  return {
    throughput: stats.reduce((a, s) => a + s.throughput, 0),
    defects: stats.reduce((a, s) => a + s.defects, 0),
    energy: stats.reduce((a, s) => a + s.energy, 0),
    running: machines.filter((m) => m.liveStatus === "running").length,
    faults: machines.filter((m) => m.last_fault_code).length,
  }
}

function serverStats(machines: LiveMachine[]): PanelStats {
  const a = lineAggregate(machines)
  return {
    status: "running",
    bpm: 70,
    power: 5.4,
    throughput: a.throughput,
    throughputMax: Math.max(2000, Math.round(a.throughput * 1.3)),
    defects: a.defects,
    defectsMax: 60,
    energy: 92,
    energyMax: 140,
    rows: [
      { label: "CPU", value: `${30 + a.running * 6}%` },
      { label: "Uptime", value: "99.98%" },
      { label: "Ingest", value: `${Math.round(a.throughput / 24)}/h` },
    ],
  }
}

function plcStats(machines: LiveMachine[]): PanelStats {
  const a = lineAggregate(machines)
  return {
    status: a.running > 0 ? "running" : "idle",
    bpm: 66,
    power: 2.3,
    throughput: a.throughput,
    throughputMax: Math.max(2000, Math.round(a.throughput * 1.3)),
    defects: a.defects,
    defectsMax: 60,
    energy: Math.round(a.energy),
    energyMax: Math.max(220, Math.round(a.energy * 1.3)),
    rows: [
      { label: "Scan", value: "8 ms" },
      { label: "I/O pts", value: `${a.running * 64}` },
      { label: "Faults", value: `${a.faults}` },
    ],
  }
}

/* ----------------------------------------------------- live panel widgets */

function PowerSpark({ value, color }: { value: number; color: string }) {
  const [series, setSeries] = useState<number[]>(() =>
    Array.from(
      { length: 26 },
      (_, i) => value * (0.85 + 0.25 * Math.sin(i / 2.2)),
    ),
  )
  useEffect(() => {
    const t = setInterval(
      () =>
        setSeries((s) => [
          ...s.slice(1),
          Math.max(0.1, value * (0.88 + Math.random() * 0.22)),
        ]),
      1600,
    )
    return () => clearInterval(t)
  }, [value])
  const max = Math.max(...series, 0.1)
  const min = Math.min(...series)
  const span = Math.max(0.1, max - min)
  const pts = series
    .map(
      (v, i) =>
        `${(i / (series.length - 1)) * 100},${28 - ((v - min) / span) * 22 - 3}`,
    )
    .join(" ")
  return (
    // decorative — the panel stats beside it carry the live values
    <svg
      viewBox="0 0 100 28"
      preserveAspectRatio="none"
      aria-hidden="true"
      className="mt-1 h-8 w-full"
    >
      <polygon points={`0,28 ${pts} 100,28`} fill={color} opacity={0.15} />
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth={1.4}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}

const KIND_ICON: Record<PanelKind, ReactNode> = {
  machine: <Activity size={13} />,
  plc: <Cpu size={13} />,
  server: <Server size={13} />,
}

function EntityPanel({
  kind,
  code,
  name,
  stats,
  fault,
  onClose,
}: {
  kind: PanelKind
  code: string
  name: string
  stats: PanelStats
  fault?: string | null
  onClose: () => void
}) {
  const color =
    stats.status === "running"
      ? HEX.success
      : stats.status === "idle"
        ? HEX.warning
        : HEX.danger
  return (
    <div className="w-64 -translate-x-1/2 rounded-2xl border border-border bg-background/95 p-3 shadow-2xl backdrop-blur-md">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <span className="flex size-6 items-center justify-center rounded-md bg-muted text-foreground">
            {KIND_ICON[kind]}
          </span>
          <div>
            <h2 className="text-sm font-semibold leading-tight">{code}</h2>
            <p className="text-[10px] text-muted-foreground">{name}</p>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Minimize panel"
          className="rounded-md p-1 text-muted-foreground hover:bg-accent"
        >
          <Minus size={14} />
        </button>
      </div>

      <div className="mt-2">
        <Heartbeat color={color} bpm={stats.bpm} />
      </div>

      <div className="mt-2 rounded-md border bg-muted/30 p-2">
        <div className="flex items-center justify-between text-[10px] text-muted-foreground">
          <span>Active power draw</span>
          <span className="font-semibold text-foreground tabular-nums">
            {stats.power.toFixed(1)} kW
          </span>
        </div>
        <PowerSpark value={stats.power} color={color} />
      </div>

      <div className="mt-2 grid grid-cols-3 gap-1.5">
        <Gauge
          value={stats.throughput}
          max={stats.throughputMax}
          label="Units/day"
          color={HEX.info}
        />
        <Gauge
          value={stats.defects}
          max={stats.defectsMax}
          label="Defects/day"
          color={HEX.danger}
        />
        <Gauge
          value={stats.energy}
          max={stats.energyMax}
          label="kWh/day"
          color={HEX.warning}
        />
      </div>

      <div className="mt-2 grid grid-cols-3 gap-1 text-center text-[10px]">
        {stats.rows.map((r) => (
          <div key={r.label} className="rounded-md border bg-muted/40 p-1">
            <div className="text-muted-foreground">{r.label}</div>
            <div className="font-semibold tabular-nums">{r.value}</div>
          </div>
        ))}
      </div>

      {fault && (
        <p className="mt-2 rounded-md bg-danger/10 px-2 py-1 text-[11px] text-danger">
          Fault: {fault}
        </p>
      )}

      {kind === "machine" && (
        // Plain <a> (not router <Link>): this panel renders inside the R3F
        // <Canvas> via drei <Html>, which is outside the Router context — a
        // <Link> here throws and silently drops the whole panel.
        <div className="mt-2 flex gap-2">
          <Button asChild size="sm" className="h-7 flex-1 text-[11px]">
            <a href="/machines">Console</a>
          </Button>
          <Button
            asChild
            size="sm"
            variant="outline"
            className="h-7 flex-1 text-[11px]"
          >
            <a href="/ask-ai">Ask AI</a>
          </Button>
        </div>
      )}
    </div>
  )
}

/* ----------------------------------------------------------- machine node */

function MachineStation({
  machine,
  open,
  highlighted,
  onToggle,
  onClose,
}: {
  machine: LiveMachine
  open: boolean
  highlighted: boolean
  onToggle: () => void
  onClose: () => void
}) {
  const [hovered, setHovered] = useState(false)
  const color = healthHex(machine.liveHealth)
  const running = machine.liveStatus === "running"
  const active = hovered || open || highlighted
  const modelUrl = MODEL_REGISTRY[machine.machine_type]

  // Never leave the document cursor stuck as a pointer if this unmounts.
  useEffect(
    () => () => {
      document.body.style.cursor = "auto"
    },
    [],
  )

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: react-three-fiber scene node, not a DOM element
    <group
      position={[machine.pos_x, 0, 0]}
      onPointerOver={(e) => {
        e.stopPropagation()
        setHovered(true)
        document.body.style.cursor = "pointer"
      }}
      onPointerOut={() => {
        setHovered(false)
        document.body.style.cursor = "auto"
      }}
      onClick={(e) => {
        e.stopPropagation()
        onToggle()
      }}
    >
      <StationCore
        type={machine.machine_type}
        running={running}
        color={color}
        active={active}
      >
        {modelUrl ? (
          <ErrorBoundary
            fallback={
              <ProceduralModel type={machine.machine_type} running={running} />
            }
          >
            <Suspense
              fallback={
                <ProceduralModel
                  type={machine.machine_type}
                  running={running}
                />
              }
            >
              <ImportedModel url={modelUrl} color={CHROME} />
            </Suspense>
          </ErrorBoundary>
        ) : undefined}
      </StationCore>

      {/* pulsing ground ring when ForgeAI has located this machine */}
      {highlighted && !open && (
        <mesh position={[0, 0.16, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[1.7, 1.95, 56]} />
          <meshBasicMaterial
            color={ACCENT}
            transparent
            opacity={0.9}
            toneMapped={false}
          />
        </mesh>
      )}

      {/* hover / highlight label */}
      {(hovered || highlighted) && !open && (
        <Html
          position={[0, 3, 0]}
          center
          distanceFactor={16}
          zIndexRange={[10, 0]}
        >
          <div className="pointer-events-none whitespace-nowrap rounded-md border border-border bg-black/80 px-2 py-1 text-[11px] text-white shadow-xl backdrop-blur">
            <span className="font-semibold">{machine.code}</span> ·{" "}
            <span style={{ color }}>{Math.round(machine.liveHealth)}</span>
          </div>
        </Html>
      )}

      {/* pinnable live panel floats above the machine in 3D space */}
      {open && (
        <Html
          position={[0, 3.6, 0]}
          center
          distanceFactor={10}
          zIndexRange={[30, 0]}
          occlude={false}
        >
          <EntityPanel
            kind="machine"
            code={machine.code}
            name={machine.name}
            stats={machineStats(machine)}
            fault={machine.last_fault_code}
            onClose={onClose}
          />
        </Html>
      )}
    </group>
  )
}

/* ------------------------------------------------ PLC / server line fixtures */

function LineFixture({
  code,
  name,
  kind,
  position,
  color,
  open,
  stats,
  onToggle,
  onClose,
  children,
}: {
  code: string
  name: string
  kind: PanelKind
  position: [number, number, number]
  color: string
  open: boolean
  stats: PanelStats
  onToggle: () => void
  onClose: () => void
  children: ReactNode
}) {
  const [hovered, setHovered] = useState(false)
  const active = hovered || open

  useEffect(
    () => () => {
      document.body.style.cursor = "auto"
    },
    [],
  )

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: react-three-fiber scene node, not a DOM element
    <group
      position={position}
      onPointerOver={(e) => {
        e.stopPropagation()
        setHovered(true)
        document.body.style.cursor = "pointer"
      }}
      onPointerOut={() => {
        setHovered(false)
        document.body.style.cursor = "auto"
      }}
      onClick={(e) => {
        e.stopPropagation()
        onToggle()
      }}
    >
      <StationCore type="" running={false} color={color} active={active}>
        {children}
      </StationCore>

      {hovered && !open && (
        <Html
          position={[0, 3, 0]}
          center
          distanceFactor={16}
          zIndexRange={[10, 0]}
        >
          <div className="pointer-events-none whitespace-nowrap rounded-md border border-border bg-black/80 px-2 py-1 text-[11px] text-white shadow-xl backdrop-blur">
            <span className="font-semibold">{code}</span>
          </div>
        </Html>
      )}

      {open && (
        <Html
          position={[0, 3.6, 0]}
          center
          distanceFactor={10}
          zIndexRange={[30, 0]}
          occlude={false}
        >
          <EntityPanel
            kind={kind}
            code={code}
            name={name}
            stats={stats}
            onClose={onClose}
          />
        </Html>
      )}
    </group>
  )
}

function ServerRackModel() {
  return (
    <group>
      <RoundedBox
        args={[1.4, 2.2, 1.1]}
        radius={0.05}
        smoothness={3}
        position={[0, 1.1, 0]}
        castShadow
        receiveShadow
      >
        <meshStandardMaterial color="#14171f" metalness={0.7} roughness={0.4} />
        <Edges threshold={15} color="#2a2f3a" />
      </RoundedBox>
      {Array.from({ length: 7 }, (_, i) => (
        <group key={i} position={[0, 0.45 + i * 0.25, 0.57]}>
          <mesh>
            <boxGeometry args={[1.2, 0.18, 0.04]} />
            <meshStandardMaterial
              color="#0d0f13"
              metalness={0.4}
              roughness={0.6}
            />
          </mesh>
          {[-0.45, -0.3].map((x) => (
            <mesh key={x} position={[x, 0, 0.03]}>
              <boxGeometry args={[0.05, 0.05, 0.02]} />
              <meshStandardMaterial
                color={i % 2 ? "#22c55e" : ACCENT}
                emissive={i % 2 ? "#22c55e" : ACCENT}
                emissiveIntensity={2.5}
                toneMapped={false}
              />
            </mesh>
          ))}
        </group>
      ))}
    </group>
  )
}

function PlcCabinetModel() {
  return (
    <group>
      <RoundedBox
        args={[1.5, 2, 1]}
        radius={0.06}
        smoothness={3}
        position={[0, 1, 0]}
        castShadow
        receiveShadow
      >
        <meshStandardMaterial
          color="#1f2733"
          metalness={0.6}
          roughness={0.45}
        />
        <Edges threshold={15} color="#2a3340" />
      </RoundedBox>
      {/* HMI touch screen */}
      <mesh position={[0, 1.35, 0.51]}>
        <boxGeometry args={[0.8, 0.55, 0.02]} />
        <meshStandardMaterial
          color="#0a1622"
          emissive={ACCENT}
          emissiveIntensity={1.5}
          toneMapped={false}
        />
      </mesh>
      {/* stacked indicator lights */}
      {(["#22c55e", "#f59e0b", "#ef4444"] as const).map((c, i) => (
        <mesh key={c} position={[0.55, 0.55 + i * 0.18, 0.51]}>
          <sphereGeometry args={[0.05, 12, 12]} />
          <meshStandardMaterial
            color={c}
            emissive={c}
            emissiveIntensity={2.5}
            toneMapped={false}
          />
        </mesh>
      ))}
      {/* recessed vent panel with a few chunky louvers (avoids fine-grate moiré) */}
      <mesh position={[-0.45, 0.6, 0.5]}>
        <boxGeometry args={[0.62, 0.52, 0.04]} />
        <meshStandardMaterial
          color="#0b0d11"
          metalness={0.3}
          roughness={0.75}
        />
      </mesh>
      {[0.74, 0.6, 0.46].map((y) => (
        <mesh key={y} position={[-0.45, y, 0.54]}>
          <boxGeometry args={[0.56, 0.07, 0.03]} />
          <meshStandardMaterial
            color="#3a4150"
            metalness={0.6}
            roughness={0.4}
          />
        </mesh>
      ))}
    </group>
  )
}

/* ------------------------------------------------------------- structures */

function Conveyor() {
  return (
    <group>
      <RoundedBox
        args={[26, 0.36, 1.15]}
        radius={0.05}
        smoothness={3}
        position={[0, 0.2, 0]}
        castShadow
        receiveShadow
      >
        <meshStandardMaterial
          color="#21252d"
          metalness={0.7}
          roughness={0.45}
        />
      </RoundedBox>
      <mesh position={[0, 0.4, 0]}>
        <boxGeometry args={[26, 0.02, 0.92]} />
        <meshStandardMaterial
          color="#0d0f13"
          metalness={0.2}
          roughness={0.85}
        />
      </mesh>
      <mesh position={[0, 0.42, 0]}>
        <boxGeometry args={[26, 0.012, 0.07]} />
        <meshStandardMaterial
          color={ACCENT}
          emissive={ACCENT}
          emissiveIntensity={2.6}
          toneMapped={false}
        />
      </mesh>
    </group>
  )
}

// Expanded warehouse shell: 46 wide × 38 deep, ~11 tall.
const BLD = { w: 46, d: 38, h: 11, frontZ: -12, backZ: 26, side: 23, cz: 7 }

function Building() {
  return (
    <group>
      {/* reflective interior floor (premium) */}
      <mesh
        position={[0, 0.02, BLD.cz]}
        rotation={[-Math.PI / 2, 0, 0]}
        receiveShadow
      >
        <planeGeometry args={[BLD.w - 0.6, BLD.d - 0.6]} />
        <MeshReflectorMaterial
          resolution={256}
          mixBlur={1}
          mixStrength={6}
          blur={[300, 80]}
          roughness={0.85}
          depthScale={1}
          minDepthThreshold={0.4}
          maxDepthThreshold={1.2}
          color="#0c0f14"
          metalness={0.6}
        />
      </mesh>

      {/* back wall */}
      <RoundedBox
        args={[BLD.w, BLD.h, 0.3]}
        radius={0.05}
        smoothness={2}
        position={[0, BLD.h / 2, BLD.backZ]}
        castShadow
        receiveShadow
      >
        <meshStandardMaterial color="#1a1e26" metalness={0.4} roughness={0.6} />
      </RoundedBox>
      {/* side walls */}
      {[-BLD.side, BLD.side].map((x) => (
        <RoundedBox
          key={x}
          args={[0.3, BLD.h, BLD.d]}
          radius={0.05}
          smoothness={2}
          position={[x, BLD.h / 2, BLD.cz]}
          castShadow
          receiveShadow
        >
          <meshStandardMaterial
            color="#1a1e26"
            metalness={0.4}
            roughness={0.6}
          />
        </RoundedBox>
      ))}

      {/* roof beams (trusses across the span) */}
      {Array.from({ length: 15 }, (_, i) => -21 + i * 3).map((x) => (
        <mesh key={x} position={[x, BLD.h, BLD.cz]} castShadow>
          <boxGeometry args={[0.24, 0.24, BLD.d]} />
          <meshStandardMaterial
            color={STEEL}
            metalness={0.8}
            roughness={0.35}
          />
        </mesh>
      ))}

      {/* glass front */}
      <mesh position={[0, BLD.h / 2, BLD.frontZ]}>
        <boxGeometry args={[BLD.w, BLD.h, 0.06]} />
        <meshStandardMaterial
          color={ACCENT}
          transparent
          opacity={0.05}
          metalness={0.1}
          roughness={0.05}
        />
        <Edges threshold={15} color="#2b3340" />
      </mesh>

      {/* sign */}
      <mesh position={[0, BLD.h - 0.7, BLD.frontZ]}>
        <boxGeometry args={[14, 0.18, 0.05]} />
        <meshStandardMaterial
          color={ACCENT}
          emissive={ACCENT}
          emissiveIntensity={2.6}
          toneMapped={false}
        />
      </mesh>
      <Html
        position={[0, BLD.h - 0.7, BLD.frontZ + 0.1]}
        center
        distanceFactor={34}
      >
        <div className="pointer-events-none select-none whitespace-nowrap text-sm font-semibold tracking-[0.35em] text-sky-300">
          SMARTFORGE
        </div>
      </Html>
    </group>
  )
}

/* ------------------------------------------------------- warehouse racking */

const PALLET_COLORS = ["#b08968", "#cbd5e1", "#3b82f6", "#e2e8f0", "#94a3b8"]

function RackUnit({
  width = 7,
  levels = 3,
}: {
  width?: number
  levels?: number
}) {
  const H = 5.4
  const D = 1.4
  const Upright = ({ x, z }: { x: number; z: number }) => (
    <mesh position={[x, H / 2, z]} castShadow>
      <boxGeometry args={[0.16, H, 0.16]} />
      <meshStandardMaterial color="#1d4ed8" metalness={0.5} roughness={0.5} />
    </mesh>
  )
  const palletsPerLevel = Math.max(1, Math.floor(width / 2.3))
  return (
    <group>
      <Upright x={-width / 2} z={-D / 2} />
      <Upright x={width / 2} z={-D / 2} />
      <Upright x={-width / 2} z={D / 2} />
      <Upright x={width / 2} z={D / 2} />
      {Array.from({ length: levels }, (_, l) => {
        const y = 0.1 + (l * (H - 0.3)) / levels
        return (
          <group key={l} position={[0, y, 0]}>
            {[-D / 2, D / 2].map((z) => (
              <mesh key={z} position={[0, 0, z]} castShadow>
                <boxGeometry args={[width, 0.12, 0.12]} />
                <meshStandardMaterial
                  color="#ea7a09"
                  metalness={0.5}
                  roughness={0.5}
                />
              </mesh>
            ))}
            <mesh position={[0, -0.04, 0]} receiveShadow>
              <boxGeometry args={[width, 0.05, D]} />
              <meshStandardMaterial
                color="#2b303a"
                metalness={0.3}
                roughness={0.7}
              />
            </mesh>
            {Array.from({ length: palletsPerLevel }, (_, p) => {
              const px = -width / 2 + 1.2 + p * 2.3
              return (
                <RoundedBox
                  key={p}
                  args={[1.6, 0.95, 1.05]}
                  radius={0.04}
                  smoothness={2}
                  position={[px, 0.55, 0]}
                >
                  <meshStandardMaterial
                    color={PALLET_COLORS[(l + p) % PALLET_COLORS.length]}
                    metalness={0.05}
                    roughness={0.75}
                  />
                  <Edges threshold={15} color="#1f2937" />
                </RoundedBox>
              )
            })}
          </group>
        )
      })}
    </group>
  )
}

function PalletStack({ x, z }: { x: number; z: number }) {
  return (
    <group position={[x, 0, z]}>
      <RoundedBox
        args={[1.5, 0.95, 1.1]}
        radius={0.04}
        smoothness={2}
        position={[0, 0.48, 0]}
        castShadow
      >
        <meshStandardMaterial color="#b08968" roughness={0.8} />
      </RoundedBox>
      <RoundedBox
        args={[1.35, 0.85, 1]}
        radius={0.04}
        smoothness={2}
        position={[0, 1.35, 0]}
        castShadow
      >
        <meshStandardMaterial color="#cbd5e1" roughness={0.7} />
        <Edges threshold={15} color="#94a3b8" />
      </RoundedBox>
    </group>
  )
}

// Forklift body, modeled facing +Z (its travel/forward direction).
function ForkliftModel({ color = "#eab308" }: { color?: string }) {
  return (
    <group>
      <RoundedBox
        args={[1.5, 1, 2.1]}
        radius={0.12}
        smoothness={3}
        position={[0, 0.75, 0]}
        castShadow
      >
        <meshStandardMaterial color={color} metalness={0.5} roughness={0.4} />
      </RoundedBox>
      {/* operator cage roof + posts */}
      <mesh position={[0, 1.7, -0.4]} castShadow>
        <boxGeometry args={[1.3, 0.08, 1.3]} />
        <meshStandardMaterial color="#0e1116" />
      </mesh>
      {[
        [-0.6, -1],
        [0.6, -1],
        [-0.6, 0.2],
        [0.6, 0.2],
      ].map(([x, z], i) => (
        <mesh key={i} position={[x, 1.35, z]} castShadow>
          <boxGeometry args={[0.06, 0.7, 0.06]} />
          <meshStandardMaterial color="#0e1116" />
        </mesh>
      ))}
      {/* mast + forks at the front (+Z) */}
      <mesh position={[0, 1.3, 1.05]} castShadow>
        <boxGeometry args={[1.3, 2.6, 0.12]} />
        <meshStandardMaterial color={STEEL} metalness={0.7} roughness={0.4} />
      </mesh>
      {[-0.35, 0.35].map((x) => (
        <mesh key={x} position={[x, 0.2, 1.7]} castShadow>
          <boxGeometry args={[0.16, 0.1, 1.1]} />
          <meshStandardMaterial
            color={CHROME}
            metalness={0.9}
            roughness={0.3}
          />
        </mesh>
      ))}
      {/* amber warning beacon */}
      <mesh position={[0, 1.85, -0.4]}>
        <sphereGeometry args={[0.08, 12, 12]} />
        <meshStandardMaterial
          color="#f59e0b"
          emissive="#f59e0b"
          emissiveIntensity={2.5}
          toneMapped={false}
        />
      </mesh>
    </group>
  )
}

// Flat outlined floor marker for a grid pick-up / drop-off point.
function GridPad({ x, z, label }: { x: number; z: number; label: string }) {
  return (
    <group position={[x, 0, z]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.05, 0]}>
        <planeGeometry args={[2.4, 2.4]} />
        <meshBasicMaterial
          color={ACCENT}
          transparent
          opacity={0.12}
          toneMapped={false}
        />
        <Edges threshold={15} color={ACCENT} />
      </mesh>
      <Html
        position={[0, 0.5, 0]}
        center
        distanceFactor={26}
        zIndexRange={[8, 0]}
      >
        <div className="pointer-events-none select-none whitespace-nowrap rounded bg-black/55 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-sky-200 backdrop-blur">
          {label}
        </div>
      </Html>
    </group>
  )
}

// A clickable pallet/box carrying a real shipment manifest.
function ManifestPallet({
  manifest,
  onSelect,
  scale = 1,
}: {
  manifest: Manifest
  onSelect?: (m: Manifest) => void
  scale?: number
}) {
  const [hovered, setHovered] = useState(false)
  useEffect(
    () => () => {
      document.body.style.cursor = "auto"
    },
    [],
  )
  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: react-three-fiber scene node, not a DOM element
    <group
      scale={scale}
      onClick={(e) => {
        e.stopPropagation()
        onSelect?.(manifest)
      }}
      onPointerOver={(e) => {
        e.stopPropagation()
        setHovered(true)
        document.body.style.cursor = "pointer"
      }}
      onPointerOut={() => {
        setHovered(false)
        document.body.style.cursor = "auto"
      }}
    >
      <RoundedBox
        args={[1.1, 0.18, 1.0]}
        radius={0.03}
        smoothness={2}
        position={[0, 0.09, 0]}
        castShadow
      >
        <meshStandardMaterial color="#b08968" roughness={0.85} />
      </RoundedBox>
      <RoundedBox
        args={[0.9, 0.62, 0.8]}
        radius={0.04}
        smoothness={2}
        position={[0, 0.5, 0]}
        castShadow
      >
        <meshStandardMaterial
          color={hovered ? ACCENT : "#cbd5e1"}
          emissive={hovered ? ACCENT : "#000000"}
          emissiveIntensity={hovered ? 0.5 : 0}
          roughness={0.7}
        />
        <Edges
          threshold={15}
          color={manifest.belowThreshold ? "#ef4444" : "#94a3b8"}
        />
      </RoundedBox>
      {hovered && (
        <Html
          position={[0, 1.15, 0]}
          center
          distanceFactor={14}
          zIndexRange={[12, 0]}
        >
          <div className="pointer-events-none whitespace-nowrap rounded bg-black/80 px-1.5 py-0.5 text-[9px] font-semibold text-white backdrop-blur">
            {manifest.sku}
          </div>
        </Html>
      )}
    </group>
  )
}

function ManifestRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="truncate font-medium">{value}</span>
    </div>
  )
}

// Screen-space panel showing the clicked pallet's manifest (shipping/receiving).
function ManifestPanel({
  manifest,
  onClose,
}: {
  manifest: Manifest
  onClose: () => void
}) {
  const status =
    manifest.poStatus === "received"
      ? "Received"
      : manifest.poStatus === "open"
        ? "In transit"
        : manifest.poStatus === "draft"
          ? "Staged"
          : "Inbound"
  const color =
    status === "Received"
      ? HEX.success
      : status === "In transit"
        ? HEX.info
        : HEX.warning
  return (
    <div className="absolute bottom-4 left-4 z-20 w-[300px] rounded-xl border border-border bg-background/95 p-4 shadow-2xl backdrop-blur-md">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <span className="flex size-7 items-center justify-center rounded-md bg-muted text-foreground">
            <Boxes size={15} />
          </span>
          <div>
            <h2 className="text-sm font-semibold leading-tight">
              Shipment Manifest
            </h2>
            <p className="text-[11px] text-muted-foreground">{manifest.sku}</p>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close manifest"
          className="rounded-md p-1 text-muted-foreground hover:bg-accent"
        >
          <X size={16} />
        </button>
      </div>
      <div className="mt-3 space-y-1.5 text-[12px]">
        <ManifestRow label="Item" value={manifest.name} />
        <ManifestRow
          label="Quantity"
          value={`${manifest.quantity.toLocaleString()} units`}
        />
        <ManifestRow label="Purchase order" value={manifest.poNumber ?? "—"} />
        {manifest.amount != null && (
          <ManifestRow
            label="Value"
            value={`$${manifest.amount.toLocaleString()}`}
          />
        )}
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">Status</span>
          <span
            className="rounded-full px-2 py-0.5 text-[10px] font-semibold"
            style={{ background: `${color}22`, color }}
          >
            {status}
          </span>
        </div>
        {manifest.belowThreshold && (
          <p className="rounded-md bg-danger/10 px-2 py-1 text-[11px] text-danger">
            Below reorder threshold — replenishment required
          </p>
        )}
      </div>
      {manifest.poId && (
        <Button
          asChild
          size="sm"
          variant="outline"
          className="mt-3 h-8 w-full text-xs"
        >
          <Link to="/order-tracker" search={{ po: manifest.poId }}>
            View in Order Tracker
          </Link>
        </Button>
      )}
    </div>
  )
}

// A forklift that drives a grid-aligned (90°) route, loaded outbound from the
// receiving area and empty on the return, pausing to load/unload at each end.
function MovingForklift({
  points,
  color,
  speed = 2.6,
  phase = 0,
  manifest,
  onManifest,
  index,
  cargoRefs,
  carryingRefs,
  dropRefs,
  followRef,
}: {
  points: [number, number][]
  color: string
  speed?: number
  phase?: number
  manifest?: Manifest
  onManifest?: (m: Manifest) => void
  index?: number
  cargoRefs?: React.MutableRefObject<(Group | null)[]>
  carryingRefs?: React.MutableRefObject<boolean[]>
  dropRefs?: React.MutableRefObject<boolean[]>
  // When set, this forklift publishes its live world group so the ForgeAI
  // camera can follow it for logistics / PO queries.
  followRef?: React.MutableRefObject<Group | null>
}) {
  const ref = useRef<Group>(null)
  const palletRef = useRef<Group>(null)
  const boxMat = useRef<MeshStandardMaterial>(null)

  const segs = useMemo(() => {
    const out: {
      ax: number
      az: number
      ux: number
      uz: number
      len: number
      heading: number
    }[] = []
    for (let i = 0; i < points.length - 1; i++) {
      const [ax, az] = points[i]
      const [bx, bz] = points[i + 1]
      const dx = bx - ax
      const dz = bz - az
      const len = Math.hypot(dx, dz) || 1
      out.push({
        ax,
        az,
        ux: dx / len,
        uz: dz / len,
        len,
        heading: Math.atan2(dx, dz),
      })
    }
    return out
  }, [points])
  const total = useMemo(() => segs.reduce((a, s) => a + s.len, 0), [segs])

  const dist = useRef(phase * total)
  const dir = useRef(1)
  const dwell = useRef(0)

  useFrame((_, dt) => {
    const g = ref.current
    if (!g || total === 0) return
    // Clamp large frame gaps (tab switches / hitches) so motion stays stable.
    const step = Math.min(dt, 0.05)
    if (dwell.current > 0) {
      dwell.current -= step
    } else {
      // Ease in/out near the endpoints for smooth stops and starts.
      const edge = Math.min(dist.current, total - dist.current)
      const ease = Math.max(0.3, Math.min(1, edge / 2))
      dist.current += speed * ease * step * dir.current
      if (dist.current >= total) {
        dist.current = total
        dir.current = -1
        dwell.current = 1.4 // unloading at the rack
      } else if (dist.current <= 0) {
        dist.current = 0
        dir.current = 1
        dwell.current = 1.4 // loading at receiving
      }
    }
    let rem = dist.current
    for (let i = 0; i < segs.length; i++) {
      const s = segs[i]
      if (rem <= s.len || i === segs.length - 1) {
        const d = Math.min(rem, s.len)
        g.position.set(s.ax + s.ux * d, 0, s.az + s.uz * d)
        // Smoothly steer toward the travel heading → rounded corners.
        const target = dir.current === 1 ? s.heading : s.heading + Math.PI
        let diff = target - g.rotation.y
        diff = Math.atan2(Math.sin(diff), Math.cos(diff))
        g.rotation.y += diff * Math.min(1, step * 6)
        break
      }
      rem -= s.len
    }
    // Cargo is shown outbound (loaded) and while unloading at the rack; the
    // box is blue while loading/hauling and green while actively unloading.
    const atEnd = dist.current >= total - 0.001 && dwell.current > 0
    const carrying = dir.current === 1 || atEnd
    const loaded = carrying && !!manifest
    if (palletRef.current) palletRef.current.visible = loaded
    // Publish cargo position + state so ForgeAI can draw a tracking arc to it.
    // `drop` (green) marks a successful drop/transaction at the rack.
    if (cargoRefs && index !== undefined)
      cargoRefs.current[index] = palletRef.current
    if (carryingRefs && index !== undefined)
      carryingRefs.current[index] = loaded
    if (dropRefs && index !== undefined) dropRefs.current[index] = atEnd
    if (followRef) followRef.current = g
    if (boxMat.current) {
      // Smoothly transition blue → green (and back) rather than snapping.
      const target = atEnd ? _BOX_GREEN : _BOX_BLUE
      const k = Math.min(1, step * 4)
      boxMat.current.color.lerp(target, k)
      boxMat.current.emissive.lerp(target, k)
      boxMat.current.emissiveIntensity = 0.3
    }
  })

  return (
    <group ref={ref}>
      <ForkliftModel color={color} />
      <group ref={palletRef} position={[0, 0.3, 1.55]}>
        {manifest && (
          // biome-ignore lint/a11y/noStaticElementInteractions: react-three-fiber scene node, not a DOM element
          <group
            scale={0.85}
            onClick={(e) => {
              e.stopPropagation()
              onManifest?.(manifest)
            }}
            onPointerOver={(e) => {
              e.stopPropagation()
              document.body.style.cursor = "pointer"
            }}
            onPointerOut={() => {
              document.body.style.cursor = "auto"
            }}
          >
            <RoundedBox
              args={[1.1, 0.18, 1.0]}
              radius={0.03}
              smoothness={2}
              position={[0, 0.09, 0]}
              castShadow
            >
              <meshStandardMaterial color="#b08968" roughness={0.85} />
            </RoundedBox>
            <RoundedBox
              args={[0.9, 0.62, 0.8]}
              radius={0.04}
              smoothness={2}
              position={[0, 0.5, 0]}
              castShadow
            >
              <meshStandardMaterial
                ref={boxMat}
                color="#3b82f6"
                roughness={0.6}
              />
              <Edges threshold={15} color="#0f172a" />
            </RoundedBox>
          </group>
        )}
      </group>
    </group>
  )
}

// Grid routes from the receiving area (front-left, x≈-12) out through the side
// aisles (x≈±15, clear of the conveyor) to drop pads at the racks.
const FORK_ROUTES: {
  points: [number, number][]
  color: string
  speed: number
  phase: number
  drop: string
}[] = [
  {
    points: [
      [-12, -9],
      [-15, -9],
      [-15, 18],
    ],
    color: "#eab308",
    speed: 2.8,
    phase: 0,
    drop: "Drop A",
  },
  {
    points: [
      [-12, -7],
      [15, -7],
      [15, 17],
    ],
    color: "#ea7a09",
    speed: 2.4,
    phase: 0.4,
    drop: "Drop B",
  },
  {
    points: [
      [-12, -5],
      [-17, -5],
      [-17, 9],
    ],
    color: "#eab308",
    speed: 2.6,
    phase: 0.75,
    drop: "Drop C",
  },
]

const STAGE_SPOTS: [number, number][] = [
  [-13.2, -9.2],
  [-11.8, -9.2],
  [-13.2, -7.8],
  [-11.8, -7.8],
]

function ForkliftFleet({
  manifests,
  onManifest,
  forgeOpen,
  followRef,
}: {
  manifests: Manifest[]
  onManifest: (m: Manifest) => void
  forgeOpen: boolean
  followRef?: React.MutableRefObject<Group | null>
}) {
  const pick = (i: number) =>
    manifests.length ? manifests[i % manifests.length] : undefined
  // Live cargo registry the logistics arcs read each frame.
  const cargoRefs = useRef<(Group | null)[]>([])
  const carryingRefs = useRef<boolean[]>([])
  // true when that forklift's box has turned green (successful drop).
  const dropRefs = useRef<boolean[]>([])
  // Receiving-dock shipments that ForgeAI should arc to (only staged spots that
  // actually hold a manifest).
  const stagedSpots = STAGE_SPOTS.filter((_, i) => !!pick(i))
  return (
    <group>
      <GridPad x={-12} z={-8} label="Receiving" />
      {/* inbound shipments staged at the dock */}
      {STAGE_SPOTS.map(([x, z], i) => {
        const m = pick(i)
        return m ? (
          <group key={`s${i}`} position={[x, 0, z]}>
            <ManifestPallet manifest={m} onSelect={onManifest} scale={0.8} />
          </group>
        ) : null
      })}
      {FORK_ROUTES.map((r, i) => {
        const end = r.points[r.points.length - 1]
        const m = pick(i + STAGE_SPOTS.length)
        return (
          <group key={i}>
            <GridPad x={end[0]} z={end[1]} label={r.drop} />
            {/* delivered shipment dropped beside the rack */}
            {m && (
              <group position={[end[0], 0, end[1] + 1.6]}>
                <ManifestPallet
                  manifest={m}
                  onSelect={onManifest}
                  scale={0.8}
                />
              </group>
            )}
            <MovingForklift
              points={r.points}
              color={r.color}
              speed={r.speed}
              phase={r.phase}
              manifest={m}
              onManifest={onManifest}
              index={i}
              cargoRefs={cargoRefs}
              carryingRefs={carryingRefs}
              dropRefs={dropRefs}
              followRef={i === 0 ? followRef : undefined}
            />
          </group>
        )
      })}
      <ForgeLogistics
        visible={forgeOpen}
        count={FORK_ROUTES.length}
        cargoRefs={cargoRefs}
        carryingRefs={carryingRefs}
        dropRefs={dropRefs}
        staging={stagedSpots}
      />
    </group>
  )
}

function Warehouse() {
  return (
    <group>
      {/* back-wall racking row */}
      {[-16, -5.5, 5.5, 16].map((x) => (
        <group key={x} position={[x, 0, BLD.backZ - 2.4]}>
          <RackUnit width={8} levels={3} />
        </group>
      ))}
      {/* secondary interior row (with an aisle in front of the back row) */}
      {[-16, 16].map((x) => (
        <group key={x} position={[x, 0, BLD.backZ - 7]}>
          <RackUnit width={8} levels={3} />
        </group>
      ))}
      {/* side-wall racking (rotated to run along the depth) */}
      {[6, 13].map((z) => (
        <group
          key={`r${z}`}
          position={[BLD.side - 1.6, 0, z]}
          rotation={[0, Math.PI / 2, 0]}
        >
          <RackUnit width={6} levels={3} />
        </group>
      ))}
      {[13].map((z) => (
        <group
          key={`l${z}`}
          position={[-BLD.side + 1.6, 0, z]}
          rotation={[0, Math.PI / 2, 0]}
        >
          <RackUnit width={6} levels={3} />
        </group>
      ))}
      {/* staged pallets near the line */}
      {/* staged pallets on open floor, clear of the line entities */}
      <PalletStack x={-18} z={12} />
      <PalletStack x={18} z={12} />
      <PalletStack x={18} z={6} />
    </group>
  )
}

function ReceivingBay() {
  return (
    <group position={[-12, 0, BLD.frontZ - 0.4]}>
      <RoundedBox
        args={[5, 0.8, 2.4]}
        radius={0.05}
        smoothness={3}
        position={[0, 0.4, 0.8]}
        castShadow
        receiveShadow
      >
        <meshStandardMaterial color="#20242c" metalness={0.4} roughness={0.6} />
      </RoundedBox>
      {[-1.3, 1.3].map((x) => (
        <RoundedBox
          key={x}
          args={[2.2, 3.6, 0.14]}
          radius={0.04}
          smoothness={3}
          position={[x, 2.4, 0.1]}
          castShadow
        >
          <meshStandardMaterial color={WHITE} metalness={0.1} roughness={0.5} />
          <Edges threshold={15} color="#c7cdd7" />
        </RoundedBox>
      ))}
      {/* truck */}
      <group position={[0, 0, -3.2]}>
        <RoundedBox
          args={[3, 2.2, 4.2]}
          radius={0.12}
          smoothness={4}
          position={[0, 1.4, 0]}
          castShadow
        >
          <meshStandardMaterial
            color="#e6eaf0"
            metalness={0.3}
            roughness={0.4}
          />
        </RoundedBox>
        <RoundedBox
          args={[2.8, 1.6, 1.2]}
          radius={0.12}
          smoothness={4}
          position={[0, 1.1, -2.6]}
          castShadow
        >
          <meshStandardMaterial
            color={ACCENT}
            metalness={0.4}
            roughness={0.35}
          />
        </RoundedBox>
        {[
          [-1.2, -1.4],
          [1.2, -1.4],
          [-1.2, 1.4],
          [1.2, 1.4],
        ].map(([x, z], i) => (
          <mesh key={i} position={[x, 0.4, z]} rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[0.4, 0.4, 0.3, 20]} />
            <meshStandardMaterial color="#0b0c0f" roughness={0.9} />
          </mesh>
        ))}
      </group>
    </group>
  )
}

const CAR_COLORS = [
  "#3b82f6",
  "#ef4444",
  "#22c55e",
  "#eab308",
  "#a855f7",
  "#e2e8f0",
]

function ParkingLot() {
  // Parking is set well back from the building, across a driveway apron.
  const cars = useMemo(() => {
    const out: { x: number; z: number; c: string }[] = []
    ;[-34, -29].forEach((z, r) => {
      for (let i = 0; i < 10; i++) {
        if ((i + r) % 3 === 0) continue
        out.push({
          x: -18 + i * 4,
          z,
          c: CAR_COLORS[(i + r) % CAR_COLORS.length],
        })
      }
    })
    return out
  }, [])

  return (
    <group>
      {/* driveway apron between the building front and the lot */}
      <mesh
        position={[0, 0.004, -16]}
        rotation={[-Math.PI / 2, 0, 0]}
        receiveShadow
      >
        <planeGeometry args={[46, 12]} />
        <meshStandardMaterial color="#1b1e24" roughness={0.9} />
      </mesh>
      {/* dashed centre lane on the apron */}
      <Instances limit={8}>
        <boxGeometry args={[1.6, 0.02, 0.18]} />
        <meshStandardMaterial color="#cdd4de" />
        {Array.from({ length: 7 }, (_, i) => -18 + i * 6).map((x) => (
          <Instance key={x} position={[x, 0.014, -16]} />
        ))}
      </Instances>
      {/* asphalt lot */}
      <mesh
        position={[0, 0.005, -30]}
        rotation={[-Math.PI / 2, 0, 0]}
        receiveShadow
      >
        <planeGeometry args={[46, 18]} />
        <meshStandardMaterial color="#14161b" roughness={0.95} />
      </mesh>
      <Instances limit={64}>
        <boxGeometry args={[0.12, 0.02, 3.4]} />
        <meshStandardMaterial color="#cdd4de" />
        {[-34, -29, -24].flatMap((z) =>
          Array.from({ length: 11 }, (_, i) => -20 + i * 4).map((x) => (
            <Instance key={`${z}-${x}`} position={[x, 0.02, z]} />
          )),
        )}
      </Instances>
      {cars.map((c, i) => (
        <group key={i} position={[c.x, 0, c.z]}>
          <RoundedBox
            args={[1.7, 0.6, 3.2]}
            radius={0.18}
            smoothness={3}
            position={[0, 0.45, 0]}
          >
            <meshStandardMaterial
              color={c.c}
              metalness={0.7}
              roughness={0.3}
              envMapIntensity={1.2}
            />
          </RoundedBox>
          <RoundedBox
            args={[1.5, 0.55, 1.7]}
            radius={0.2}
            smoothness={3}
            position={[0, 0.95, -0.2]}
          >
            <meshStandardMaterial
              color="#0e1116"
              metalness={0.6}
              roughness={0.15}
              envMapIntensity={1.5}
            />
          </RoundedBox>
        </group>
      ))}
    </group>
  )
}

function DecorCubes() {
  const cubes = useMemo(
    () => [
      { p: [9, 0.75, 6], s: 1.5 },
      { p: [9, 0.5, 8], s: 1 },
      { p: [-10, 1, 7], s: 2 },
      { p: [7, 0.4, -2], s: 0.8 },
      { p: [-7, 0.6, -2], s: 1.2 },
      { p: [10, 0.3, 2], s: 0.6 },
      { p: [4, 0.3, 7.5], s: 0.6 },
      { p: [-4, 0.4, 7.5], s: 0.8 },
    ],
    [],
  )
  return (
    <group>
      {cubes.map((c, i) => (
        <RoundedBox
          key={i}
          args={[c.s, c.s, c.s]}
          radius={Math.min(0.12, c.s * 0.12)}
          smoothness={3}
          position={c.p as [number, number, number]}
          receiveShadow
        >
          <meshStandardMaterial
            color={WHITE}
            metalness={0.05}
            roughness={0.5}
            envMapIntensity={0.8}
          />
          <Edges threshold={15} color="#d4dae3" />
        </RoundedBox>
      ))}
    </group>
  )
}

/* ---------------------------------------------------- ForgeAI scene beacon */

/**
 * The floating accent crystal above the centre machine. Clicking it opens the
 * ForgeAI assistant; it enlarges on hover/open to invite interaction.
 */
function ForgeBeacon({ open, onOpen }: { open: boolean; onOpen: () => void }) {
  const [hovered, setHovered] = useState(false)
  const ref = useRef<Mesh>(null)

  useEffect(
    () => () => {
      document.body.style.cursor = "auto"
    },
    [],
  )

  // Smoothly grow when the agent is open/hovered, and add a slow bob while
  // open (selected) so the cube reads as "active".
  useFrame((state, dt) => {
    const m = ref.current
    if (!m) return
    const target = open ? 1.6 : hovered ? 1.25 : 1
    const k = Math.min(1, dt * 5)
    m.scale.setScalar(m.scale.x + (target - m.scale.x) * k)
    const amp = open ? 0.18 : 0.05
    const speed = open ? 1.1 : 1.6
    m.position.y = Math.sin(state.clock.elapsedTime * speed) * amp
  })

  return (
    <group position={[0, 7, 0]}>
      <Float speed={1.2} rotationIntensity={0.5} floatIntensity={0.4}>
        {/* biome-ignore lint/a11y/noStaticElementInteractions: react-three-fiber scene node, not a DOM element */}
        <mesh
          ref={ref}
          onClick={(e) => {
            e.stopPropagation()
            onOpen()
          }}
          onPointerOver={(e) => {
            e.stopPropagation()
            setHovered(true)
            document.body.style.cursor = "pointer"
          }}
          onPointerOut={() => {
            setHovered(false)
            document.body.style.cursor = "auto"
          }}
        >
          <icosahedronGeometry args={[0.5, 0]} />
          <meshStandardMaterial
            color={ACCENT}
            emissive={ACCENT}
            emissiveIntensity={open ? 3.2 : hovered ? 2.6 : 1.8}
            metalness={0.4}
            roughness={0.2}
            toneMapped={false}
          />
        </mesh>
        <Html
          position={[0, 1, 0]}
          center
          distanceFactor={14}
          zIndexRange={[20, 0]}
        >
          <div className="pointer-events-none flex select-none items-center gap-1 whitespace-nowrap rounded-full border border-sky-400/40 bg-black/70 px-2.5 py-0.5 text-[10px] font-semibold tracking-wide text-sky-200 backdrop-blur">
            ForgeAI{!open && <span className="text-sky-400/70">· ask</span>}
          </div>
        </Html>
      </Float>
    </group>
  )
}

/**
 * Orthogonal "hierarchy" connectors drawn from the ForgeAI cube down to a bus
 * and out to each line entity — shown while ForgeAI is open to signal that the
 * whole line is actively selected.
 */
function ForgeLinks({ xs }: { xs: number[] }) {
  const cubeY = 7
  const busY = 3.35
  const topY = 2.7
  const minX = Math.min(...xs, 0)
  const maxX = Math.max(...xs, 0)
  const line = (pts: [number, number, number][], key: string) => (
    <Line
      key={key}
      points={pts}
      color={ACCENT}
      lineWidth={2}
      transparent
      opacity={0.85}
    />
  )
  return (
    <group>
      {line(
        [
          [0, cubeY, 0],
          [0, busY, 0],
        ],
        "trunk",
      )}
      {line(
        [
          [minX, busY, 0],
          [maxX, busY, 0],
        ],
        "bus",
      )}
      {xs.map((x, i) =>
        line(
          [
            [x, busY, 0],
            [x, topY, 0],
          ],
          `b${i}`,
        ),
      )}
      {/* small nodes where branches meet the bus */}
      {xs.map((x, i) => (
        <mesh key={`n${i}`} position={[x, busY, 0]}>
          <sphereGeometry args={[0.06, 12, 12]} />
          <meshBasicMaterial color={ACCENT} toneMapped={false} />
        </mesh>
      ))}
    </group>
  )
}

// Cube world position (production group is offset z=+2; the beacon sits at
// local [0, 4.3, 0]). Used as the origin for the green logistics arcs.
const CUBE_WORLD: [number, number, number] = [0, 7, 2]
const ARC_SEG = 22
// Logistics arcs match the cargo-box state: blue while in transit, green on a
// successful drop/transaction. Shared, never-mutated lerp targets.
const LOGI_BLUE = "#3b82f6"
const LOGI_GREEN = "#22c55e"
const _BOX_BLUE = new Color(LOGI_BLUE)
const _BOX_GREEN = new Color(LOGI_GREEN)

// A thin curved arc from the ForgeAI cube out to a tracked package.
function forgeArc(end: Vector3): Vector3[] {
  const start = new Vector3(...CUBE_WORLD)
  const mid = start.clone().lerp(end, 0.5)
  mid.y += start.distanceTo(end) * 0.22 + 1.4
  return new QuadraticBezierCurve3(start, mid, end).getPoints(ARC_SEG - 1)
}
function forgeArcFlat(end: Vector3, out: number[]): number[] {
  const pts = forgeArc(end)
  for (let i = 0; i < pts.length; i++) {
    out[i * 3] = pts[i].x
    out[i * 3 + 1] = pts[i].y
    out[i * 3 + 2] = pts[i].z
  }
  return out
}

// Thin solid green arcs from the cube to every package ForgeAI is actively
// tracking — each forklift's carried cargo (dynamic, follows the truck) and the
// shipments staged in receiving (static). Same philosophy as the blue hierarchy
// lines, but green + arced to read as live logistics.
function ForgeLogistics({
  visible,
  count,
  cargoRefs,
  carryingRefs,
  dropRefs,
  staging,
}: {
  visible: boolean
  count: number
  cargoRefs: React.MutableRefObject<(Group | null)[]>
  carryingRefs: React.MutableRefObject<boolean[]>
  dropRefs: React.MutableRefObject<boolean[]>
  staging: [number, number][]
}) {
  // drei Line2 ref (geometry.setPositions)
  const lineRefs = useRef<any[]>([])
  const tmp = useMemo(() => new Vector3(), [])
  const buf = useMemo(() => new Array(ARC_SEG * 3).fill(0), [])
  const placeholder = useMemo(
    () =>
      forgeArc(new Vector3(...CUBE_WORLD)).map(
        (p) => [p.x, p.y, p.z] as [number, number, number],
      ),
    [],
  )
  const stagingArcs = useMemo(
    () =>
      staging.map(([x, z]) =>
        forgeArc(new Vector3(x, 0.8, z)).map(
          (p) => [p.x, p.y, p.z] as [number, number, number],
        ),
      ),
    [staging],
  )

  useFrame((_, dt) => {
    if (!visible) return
    const k = Math.min(1, dt * 4)
    for (let i = 0; i < count; i++) {
      const line = lineRefs.current[i]
      if (!line) continue
      const g = cargoRefs.current[i]
      if (!g || !carryingRefs.current[i]) {
        line.visible = false
        continue
      }
      line.visible = true
      g.getWorldPosition(tmp)
      tmp.y += 0.6
      forgeArcFlat(tmp, buf)
      line.geometry.setPositions(buf)
      // Match the cargo box: blue in transit, green on a successful drop —
      // smoothly transitioning between the two.
      const target = dropRefs.current[i] ? _BOX_GREEN : _BOX_BLUE
      if (line.material?.color) line.material.color.lerp(target, k)
    }
  })

  if (!visible) return null
  return (
    <group>
      {/* cube hub node */}
      <mesh position={CUBE_WORLD}>
        <sphereGeometry args={[0.08, 12, 12]} />
        <meshBasicMaterial color={LOGI_BLUE} toneMapped={false} />
      </mesh>
      {/* static arcs to staged receiving shipments (in transit → blue) */}
      {stagingArcs.map((pts, i) => (
        <Line
          key={`stage${i}`}
          points={pts}
          color={LOGI_BLUE}
          lineWidth={1.5}
          transparent
          opacity={0.85}
        />
      ))}
      {/* dynamic arcs to forklift-carried cargo (updated each frame). Default
          blue; lerps to green when that forklift's box turns green (drop). */}
      {Array.from({ length: count }, (_, i) => (
        <Line
          key={`cargo${i}`}
          ref={(el) => {
            lineRefs.current[i] = el
          }}
          points={placeholder}
          color={LOGI_BLUE}
          lineWidth={1.5}
          transparent
          opacity={0.9}
        />
      ))}
    </group>
  )
}

// Free-fly WASD panning layered on top of OrbitControls — moves both the camera
// and the orbit target across the ground plane (relative to view facing).
function WasdPan({
  controls,
}: {
  controls: React.RefObject<React.ComponentRef<typeof OrbitControls> | null>
}) {
  const camera = useThree((s) => s.camera)
  const keys = useRef<Record<string, boolean>>({})
  const fwd = useMemo(() => new Vector3(), [])
  const right = useMemo(() => new Vector3(), [])
  const move = useMemo(() => new Vector3(), [])
  const worldUp = useMemo(() => new Vector3(0, 1, 0), [])

  useEffect(() => {
    const typing = (t: EventTarget | null) => {
      const el = t as HTMLElement | null
      return (
        !!el &&
        (el.tagName === "INPUT" ||
          el.tagName === "TEXTAREA" ||
          el.isContentEditable)
      )
    }
    const down = (e: KeyboardEvent) => {
      const k = e.key.length === 1 ? e.key.toLowerCase() : ""
      if (k !== "w" && k !== "a" && k !== "s" && k !== "d") return
      if (typing(e.target)) return
      keys.current[k] = true
    }
    const up = (e: KeyboardEvent) => {
      if (e.key.length === 1) keys.current[e.key.toLowerCase()] = false
    }
    window.addEventListener("keydown", down)
    window.addEventListener("keyup", up)
    return () => {
      window.removeEventListener("keydown", down)
      window.removeEventListener("keyup", up)
    }
  }, [])

  useFrame((_, dt) => {
    const c = controls.current
    const k = keys.current
    if (!c || (!k.w && !k.a && !k.s && !k.d)) return
    camera.getWorldDirection(fwd)
    fwd.y = 0
    if (fwd.lengthSq() < 1e-6) return
    fwd.normalize()
    right.crossVectors(fwd, worldUp).normalize()
    move.set(0, 0, 0)
    if (k.w) move.add(fwd)
    if (k.s) move.sub(fwd)
    if (k.d) move.add(right)
    if (k.a) move.sub(right)
    if (move.lengthSq() === 0) return
    move.normalize().multiplyScalar(Math.min(dt, 0.05) * 26)
    camera.position.add(move)
    c.target.add(move)
    c.update()
  })

  return null
}

// One car looping along the elevated highway deck.
function HighwayCar({
  z0,
  dir,
  speed,
  lane,
  len,
  y,
}: {
  z0: number
  dir: 1 | -1
  speed: number
  lane: number
  len: number
  y: number // deck surface height — cars ride ON the deck, not beneath it
}) {
  const ref = useRef<Group>(null)
  const z = useRef(z0)
  useFrame((_, dt) => {
    const g = ref.current
    if (!g) return
    z.current += dir * speed * Math.min(dt, 0.05)
    const half = len / 2
    if (z.current > half) z.current = -half
    else if (z.current < -half) z.current = half
    g.position.z = z.current
  })
  const tail = dir === 1 ? "#f87171" : "#fde047"
  return (
    <group
      ref={ref}
      position={[lane, y, z0]}
      rotation={[0, dir === 1 ? 0 : Math.PI, 0]}
    >
      <RoundedBox
        args={[0.9, 0.5, 1.9]}
        radius={0.12}
        smoothness={2}
        position={[0, 0.3, 0]}
      >
        <meshStandardMaterial color="#e3e9f1" metalness={0.5} roughness={0.4} />
      </RoundedBox>
      <mesh position={[0, 0.28, -0.97]}>
        <boxGeometry args={[0.7, 0.16, 0.04]} />
        <meshStandardMaterial
          color={tail}
          emissive={tail}
          emissiveIntensity={2.4}
          toneMapped={false}
        />
      </mesh>
    </group>
  )
}

// Elevated highway running alongside the lot (left side), on pillars, with lane
// markings, a glowing center divider and looping traffic. Pure decor.
function ElevatedHighway() {
  const X = 64 // set well back from the building + office wing
  const Y = 7
  const LEN = 380 // runs far into the distance
  const DECK = Y + 0.3 // deck top surface — cars ride here
  const pillars = useMemo(
    () => Array.from({ length: 24 }, (_, i) => -184 + i * 16),
    [],
  )
  const dashes = useMemo(
    () => Array.from({ length: 63 }, (_, i) => -186 + i * 6),
    [],
  )
  return (
    <group position={[X, 0, BLD.cz]}>
      {pillars.map((z) => (
        <mesh key={z} position={[0, Y / 2, z]} castShadow>
          <boxGeometry args={[2.2, Y, 2.2]} />
          <meshStandardMaterial
            color="#39414f"
            metalness={0.3}
            roughness={0.7}
          />
        </mesh>
      ))}
      <mesh position={[0, Y, 0]} receiveShadow>
        <boxGeometry args={[12, 0.6, LEN]} />
        <meshStandardMaterial color="#23272f" metalness={0.4} roughness={0.6} />
      </mesh>
      {[-5.8, 5.8].map((x) => (
        <mesh key={x} position={[x, Y + 0.45, 0]}>
          <boxGeometry args={[0.18, 0.6, LEN]} />
          <meshStandardMaterial
            color="#11151c"
            metalness={0.4}
            roughness={0.5}
          />
        </mesh>
      ))}
      <mesh position={[0, Y + 0.34, 0]}>
        <boxGeometry args={[0.14, 0.06, LEN]} />
        <meshStandardMaterial
          color={ACCENT}
          emissive={ACCENT}
          emissiveIntensity={1.8}
          toneMapped={false}
        />
      </mesh>
      {dashes.flatMap((z) =>
        [-3, 3].map((x) => (
          <mesh key={`${x}_${z}`} position={[x, Y + 0.32, z]}>
            <boxGeometry args={[0.12, 0.02, 1.6]} />
            <meshStandardMaterial
              color="#cbd5e1"
              emissive="#cbd5e1"
              emissiveIntensity={0.5}
              toneMapped={false}
            />
          </mesh>
        )),
      )}
      <HighwayCar z0={-150} dir={1} speed={14} lane={-3} len={LEN} y={DECK} />
      <HighwayCar z0={-40} dir={1} speed={11} lane={-3} len={LEN} y={DECK} />
      <HighwayCar z0={90} dir={1} speed={16} lane={-3} len={LEN} y={DECK} />
      <HighwayCar z0={150} dir={-1} speed={13} lane={3} len={LEN} y={DECK} />
      <HighwayCar z0={20} dir={-1} speed={15} lane={3} len={LEN} y={DECK} />
      <HighwayCar z0={-100} dir={-1} speed={12} lane={3} len={LEN} y={DECK} />
    </group>
  )
}

// A slow freight train looping along the rail line.
function FreightTrain({ len }: { len: number }) {
  const ref = useRef<Group>(null)
  const z = useRef(-len / 2)
  useFrame((_, dt) => {
    const g = ref.current
    if (!g) return
    z.current += 7 * Math.min(dt, 0.05)
    if (z.current > len / 2 + 26) z.current = -len / 2 - 26
    g.position.z = z.current
  })
  return (
    <group ref={ref}>
      {[0, 1, 2, 3, 4].map((i) => (
        <RoundedBox
          key={i}
          args={[2.2, 1.4, 5]}
          radius={0.12}
          smoothness={2}
          position={[0, 1.05, i * -6]}
          castShadow
        >
          <meshStandardMaterial
            color={i === 0 ? "#2b3340" : i % 2 ? "#6b5642" : "#4a5a6a"}
            metalness={0.45}
            roughness={0.55}
          />
        </RoundedBox>
      ))}
    </group>
  )
}

// Ground-level rail line where the highway used to be (other side of the lot).
function Railroad() {
  const X = -46
  const LEN = 380 // runs far into the distance
  const ties = useMemo(
    () => Array.from({ length: 152 }, (_, i) => -189 + i * 2.5),
    [],
  )
  return (
    <group position={[X, 0, BLD.cz]}>
      {/* ballast bed */}
      <mesh position={[0, 0.08, 0]} receiveShadow>
        <boxGeometry args={[4, 0.16, LEN]} />
        <meshStandardMaterial color="#3a3631" roughness={1} />
      </mesh>
      {/* sleepers / ties */}
      {ties.map((z) => (
        <mesh key={z} position={[0, 0.2, z]} castShadow>
          <boxGeometry args={[3, 0.12, 0.5]} />
          <meshStandardMaterial color="#5b4a3a" roughness={0.9} />
        </mesh>
      ))}
      {/* rails */}
      {[-0.75, 0.75].map((x) => (
        <mesh key={x} position={[x, 0.3, 0]}>
          <boxGeometry args={[0.12, 0.14, LEN]} />
          <meshStandardMaterial
            color="#9aa3b0"
            metalness={0.9}
            roughness={0.35}
          />
        </mesh>
      ))}
      <FreightTrain len={LEN} />
    </group>
  )
}

// ---- Attached office wing --------------------------------------------------
// A roofless, open-plan office wing abutting the main building's open (+x) side,
// running the FULL length of the building and partitioned into small offices per
// section (so you can see into the rooms from the orbit camera).
function AttachedOffice() {
  const W = 12
  const D = BLD.d // span the full building length
  const H = 3.2 // low cubicle/office walls (no roof)
  const X = BLD.side + W / 2 // inner wall flush with the building side wall
  const Z = BLD.cz // centered on the building, front↔back
  const ROOMS = 7
  const roomD = D / ROOMS
  // Interior partition planes between sections.
  const partitions = useMemo(
    () => Array.from({ length: ROOMS - 1 }, (_, i) => -D / 2 + (i + 1) * roomD),
    [roomD],
  )
  // One desk centered in each room.
  const desks = useMemo(
    () => Array.from({ length: ROOMS }, (_, i) => -D / 2 + (i + 0.5) * roomD),
    [roomD],
  )
  return (
    <group position={[X, 0, Z]}>
      {/* floor slab */}
      <mesh position={[0, 0.1, 0]} receiveShadow>
        <boxGeometry args={[W, 0.2, D]} />
        <meshStandardMaterial color="#1a1e26" metalness={0.3} roughness={0.7} />
      </mesh>

      {/* perimeter glass walls (no top → roof removed) */}
      {/* outer (+x) */}
      <mesh position={[W / 2, H / 2, 0]}>
        <boxGeometry args={[0.16, H, D]} />
        <meshStandardMaterial
          color={ACCENT}
          transparent
          opacity={0.18}
          metalness={0.1}
          roughness={0.05}
        />
      </mesh>
      {/* inner (-x), flush with the building */}
      <mesh position={[-W / 2, H / 2, 0]}>
        <boxGeometry args={[0.16, H, D]} />
        <meshStandardMaterial color="#222831" metalness={0.5} roughness={0.5} />
      </mesh>
      {/* end caps (front/-z and back/+z) */}
      {[-D / 2, D / 2].map((z) => (
        <mesh key={z} position={[0, H / 2, z]}>
          <boxGeometry args={[W, H, 0.16]} />
          <meshStandardMaterial
            color={ACCENT}
            transparent
            opacity={0.18}
            metalness={0.1}
            roughness={0.05}
          />
        </mesh>
      ))}
      {/* base plinth band around the whole wing */}
      <mesh position={[0, 0.45, 0]}>
        <boxGeometry args={[W + 0.12, 0.5, D + 0.12]} />
        <meshStandardMaterial color="#161a21" metalness={0.4} roughness={0.6} />
      </mesh>

      {/* interior partition walls — one small office per section */}
      {partitions.map((z) => (
        <mesh key={z} position={[0, H * 0.4, z]} castShadow>
          <boxGeometry args={[W - 0.4, H * 0.8, 0.12]} />
          <meshStandardMaterial
            color="#2b3340"
            metalness={0.4}
            roughness={0.55}
          />
        </mesh>
      ))}

      {/* a desk in each office section */}
      {desks.map((z) => (
        <group key={z} position={[1.4, 0.2, z]}>
          <mesh position={[0, 0.55, 0]} castShadow>
            <boxGeometry args={[2.2, 0.1, 1.1]} />
            <meshStandardMaterial
              color="#3a4150"
              metalness={0.3}
              roughness={0.6}
            />
          </mesh>
          {/* monitor */}
          <mesh position={[0, 1.0, -0.35]}>
            <boxGeometry args={[0.9, 0.55, 0.06]} />
            <meshStandardMaterial
              color="#0a1622"
              emissive={ACCENT}
              emissiveIntensity={1.1}
              toneMapped={false}
            />
          </mesh>
        </group>
      ))}

      {/* entrance + canopy (faces the approach, -z corner) */}
      <mesh position={[0, 1.05, -D / 2 - 0.05]}>
        <boxGeometry args={[2.2, 2.1, 0.1]} />
        <meshStandardMaterial color="#0d0f13" metalness={0.3} roughness={0.6} />
      </mesh>
      <mesh position={[0, 2.3, -D / 2 - 1]} castShadow>
        <boxGeometry args={[3.4, 0.16, 2]} />
        <meshStandardMaterial color={STEEL} metalness={0.6} roughness={0.4} />
      </mesh>

      {/* signage on the outer wall */}
      <mesh
        position={[W / 2 + 0.05, H - 0.4, -D / 2 + 4]}
        rotation={[0, Math.PI / 2, 0]}
      >
        <boxGeometry args={[6, 0.5, 0.06]} />
        <meshStandardMaterial
          color={ACCENT}
          emissive={ACCENT}
          emissiveIntensity={2}
          toneMapped={false}
        />
      </mesh>
      <Html
        position={[W / 2 + 0.16, H - 0.4, -D / 2 + 4]}
        center
        distanceFactor={26}
        rotation={[0, Math.PI / 2, 0]}
      >
        <div className="pointer-events-none select-none whitespace-nowrap text-xs font-semibold tracking-[0.3em] text-sky-200">
          OFFICES
        </div>
      </Html>
    </group>
  )
}

function Lights({ dark }: { dark: boolean }) {
  return (
    <>
      <ambientLight intensity={dark ? 0.28 : 0.6} />
      <directionalLight
        position={[14, 20, 8]}
        intensity={dark ? 1.5 : 1.9}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-28}
        shadow-camera-right={28}
        shadow-camera-top={28}
        shadow-camera-bottom={-28}
        shadow-bias={-0.0004}
      />
      <pointLight
        position={[-10, 8, -6]}
        intensity={dark ? 45 : 22}
        color="#38bdf8"
        distance={44}
      />
      <pointLight
        position={[10, 6, 8]}
        intensity={dark ? 32 : 16}
        color="#a855f7"
        distance={44}
      />
      <Environment resolution={256}>
        <Lightformer
          intensity={2}
          position={[0, 9, -2]}
          scale={[14, 5, 1]}
          color="#cfe0ff"
        />
        <Lightformer
          intensity={1.6}
          position={[8, 6, 8]}
          scale={[6, 6, 1]}
          color="#ffffff"
        />
        <Lightformer
          intensity={1.2}
          position={[-8, 5, 6]}
          scale={[5, 5, 1]}
          color="#bcd3ff"
        />
      </Environment>
    </>
  )
}

/* ----------------------------------------------------------------- scene */

// Cinematic camera director: after ForgeAI answers (on the simulation page) it
// flies to / follows the entities in the response — machine, fleet, the
// receiving dock, or a moving forklift for PO/logistics queries.
const _camTmp = new Vector3()

function CameraDirector({
  focus,
  machines,
  controls,
  followRef,
}: {
  focus: ForgeFocus | null
  machines: LiveMachine[]
  controls: React.RefObject<React.ComponentRef<typeof OrbitControls> | null>
  followRef: React.MutableRefObject<Group | null>
}) {
  const camera = useThree((s) => s.camera)
  const machinesRef = useRef(machines)
  machinesRef.current = machines
  const lastToken = useRef<number>(-1)
  const anim = useRef<{
    follow: boolean
    target: Vector3
    camPos: Vector3
    until: number
  } | null>(null)

  // Cancel the cinematic move the moment the user grabs the controls.
  useEffect(() => {
    const c = controls.current
    if (!c) return
    const cancel = () => {
      anim.current = null
    }
    c.addEventListener("start", cancel)
    return () => c.removeEventListener("start", cancel)
  }, [controls])

  useFrame((state, dt) => {
    const c = controls.current
    if (!c) return
    const f = focus

    if (f && f.token !== lastToken.current) {
      lastToken.current = f.token
      // The factory is viewed FROM THE FRONT (the parking lot, −z) looking IN
      // (+z), below the roofline — so the glass front (see-through) is between
      // the camera and the floor and the solid back wall / roof trusses never
      // obstruct. All offsets therefore carry a negative z.
      const target = new Vector3(0, 2, 6)
      let off = new Vector3(7, 9, -34)
      let follow = false
      if (f.point) {
        // an explicit line device (PLC cabinet / server rack)
        target.set(f.point.x, 1.6, f.point.z)
        off = new Vector3(3, 4, -11)
      } else if (f.mode === "logistics" && f.follow_forklift) {
        follow = true
        off = new Vector3(4, 6, -10)
      } else if (f.mode === "inventory") {
        target.set(-13, 1, -7) // receiving dock
        off = new Vector3(4, 7, -14)
      } else if (f.mode === "fleet") {
        target.set(0, 2, 6)
        off = new Vector3(8, 11, -36)
      } else if (f.mode === "reset") {
        // Default establishing shot (matches the initial camera).
        target.set(0, 2, 6)
        off = new Vector3(7, 9, -34)
      } else if (f.machine_ids.length) {
        const ms = machinesRef.current.filter((m) =>
          f.machine_ids.includes(m.id),
        )
        if (ms.length) {
          const ax = ms.reduce((a, m) => a + m.pos_x, 0) / ms.length
          target.set(ax, 1.6, 2)
          off = ms.length > 1 ? new Vector3(4, 8, -18) : new Vector3(3, 4, -11)
        }
      }
      anim.current = {
        follow,
        target,
        camPos: target.clone().add(off),
        // Forklift-follow runs continually (until the user grabs the controls);
        // fixed shots settle after a couple seconds.
        until: follow
          ? Number.POSITIVE_INFINITY
          : state.clock.elapsedTime + 2.4,
      }
    }

    const a = anim.current
    if (!a) return
    // Follow mode keeps re-aiming at the moving forklift each frame.
    if (a.follow && followRef.current) {
      followRef.current.getWorldPosition(_camTmp)
      a.target.set(_camTmp.x, 0.9, _camTmp.z)
      // trail the forklift from the front (parking-lot) side
      a.camPos.set(_camTmp.x + 4, _camTmp.y + 6, _camTmp.z - 10)
    }
    const k = 1 - Math.exp(-3.2 * Math.min(dt, 0.05))
    camera.position.lerp(a.camPos, k)
    c.target.lerp(a.target, k)
    c.update()
    if (state.clock.elapsedTime > a.until) anim.current = null
  })

  return null
}

function Scene({
  machines,
  openIds,
  onToggle,
  onClose,
  highlightIds,
  focus,
  forgeOpen,
  onOpenForge,
  manifests,
  onManifest,
  palette,
  showGrid,
}: {
  machines: LiveMachine[]
  openIds: string[]
  onToggle: (id: string) => void
  onClose: (id: string) => void
  highlightIds: string[]
  focus: ForgeFocus | null
  forgeOpen: boolean
  onOpenForge: () => void
  manifests: Manifest[]
  onManifest: (m: Manifest) => void
  palette: ScenePalette
  showGrid: boolean
}) {
  const dark = palette.dark
  const setDpr = useThree((s) => s.setDpr)
  const controls = useRef<React.ComponentRef<typeof OrbitControls>>(null)
  // A live forklift group the camera can follow for logistics / PO queries.
  const followRef = useRef<Group | null>(null)
  // Latest machines without retriggering the focus effect on every telemetry poll.
  const machinesRef = useRef(machines)
  machinesRef.current = machines
  const lastFocus = useRef<string | null>(null)

  // Snap the camera target when a machine PANEL is pinned manually (clicks /
  // deep-link). ForgeAI-driven focus is handled cinematically by CameraDirector.
  useEffect(() => {
    const focusId = openIds[openIds.length - 1] ?? null
    if (!focusId || focusId === lastFocus.current) return
    lastFocus.current = focusId
    const m = machinesRef.current.find((x) => x.id === focusId)
    if (m && controls.current) {
      controls.current.target.set(m.pos_x, 1.2, 2)
      controls.current.update()
    }
  }, [openIds])

  return (
    <>
      <color attach="background" args={[palette.bg]} />
      <fog attach="fog" args={[palette.bg, 70, 300]} />
      <PerformanceMonitor
        onDecline={() => setDpr(1)}
        onIncline={() => setDpr(1.75)}
      />
      <Suspense fallback={null}>
        <Lights dark={dark} />

        {/* Base ground sits below every other floor surface to avoid z-fighting. */}
        <mesh
          position={[0, -0.05, 0]}
          rotation={[-Math.PI / 2, 0, 0]}
          receiveShadow
        >
          <planeGeometry args={[420, 420]} />
          <meshStandardMaterial color={palette.floor} roughness={1} />
        </mesh>
        {/* Optional reference grid. Thicker lines + a tighter fade stop the
            distant lines from shimmering, and it sits above all floors. */}
        {showGrid && (
          <Grid
            args={[200, 200]}
            cellSize={1}
            cellThickness={0.7}
            cellColor={palette.cell}
            sectionSize={10}
            sectionThickness={1.4}
            sectionColor={palette.section}
            fadeDistance={60}
            fadeStrength={2}
            infiniteGrid
            position={[0, 0.08, 0]}
          />
        )}

        <ParkingLot />
        <Building />
        <Warehouse />
        <ForkliftFleet
          manifests={manifests}
          onManifest={onManifest}
          forgeOpen={forgeOpen}
          followRef={followRef}
        />
        <ReceivingBay />
        <DecorCubes />
        {/* surrounding location: elevated highway (one side), rail line (other),
            attached office wing */}
        <ElevatedHighway />
        <Railroad />
        <AttachedOffice />

        <group position={[0, 0, 2]}>
          <Conveyor />
          {machines.map((m) => (
            <MachineStation
              key={m.id}
              machine={m}
              open={openIds.includes(m.id)}
              highlighted={highlightIds.includes(m.id)}
              onToggle={() => onToggle(m.id)}
              onClose={() => onClose(m.id)}
            />
          ))}
          {/* server rack at the start of the line, PLC cabinet on the line */}
          <LineFixture
            code="srv-01"
            name="Edge Server Rack"
            kind="server"
            position={[-11, 0, 0]}
            color={HEX.info}
            open={openIds.includes("srv-01")}
            stats={serverStats(machines)}
            onToggle={() => onToggle("srv-01")}
            onClose={() => onClose("srv-01")}
          >
            <group rotation={[0, Math.PI, 0]}>
              <ServerRackModel />
            </group>
          </LineFixture>
          <LineFixture
            code="plc-01"
            name="PLC Control Cabinet"
            kind="plc"
            position={[11, 0, 0]}
            color={HEX.info}
            open={openIds.includes("plc-01")}
            stats={plcStats(machines)}
            onToggle={() => onToggle("plc-01")}
            onClose={() => onClose("plc-01")}
          >
            <group rotation={[0, Math.PI, 0]}>
              <PlcCabinetModel />
            </group>
          </LineFixture>
          <ForgeBeacon open={forgeOpen} onOpen={onOpenForge} />
          {forgeOpen && (
            <ForgeLinks xs={[...machines.map((m) => m.pos_x), -11, 11]} />
          )}
        </group>

        <ContactShadows
          position={[0, 0.03, 4]}
          opacity={dark ? 0.5 : 0.35}
          scale={80}
          blur={2.6}
          far={18}
        />
      </Suspense>

      <OrbitControls
        ref={controls}
        makeDefault
        enableDamping
        minPolarAngle={0.15}
        maxPolarAngle={Math.PI / 2.05}
        minDistance={6}
        maxDistance={240}
        target={[0, 2, 6]}
      />
      <WasdPan controls={controls} />
      <CameraDirector
        focus={focus}
        machines={machines}
        controls={controls}
        followRef={followRef}
      />
      <GizmoHelper alignment="bottom-right" margin={[64, 64]}>
        <GizmoViewport labelColor="white" axisHeadScale={1} />
      </GizmoHelper>

      <EffectComposer enableNormalPass={false} multisampling={0}>
        <Bloom
          intensity={dark ? 0.9 : 0.4}
          luminanceThreshold={1}
          luminanceSmoothing={0.2}
          mipmapBlur
        />
        <Vignette eskil={false} offset={0.25} darkness={dark ? 0.7 : 0.3} />
        <SMAA />
      </EffectComposer>
    </>
  )
}

/* ------------------------------------------------------------------ page */

// The line's non-machine devices (LineFixtures), centerable from the menu.
// World positions match the <LineFixture> placements (inside the z=2 group).
const SIM_DEVICES = [
  { code: "plc-01", name: "PLC Control Cabinet", x: 11, icon: Cpu, tag: "PLC" },
  {
    code: "srv-01",
    name: "Edge Server Rack",
    x: -11,
    icon: Server,
    tag: "Server",
  },
] as const

function FactorySimulationPage() {
  const { theme, resolvedTheme } = useTheme()
  // "future" gets its own (black) scene palette; everything else maps to the
  // resolved light/dark palette. Adding a theme = adding a SCENE_THEME entry.
  const sceneKey: SceneKey = theme === "future" ? "future" : resolvedTheme
  const palette = SCENE_THEME[sceneKey]

  // Deep-link: /factory-map?machine=<id> auto-pins that machine's panel.
  const { machine: deepLinkId } = Route.useSearch()

  const { ticks, connected } = useTelemetryStream()
  const { data } = useQuery({
    queryKey: ["machines"],
    queryFn: () => sf.get<Page<Machine>>("/machines/"),
    refetchInterval: connected ? POLL.slow : POLL.fast,
  })
  // Multiple panels can be pinned at once; minimize closes one at a time.
  const [openIds, setOpenIds] = useState<string[]>(
    deepLinkId ? [deepLinkId] : [],
  )
  const [fullscreen, setFullscreen] = useState(false)
  const [showGrid, setShowGrid] = useState(false)
  // ForgeAI lives site-wide (layout level); the scene just reacts to it.
  const forge = useForgeAgent()
  const [manifest, setManifest] = useState<Manifest | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // Cinematic caption shown while ForgeAI steers the camera (auto-hides).
  const [cinematic, setCinematic] = useState<string | null>(null)
  useEffect(() => {
    const f = forge.focus
    if (!f?.label) return
    setCinematic(f.label)
    const hold = f.mode === "logistics" ? 9000 : 4200
    const t = window.setTimeout(() => setCinematic(null), hold)
    return () => window.clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [forge.focus])

  // Inventory + purchase orders → clickable shipment manifests on the pallets.
  const { data: invData } = useQuery({
    queryKey: ["inventory"],
    queryFn: () => sf.get<Page<InventoryItem>>("/inventory"),
    refetchInterval: POLL.slow,
  })
  const { data: poData } = useQuery({
    queryKey: ["purchase-orders"],
    queryFn: () => sf.get<Page<PurchaseOrder>>("/purchase-orders"),
    refetchInterval: POLL.slow,
  })
  const manifests: Manifest[] = useMemo(() => {
    const pos = poData?.data ?? []
    return (invData?.data ?? []).map((it) => {
      const po = pos.find((p) => p.inventory_item_id === it.id)
      return {
        id: it.id,
        sku: it.sku,
        name: it.name,
        quantity: it.quantity,
        belowThreshold: it.below_threshold,
        poId: po?.id,
        poNumber: po?.po_number,
        amount: po?.amount,
        poStatus: po?.status,
      }
    })
  }, [invData, poData])

  const toggleOpen = (id: string) =>
    setOpenIds((ids) =>
      ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id],
    )
  const closeOne = (id: string) =>
    setOpenIds((ids) => ids.filter((x) => x !== id))

  // Keep the pinned set in sync if the deep-link changes while mounted.
  useEffect(() => {
    if (deepLinkId)
      setOpenIds((ids) =>
        ids.includes(deepLinkId) ? ids : [...ids, deepLinkId],
      )
  }, [deepLinkId])

  useEffect(() => {
    const onChange = () => setFullscreen(Boolean(document.fullscreenElement))
    document.addEventListener("fullscreenchange", onChange)
    return () => document.removeEventListener("fullscreenchange", onChange)
  }, [])

  const toggleFullscreen = () => {
    if (document.fullscreenElement) document.exitFullscreen()
    else containerRef.current?.requestFullscreen?.()
  }

  // Polling fallback for live telemetry — guarantees temp/vibration show on the
  // panels even when the WebSocket is unavailable or still reconnecting.
  const ids = useMemo(() => (data?.data ?? []).map((m) => m.id), [data])
  const { data: latestTel } = useQuery({
    queryKey: ["sim-telemetry", ids],
    enabled: ids.length > 0,
    refetchInterval: POLL.medium,
    queryFn: async () => {
      const entries = await Promise.all(
        ids.map(async (id) => {
          const page = await sf.get<Page<TelemetryEvent>>(
            `/machines/${id}/telemetry?limit=1`,
          )
          return [id, page.data[0]] as const
        }),
      )
      return Object.fromEntries(entries) as Record<
        string,
        TelemetryEvent | undefined
      >
    },
  })

  const machines: LiveMachine[] = useMemo(
    () =>
      (data?.data ?? []).map((m) => {
        const tick = ticks[m.id]
        const tel = latestTel?.[m.id]
        return {
          ...m,
          liveHealth: tick?.health_score ?? m.health_score,
          liveStatus: tick?.status ?? m.status,
          liveTemp: tick?.temperature ?? tel?.temperature,
          liveVibration: tick?.vibration ?? tel?.vibration,
        }
      }),
    [data, ticks, latestTel],
  )

  // All camera moves — ForgeAI focus, the machine menu, "Reset View" and the
  // first-visit centering — flow through one directive the CameraDirector reads.
  const [camFocus, setCamFocus] = useState<ForgeFocus | null>(null)
  const camToken = useRef(0)
  const focusOn = useCallback(
    (partial: {
      mode: ForgeFocus["mode"]
      machine_ids?: string[]
      follow_forklift?: boolean
      label?: string
      point?: { x: number; z: number } | null
    }) => {
      camToken.current += 1
      setCamFocus({
        mode: partial.mode,
        machine_ids: partial.machine_ids ?? [],
        follow_forklift: partial.follow_forklift ?? false,
        label: partial.label ?? "",
        point: partial.point ?? null,
        token: camToken.current,
      })
    },
    [],
  )

  // ForgeAI focus → drive the camera.
  useEffect(() => {
    if (forge.focus) focusOn(forge.focus)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [forge.focus?.token, forge.focus, focusOn])

  // First visit: open on the front establishing shot (from the parking lot,
  // looking into the factory). The machine menu then centers on any machine.
  const centeredOnce = useRef(false)
  useEffect(() => {
    if (centeredOnce.current || machines.length === 0) return
    centeredOnce.current = true
    focusOn({ mode: "reset" })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [machines, focusOn])

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col gap-3">
      <PageHeader
        title="Smart Forge — Factory Simulation"
        description={
          <>
            3D digital twin · click a machine for a live panel, or a pallet for
            its shipment manifest ·{" "}
            <span className="font-medium text-foreground/80">WASD</span> to pan,
            drag/scroll to orbit.
          </>
        }
        actions={
          <span className="text-xs text-muted-foreground">
            {connected ? "● live telemetry" : "○ polling"}
          </span>
        }
      />

      <div
        ref={containerRef}
        className="sf-fade-in relative flex-1 overflow-hidden rounded-xl border"
        style={{ background: palette.bg }}
      >
        <Canvas
          shadows
          dpr={[1, 1.75]}
          gl={{ antialias: false, powerPreference: "high-performance" }}
          camera={{ position: [7, 11, -28], fov: 42, far: 400 }}
        >
          <Scene
            machines={machines}
            openIds={openIds}
            onToggle={toggleOpen}
            onClose={closeOne}
            highlightIds={forge.highlightIds}
            focus={camFocus}
            forgeOpen={forge.open}
            onOpenForge={() => forge.setOpen(true)}
            manifests={manifests}
            onManifest={setManifest}
            palette={palette}
            showGrid={showGrid}
          />
        </Canvas>

        {/* Cinematic caption while ForgeAI is steering the camera. */}
        {cinematic && (
          <div className="pointer-events-none absolute bottom-6 left-1/2 z-10 -translate-x-1/2">
            <div className="sf-fade-in flex items-center gap-2 rounded-full border border-primary/40 bg-black/65 px-4 py-2 text-sm font-medium text-white shadow-2xl backdrop-blur">
              <Sparkles size={14} className="text-primary" />
              {cinematic}
            </div>
          </div>
        )}

        {manifest && (
          <ManifestPanel
            manifest={manifest}
            onClose={() => setManifest(null)}
          />
        )}

        <div className="absolute right-4 top-4 flex items-center gap-2">
          <Button
            size="sm"
            onClick={() => focusOn({ mode: "reset" })}
            aria-label="Reset camera view"
            className="bg-info text-white shadow-lg backdrop-blur transition-all hover:brightness-110"
          >
            <RotateCcw size={15} /> Reset View
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setShowGrid((v) => !v)}
            aria-pressed={showGrid}
            className="bg-black/50 text-white backdrop-blur hover:bg-black/70"
          >
            <Grid3x3 size={15} /> {showGrid ? "Hide Grid" : "Show Grid"}
          </Button>
          <Button
            size="icon"
            variant="secondary"
            onClick={toggleFullscreen}
            aria-label={fullscreen ? "Exit full screen" : "Full screen"}
            className="bg-black/50 text-white backdrop-blur hover:bg-black/70"
          >
            {fullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
          </Button>
        </div>

        <div className="absolute left-4 top-4 flex items-center gap-3 rounded-lg border border-border bg-black/50 px-3 py-2 text-[11px] text-white backdrop-blur">
          <span className="flex items-center gap-1">
            <i
              className="size-2 rounded-full"
              style={{ background: "var(--success)" }}
            />{" "}
            Healthy
          </span>
          <span className="flex items-center gap-1">
            <i
              className="size-2 rounded-full"
              style={{ background: "var(--warning)" }}
            />{" "}
            At risk
          </span>
          <span className="flex items-center gap-1">
            <i
              className="size-2 rounded-full"
              style={{ background: "var(--danger)" }}
            />{" "}
            Critical
          </span>
        </div>

        {/* machine directory — click to center the camera on a machine */}
        <div className="absolute left-4 top-16 z-10 w-44 rounded-lg border border-border bg-black/55 p-2 text-white backdrop-blur">
          <p className="px-1 pb-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
            Machines
          </p>
          <ul className="max-h-[38vh] space-y-0.5 overflow-y-auto">
            {machines.map((m) => (
              <li key={m.id}>
                <button
                  type="button"
                  onClick={() =>
                    focusOn({ mode: "machine", machine_ids: [m.id] })
                  }
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors hover:bg-white/10"
                >
                  <span
                    className="size-2 shrink-0 rounded-full"
                    style={{ background: healthHex(m.liveHealth) }}
                  />
                  <span className="truncate font-medium">{m.code}</span>
                  <span className="ml-auto shrink-0 tabular-nums text-zinc-400">
                    {Math.round(m.liveHealth)}
                  </span>
                </button>
              </li>
            ))}
          </ul>

          {/* line devices (PLC cabinet, server rack) — click to center camera */}
          <p className="mt-2 border-t border-white/10 px-1 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
            Devices
          </p>
          <ul className="space-y-0.5">
            {SIM_DEVICES.map((d) => (
              <li key={d.code}>
                <button
                  type="button"
                  onClick={() =>
                    focusOn({ mode: "machine", point: { x: d.x, z: 2 } })
                  }
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors hover:bg-white/10"
                >
                  <d.icon size={13} className="shrink-0 text-info" />
                  <span className="truncate font-medium">{d.code}</span>
                  <span className="ml-auto shrink-0 text-zinc-400">
                    {d.tag}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
