import { Html, Line, OrbitControls, Stars } from "@react-three/drei"
import { Canvas, useFrame, useThree } from "@react-three/fiber"
import { Bloom, EffectComposer, Vignette } from "@react-three/postprocessing"
import { useQuery } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import { Building2, ChevronDown, ChevronRight, RotateCcw, Truck, X } from "lucide-react"
import { useMemo, useRef, useState } from "react"
import {
  BackSide,
  type Group,
  type Mesh,
  QuadraticBezierCurve3,
  Quaternion,
  Vector3,
} from "three"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { sf } from "@/smartforge/api"
import { POLL } from "@/smartforge/constants"
import { HEX } from "@/smartforge/components"
import type { Page, PurchaseOrder } from "@/smartforge/types"

const R = 2

function latLng(lat: number, lng: number, r = R): [number, number, number] {
  const phi = ((90 - lat) * Math.PI) / 180
  const theta = ((lng + 180) * Math.PI) / 180
  return [
    -r * Math.sin(phi) * Math.cos(theta),
    r * Math.cos(phi),
    r * Math.sin(phi) * Math.sin(theta),
  ]
}

// Reno, NV — the SmartForge factory — and a global set of active lanes.
const RENO = { lat: 39.53, lng: -119.81 }
const ROUTES = [
  { id: 0, city: "Los Angeles, US", lat: 34.05, lng: -118.24, color: HEX.info },
  { id: 1, city: "Toronto, CA", lat: 43.65, lng: -79.38, color: "#34d399" },
  { id: 2, city: "Mexico City, MX", lat: 19.43, lng: -99.13, color: "#f97316" },
  { id: 3, city: "London, UK", lat: 51.51, lng: -0.12, color: HEX.success },
  { id: 4, city: "Berlin, DE", lat: 52.52, lng: 13.405, color: "#818cf8" },
  { id: 5, city: "São Paulo, BR", lat: -23.55, lng: -46.63, color: "#22d3ee" },
  { id: 6, city: "Dubai, AE", lat: 25.2, lng: 55.27, color: "#fbbf24" },
  { id: 7, city: "Mumbai, IN", lat: 19.08, lng: 72.88, color: "#f43f5e" },
  { id: 8, city: "Tokyo, JP", lat: 35.68, lng: 139.69, color: "#f472b6" },
  { id: 9, city: "Sydney, AU", lat: -33.87, lng: 151.21, color: "#c084fc" },
] as const

const RENO_V = new Vector3(...latLng(RENO.lat, RENO.lng))
// Pulled out so the whole network + international arcs read clearly by default.
const CAM = RENO_V.clone().normalize().multiplyScalar(9.6).toArray() as [
  number,
  number,
  number,
]
const RENO_Q = new Quaternion().setFromUnitVectors(
  new Vector3(0, 1, 0),
  RENO_V.clone().normalize(),
)

function Globe() {
  return (
    <group>
      <mesh>
        <sphereGeometry args={[R * 0.99, 64, 64]} />
        <meshStandardMaterial color="#0a1422" metalness={0.2} roughness={0.85} />
      </mesh>
      <mesh>
        <sphereGeometry args={[R, 36, 24]} />
        <meshBasicMaterial wireframe color="#16365a" transparent opacity={0.4} />
      </mesh>
      <mesh>
        <sphereGeometry args={[R * 1.08, 48, 48]} />
        <meshBasicMaterial color="#1e90ff" transparent opacity={0.08} side={BackSide} />
      </mesh>
    </group>
  )
}

function CityDot({ lat, lng, color }: { lat: number; lng: number; color: string }) {
  return (
    <mesh position={latLng(lat, lng, R * 1.005)}>
      <sphereGeometry args={[0.035, 16, 16]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={3} toneMapped={false} />
    </mesh>
  )
}

function FactoryBuilding({ onOpenFactory }: { onOpenFactory: () => void }) {
  const [hovered, setHovered] = useState(false)
  return (
    <group
      position={RENO_V.toArray() as [number, number, number]}
      quaternion={[RENO_Q.x, RENO_Q.y, RENO_Q.z, RENO_Q.w]}
      onClick={(e) => {
        e.stopPropagation()
        onOpenFactory()
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
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, 0]}>
        <ringGeometry args={[0.12, 0.16, 32]} />
        <meshBasicMaterial color={HEX.info} transparent opacity={0.9} toneMapped={false} />
      </mesh>
      <mesh position={[0, 0.14, 0]} scale={hovered ? 1.15 : 1}>
        <boxGeometry args={[0.13, 0.28, 0.13]} />
        <meshStandardMaterial color="#e6eef8" emissive={HEX.info} emissiveIntensity={hovered ? 1.4 : 0.7} metalness={0.4} roughness={0.3} />
      </mesh>
      <mesh position={[0, 0.32, 0]}>
        <boxGeometry args={[0.08, 0.12, 0.08]} />
        <meshStandardMaterial color="#cdd9e8" emissive={HEX.info} emissiveIntensity={0.6} />
      </mesh>
      <Html position={[0, 0.5, 0]} center distanceFactor={6} zIndexRange={[20, 0]}>
        <div className="pointer-events-none flex select-none items-center gap-0.5 whitespace-nowrap rounded-full border border-sky-400/40 bg-black/70 px-1.5 py-px text-[7px] font-semibold text-sky-200 backdrop-blur">
          <Building2 size={7} /> Future Form HQ · Reno, NV
        </div>
      </Html>
    </group>
  )
}

function RouteLayer({
  route,
  selected,
  dimmed,
  onSelect,
}: {
  route: (typeof ROUTES)[number]
  selected: boolean
  dimmed: boolean
  onSelect: () => void
}) {
  const carrier = useRef<Group>(null)
  const pulse = useRef<Mesh>(null)
  const t = useRef(Math.random())
  const dir = useRef(1)
  const flow = useRef(Math.random())

  const curve = useMemo(() => {
    const start = new Vector3(...latLng(RENO.lat, RENO.lng))
    const end = new Vector3(...latLng(route.lat, route.lng))
    // Longer (international) lanes bow further off the surface.
    const angle = start.angleTo(end)
    const lift = R * (1.18 + angle * 0.32)
    const mid = start.clone().add(end).multiplyScalar(0.5).normalize().multiplyScalar(lift)
    return new QuadraticBezierCurve3(start, mid, end)
  }, [route])

  const points = useMemo(() => curve.getPoints(80), [curve])

  useFrame((_, dt) => {
    // Carrier eases to/from the factory; a brighter pulse streams outbound.
    t.current += dt * 0.05 * dir.current
    if (t.current >= 1) {
      t.current = 1
      dir.current = -1
    } else if (t.current <= 0) {
      t.current = 0
      dir.current = 1
    }
    if (carrier.current) {
      const p = curve.getPointAt(t.current)
      const tan = curve.getTangentAt(t.current)
      carrier.current.position.copy(p)
      carrier.current.lookAt(p.clone().add(tan))
    }
    flow.current = (flow.current + dt * 0.18) % 1
    if (pulse.current) pulse.current.position.copy(curve.getPointAt(flow.current))
  })

  const opacity = selected ? 1 : dimmed ? 0.12 : 0.5
  return (
    <group>
      <Line
        points={points}
        color={route.color}
        lineWidth={selected ? 3.5 : 1.5}
        transparent
        opacity={opacity}
      />
      <CityDot lat={route.lat} lng={route.lng} color={route.color} />

      {/* streaming flow pulse */}
      <mesh ref={pulse}>
        <sphereGeometry args={[selected ? 0.05 : 0.035, 12, 12]} />
        <meshBasicMaterial color={route.color} transparent opacity={dimmed ? 0.2 : 1} toneMapped={false} />
      </mesh>

      <group
        ref={carrier}
        scale={selected ? 1.6 : 1}
        onClick={(e) => {
          e.stopPropagation()
          onSelect()
        }}
        onPointerOver={(e) => {
          e.stopPropagation()
          document.body.style.cursor = "pointer"
        }}
        onPointerOut={() => {
          document.body.style.cursor = "auto"
        }}
      >
        <mesh position={[0, 0, 0.05]}>
          <boxGeometry args={[0.07, 0.06, 0.12]} />
          <meshStandardMaterial color="#eef2f8" emissive={route.color} emissiveIntensity={selected ? 1.6 : 0.6} metalness={0.4} roughness={0.4} />
        </mesh>
        <mesh position={[0, 0, -0.07]}>
          <boxGeometry args={[0.06, 0.05, 0.05]} />
          <meshStandardMaterial color={route.color} emissive={route.color} emissiveIntensity={2} toneMapped={false} />
        </mesh>
      </group>
    </group>
  )
}

// The globe + lanes live in a group that smoothly rotates so the selected lane
// faces the camera (the globe "turns" to center the clicked route).
function GlobeContent({
  selected,
  onSelect,
  onOpenFactory,
}: {
  selected: number | null
  onSelect: (id: number | null) => void
  onOpenFactory: () => void
}) {
  const group = useRef<Group>(null)
  const { camera } = useThree()
  const targetMid = useMemo(() => {
    if (selected == null) return null
    const r = ROUTES[selected]
    const start = new Vector3(...latLng(RENO.lat, RENO.lng))
    const end = new Vector3(...latLng(r.lat, r.lng))
    // Midpoint direction of the lane — point it at the camera to center the arc.
    return start.add(end).normalize()
  }, [selected])
  const q = useRef(new Quaternion())

  useFrame(() => {
    const g = group.current
    if (!g || !targetMid) return
    const camDir = camera.position.clone().normalize()
    q.current.setFromUnitVectors(targetMid, camDir)
    g.quaternion.slerp(q.current, 0.08)
  })

  return (
    <group ref={group}>
      <Globe />
      <CityDot lat={RENO.lat} lng={RENO.lng} color="#ffffff" />
      <FactoryBuilding onOpenFactory={onOpenFactory} />
      {ROUTES.map((r) => (
        <RouteLayer
          key={r.id}
          route={r}
          selected={selected === r.id}
          dimmed={selected !== null && selected !== r.id}
          onSelect={() => onSelect(r.id)}
        />
      ))}
    </group>
  )
}

function Scene({
  selected,
  onSelect,
  onOpenFactory,
}: {
  selected: number | null
  onSelect: (id: number | null) => void
  onOpenFactory: () => void
}) {
  return (
    <>
      <color attach="background" args={["#03060d"]} />
      <ambientLight intensity={0.5} />
      <directionalLight position={[5, 3, 5]} intensity={1.4} />
      <pointLight position={[-4, 2, 3]} intensity={20} color="#1e90ff" distance={20} />
      <Stars radius={70} depth={35} count={2600} factor={3} saturation={0} fade speed={0.4} />

      <GlobeContent selected={selected} onSelect={onSelect} onOpenFactory={onOpenFactory} />

      <OrbitControls
        makeDefault
        enablePan={false}
        enableDamping
        minDistance={3.4}
        maxDistance={15}
      />
      <EffectComposer enableNormalPass={false} multisampling={0}>
        <Bloom intensity={0.9} luminanceThreshold={0.6} luminanceSmoothing={0.3} mipmapBlur />
        <Vignette eskil={false} offset={0.3} darkness={0.7} />
      </EffectComposer>
    </>
  )
}

export function GlobalOperations({ className }: { className?: string }) {
  const [selected, setSelected] = useState<number | null>(null)
  const navigate = useNavigate()

  const { data } = useQuery({
    queryKey: ["purchase-orders"],
    queryFn: () => sf.get<Page<PurchaseOrder>>("/purchase-orders"),
    refetchInterval: POLL.slow,
  })
  const allPOs = data?.data ?? []
  const routePOs = (id: number) => allPOs.filter((_, i) => i % ROUTES.length === id)

  const route = selected != null ? ROUTES[selected] : null
  const pos = selected != null ? routePOs(selected) : []

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-xl border bg-black",
        className ?? "h-[420px]",
      )}
    >
      <Canvas
        dpr={[1, 1.75]}
        gl={{ antialias: false, powerPreference: "high-performance" }}
        camera={{ position: CAM, fov: 34 }}
        onPointerMissed={() => setSelected(null)}
      >
        <Scene
          selected={selected}
          onSelect={setSelected}
          onOpenFactory={() => navigate({ to: "/factory-map" })}
        />
      </Canvas>

      {/* reset the globe to its centered (no-lane) view */}
      <button
        type="button"
        onClick={() => setSelected(null)}
        aria-label="Reset globe view"
        title="Reset globe view"
        className="absolute right-4 top-4 z-10 flex items-center gap-1.5 rounded-md bg-info px-2.5 py-1.5 text-xs font-medium text-white shadow-lg backdrop-blur transition-all hover:brightness-110"
      >
        <RotateCcw size={14} /> Reset Globe
      </button>

      <div className="pointer-events-none absolute bottom-4 left-4 top-4 flex max-w-[230px] flex-col gap-2">
        <div>
          <h2 className="text-sm font-semibold text-white">Global Operations</h2>
          <p className="text-[11px] text-white/60">
            {ROUTES.length} active lanes · {allPOs.length} purchase orders
          </p>
        </div>
        <div className="pointer-events-auto flex min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-black/50 text-[11px] text-white backdrop-blur">
          <div className="border-b border-border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-white/50">
            Active lanes
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-2 py-1.5">
            {ROUTES.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => setSelected(r.id)}
                className={cn(
                  "flex w-full items-center gap-2 rounded px-1.5 py-1 text-left transition-colors hover:bg-white/10",
                  selected === r.id ? "bg-white/10 text-sky-300" : "text-white/85",
                )}
              >
                <i className="size-2 shrink-0 rounded-full" style={{ background: r.color }} />
                <span className="truncate">Reno → {r.city}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      {route && (
        <div className="absolute bottom-4 right-4 top-4 flex w-[min(320px,calc(100%-2rem))] flex-col overflow-hidden rounded-xl border border-border bg-background/95 shadow-2xl backdrop-blur-md">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <div className="flex items-center gap-2">
              <span
                className="flex size-7 items-center justify-center rounded-full"
                style={{ background: `${route.color}26`, color: route.color }}
              >
                <Truck size={15} />
              </span>
              <div>
                <h3 className="text-sm font-semibold leading-tight">Reno → {route.city}</h3>
                <p className="text-[11px] text-muted-foreground">
                  {pos.length} active purchase orders on this lane
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setSelected(null)}
              aria-label="Close lane"
              className="rounded-md p-1 text-muted-foreground hover:bg-accent"
            >
              <X size={16} />
            </button>
          </div>
          <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
            {pos.length === 0 && (
              <p className="text-sm text-muted-foreground">
                No active purchase orders on this lane.
              </p>
            )}
            {pos.map((po) => (
              <POReceipt key={po.id} po={po} accent={route.color} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function POReceipt({ po, accent }: { po: PurchaseOrder; accent: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded-lg border bg-card">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between p-2.5 text-left"
      >
        <span className="flex items-center gap-1.5 text-sm font-semibold">
          {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          {po.po_number}
        </span>
        <span className="text-sm tabular-nums">${po.amount.toLocaleString()}</span>
      </button>
      {open && (
        <div className="space-y-1 border-t px-3 py-2 text-[11px]">
          {/* high-level receipt preview */}
          <ReceiptRow label="Status" value={<span className="capitalize">{po.status}</span>} />
          <ReceiptRow
            label="Shop floor"
            value={po.shop_floor_ready ? "Ready" : "In transit"}
          />
          <ReceiptRow label="Linked job" value={po.job_id ? po.job_id.slice(0, 8) : "—"} />
          <ReceiptRow
            label="Customer order"
            value={po.customer_order_id ? po.customer_order_id.slice(0, 8) : "—"}
          />
          <div className="mt-1 flex justify-between border-t pt-1 font-semibold">
            <span>Total</span>
            <span className="tabular-nums">${po.amount.toLocaleString()}</span>
          </div>
          <Button
            asChild
            size="sm"
            className="mt-2 h-7 w-full text-[11px]"
            style={{ background: accent }}
          >
            <Link to="/order-tracker" search={{ po: po.id }}>
              View Purchase Order
            </Link>
          </Button>
        </div>
      )}
    </div>
  )
}

function ReceiptRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span>{value}</span>
    </div>
  )
}
