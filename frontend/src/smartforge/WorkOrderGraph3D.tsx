// 3D genealogy galaxy for the Work Orders Explorer — the same R3F stack
// and theme conventions as the Factory Simulation, restyled as a space
// scene using the techniques from the supernova reference visualization
// (refs/components/supernova-intake-console.tsx): a twinkling point-sprite
// starfield backdrop and procedurally surface-textured bodies — the
// gradient lives ON each sphere (granulated star, banded planet, cratered
// moon), never as a halo around it. Node size is proportional to order
// value (cost when present, else quantity), so the heaviest work reads as
// the biggest body at a glance.
//
// Performance: the whole field is five draw calls — one instanced mesh per
// body class, one Points for the backdrop starfield, one lineSegments for
// the edges — so the server's 1000-row cap renders comfortably. Clicking a
// node selects the matching table record below.

import { Instance, Instances, OrbitControls } from "@react-three/drei"
import { Canvas, useFrame } from "@react-three/fiber"
import { Bloom, EffectComposer, Vignette } from "@react-three/postprocessing"
import { Moon, Pause, Play, RotateCcw, Sun, SunMoon } from "lucide-react"
import { memo, useEffect, useMemo, useRef, useState } from "react"
import type { Mesh, Points, ShaderMaterial } from "three"
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  CanvasTexture,
  Color,
  NormalBlending,
  SRGBColorSpace,
} from "three"

import { useTheme } from "@/components/theme-provider"
import { Button } from "@/components/ui/button"
import { descendantStats, formatDescendants } from "@/smartforge/explorer"
import {
  buildWorkOrderGraph,
  type GraphNode,
  magnitudeOf,
  type WorkOrderGraphModel,
} from "@/smartforge/graphLayout"
import type { ApiWorkOrderRow } from "@/smartforge/platformTypes"

type OrbitControlsImpl = React.ComponentRef<typeof OrbitControls>

/* ------------------------------------------------------- scene theming */

// Mirrors the Factory Simulation SCENE_THEME: the canvas can't read CSS
// variables, so each resolved theme maps to literal stage colors. Dark is
// deep space; light is its star-chart counterpart (same geometry, ink on
// paper instead of light on black).
interface ScenePalette {
  bg: string
  edge: string
  halo: string
  /** Backdrop star tints (the reference's stellar-class palette). */
  starTints: string[]
  dark: boolean
}
const SCENE_THEME: Record<"light" | "dark" | "future", ScenePalette> = {
  // halo = the selection marker (green: "you are here", distinct from every
  // body-class hue), stepped per surface.
  light: {
    bg: "#eef1f6",
    edge: "#5b6b85",
    halo: "#16a34a",
    starTints: ["#8c9cb8", "#7c93b8", "#a3aec4", "#95a1b6"],
    dark: false,
  },
  dark: {
    bg: "#05070d",
    edge: "#7d8db0",
    halo: "#4ade80",
    starTints: ["#88aaff", "#aaffff", "#ffddaa", "#ffeecc", "#ffffff"],
    dark: true,
  },
  future: {
    bg: "#050510",
    edge: "#8d8dc0",
    halo: "#4ade80",
    starTints: ["#8888ff", "#aaccff", "#ffccee", "#eeeeff", "#ffffff"],
    dark: true,
  },
}

const STATUS_KEY = (r: ApiWorkOrderRow): string => r.status ?? "(none)"

/** Deterministic 0..1 from an index (stable frames, no Math.random). */
const rnd = (i: number, salt: number): number => {
  const x = Math.sin(i * 127.1 + salt * 311.7) * 43758.5453
  return x - Math.floor(x)
}

/* --------------------------------------------- stellar-body appearance */

// Hierarchy classes styled as celestial bodies with ONE consistent color
// family each — the gradient is baked directly into the class's surface
// texture (below), so every body of a class reads identically: roots as
// yellow → burnt-orange stars, children as teal planets, grandchildren as
// slate-gray moons. The gradient lives on the sphere itself (hot core
// band, atmosphere bands, cratered regolith), never as a halo around it.
type BodyClass = "root" | "child" | "grand"

const BODY_CLASSES: Record<
  BodyClass,
  { label: string; gradient: [string, string] }
> = {
  root: { label: "root orders", gradient: ["#fbbf24", "#c2410c"] },
  child: { label: "children", gradient: ["#5eead4", "#0f766e"] },
  grand: { label: "grandchildren", gradient: ["#cbd5e1", "#64748b"] },
}

const bodyClassOf = (depth: number): BodyClass =>
  depth <= 0 ? "root" : depth === 1 ? "child" : "grand"

/* ------------------------------------------------------ backdrop modes */

// The scene backdrop is user-switchable independent of the app theme:
// auto follows the theme with the starfield, void is a pure star-less
// dark stage, studio is a white-room stage for print-friendly reading.
type BackdropMode = "auto" | "void" | "studio"

const BACKDROP_ORDER: BackdropMode[] = ["auto", "void", "studio"]

const BACKDROP_META: Record<
  BackdropMode,
  { label: string; icon: typeof SunMoon }
> = {
  auto: { label: "Backdrop: theme + starfield", icon: SunMoon },
  void: { label: "Backdrop: dark void", icon: Moon },
  studio: { label: "Backdrop: white room", icon: Sun },
}

interface StagePalette extends ScenePalette {
  stars: boolean
}

function stageFor(mode: BackdropMode, themed: ScenePalette): StagePalette {
  if (mode === "void")
    return {
      ...SCENE_THEME.dark,
      bg: "#030308",
      halo: "#4ade80",
      dark: true,
      stars: false,
    }
  if (mode === "studio")
    return {
      ...SCENE_THEME.light,
      bg: "#f7f8fa",
      dark: false,
      stars: false,
    }
  return { ...themed, stars: true }
}

const classGradientCss = (cls: BodyClass): string =>
  `linear-gradient(90deg, ${BODY_CLASSES[cls].gradient.join(", ")})`

/**
 * Per-class equirect surface textures with the class color family baked
 * straight into the map (yellow→burnt-orange star, teal planet, slate
 * moon) — one consistent color type per hierarchy class, one instanced
 * draw call per class (instance tint stays white). Deterministic (rnd,
 * never Math.random): the same map every mount.
 */
function makeBodyTexture(kind: BodyClass): CanvasTexture | null {
  const w = 512
  const h = 256
  const canvas = document.createElement("canvas")
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext("2d")
  if (!ctx) return null

  if (kind === "root") {
    // Star: self-luminous — a bright yellow core band at the equator
    // cooling to burnt orange toward the poles, plasma convection cells,
    // and granulation streaks.
    const g = ctx.createLinearGradient(0, 0, 0, h)
    g.addColorStop(0, "#b45309")
    g.addColorStop(0.32, "#fbbf24")
    g.addColorStop(0.5, "#fde68a")
    g.addColorStop(0.68, "#f59e0b")
    g.addColorStop(1, "#9a3412")
    ctx.fillStyle = g
    ctx.fillRect(0, 0, w, h)
    // convection cells — soft radial blotches, brighter near the equator
    for (let i = 0; i < 60; i++) {
      const x = rnd(i, 41) * w
      const y = rnd(i, 42) * h
      const r = 8 + rnd(i, 43) * 26
      const nearCore = 1 - Math.abs(y / h - 0.5) * 2
      const cell = ctx.createRadialGradient(x, y, 0, x, y, r)
      cell.addColorStop(0, `rgba(255,255,255,${0.1 + nearCore * 0.2})`)
      cell.addColorStop(1, "rgba(255,255,255,0)")
      ctx.fillStyle = cell
      ctx.beginPath()
      ctx.arc(x, y, r, 0, Math.PI * 2)
      ctx.fill()
    }
    // granulation streaks (darker filaments toward the poles)
    for (let i = 0; i < 140; i++) {
      const bright = rnd(i, 12) > 0.55
      ctx.fillStyle = bright
        ? `rgba(255,255,255,${0.08 + rnd(i, 16) * 0.14})`
        : `rgba(100,70,35,${0.05 + rnd(i, 17) * 0.11})`
      ctx.fillRect(
        rnd(i, 14) * w,
        rnd(i, 11) * h,
        16 + rnd(i, 13) * 90,
        1 + rnd(i, 15) * 3,
      )
    }
  } else if (kind === "child") {
    // Planet: teal banded atmosphere with turbulent streaks, a bright
    // polar cap and one great storm — light aqua day-side into deep teal.
    const g = ctx.createLinearGradient(0, 0, 0, h)
    g.addColorStop(0, "#ccfbf1")
    g.addColorStop(0.1, "#99f6e4")
    g.addColorStop(0.55, "#2dd4bf")
    g.addColorStop(0.92, "#115e59")
    g.addColorStop(1, "#0f766e")
    ctx.fillStyle = g
    ctx.fillRect(0, 0, w, h)
    let y = 0
    let band = 0
    while (y < h) {
      const bandHeight = 10 + rnd(band, 21) * 28
      const tone = rnd(band, 22)
      ctx.fillStyle =
        tone > 0.5
          ? `rgba(255,255,255,${0.06 + tone * 0.13})`
          : `rgba(16,22,52,${0.06 + (1 - tone) * 0.13})`
      ctx.fillRect(0, y, w, bandHeight)
      // turbulence at the band boundary
      for (let i = 0; i < 12; i++) {
        const sx = rnd(band * 31 + i, 23) * w
        ctx.fillStyle = `rgba(255,255,255,${0.04 + rnd(band * 31 + i, 24) * 0.08})`
        ctx.fillRect(
          sx,
          y + bandHeight - 2,
          24 + rnd(band * 31 + i, 25) * 70,
          2,
        )
      }
      y += bandHeight
      band++
    }
    // the great storm — an elliptical swirl below the equator
    const storm = ctx.createRadialGradient(
      w * 0.68,
      h * 0.62,
      2,
      w * 0.68,
      h * 0.62,
      26,
    )
    storm.addColorStop(0, "rgba(255,255,255,0.4)")
    storm.addColorStop(0.6, "rgba(30,30,60,0.18)")
    storm.addColorStop(1, "rgba(30,30,60,0)")
    ctx.fillStyle = storm
    ctx.save()
    ctx.translate(w * 0.68, h * 0.62)
    ctx.scale(1.8, 1)
    ctx.beginPath()
    ctx.arc(0, 0, 26, 0, Math.PI * 2)
    ctx.restore()
    ctx.fill()
  } else {
    // Moon/asteroid: matte slate-gray regolith — dark maria patches,
    // rim-lit craters of varied size, and fine surface noise.
    const g = ctx.createLinearGradient(0, 0, 0, h)
    g.addColorStop(0, "#e2e8f0")
    g.addColorStop(0.6, "#94a3b8")
    g.addColorStop(1, "#475569")
    ctx.fillStyle = g
    ctx.fillRect(0, 0, w, h)
    // maria — large soft dark patches
    for (let i = 0; i < 6; i++) {
      const x = rnd(i, 36) * w
      const y = rnd(i, 37) * h
      const r = 30 + rnd(i, 38) * 60
      const mare = ctx.createRadialGradient(x, y, 0, x, y, r)
      mare.addColorStop(0, "rgba(40,40,56,0.16)")
      mare.addColorStop(1, "rgba(40,40,56,0)")
      ctx.fillStyle = mare
      ctx.beginPath()
      ctx.arc(x, y, r, 0, Math.PI * 2)
      ctx.fill()
    }
    for (let i = 0; i < 110; i++) {
      const r = 1.5 + rnd(i, 31) ** 2 * 9
      const x = rnd(i, 32) * w
      const y = rnd(i, 33) * h
      ctx.beginPath()
      ctx.arc(x, y, r, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(26,26,38,${0.1 + rnd(i, 34) * 0.18})`
      ctx.fill()
      ctx.beginPath()
      ctx.arc(x, y - r * 0.35, r * 0.7, 0, Math.PI * 2)
      ctx.fillStyle = "rgba(255,255,255,0.09)"
      ctx.fill()
    }
    // fine noise speckle
    for (let i = 0; i < 500; i++) {
      ctx.fillStyle =
        rnd(i, 35) > 0.5 ? "rgba(255,255,255,0.05)" : "rgba(20,20,30,0.05)"
      ctx.fillRect(rnd(i, 36) * w, rnd(i, 37) * h, 1.5, 1.5)
    }
  }
  const texture = new CanvasTexture(canvas)
  texture.colorSpace = SRGBColorSpace
  return texture
}

function useBodyTextures(): Record<BodyClass, CanvasTexture | null> {
  const textures = useMemo(
    () => ({
      root: makeBodyTexture("root"),
      child: makeBodyTexture("child"),
      grand: makeBodyTexture("grand"),
    }),
    [],
  )
  useEffect(
    () => () => {
      for (const texture of Object.values(textures)) texture?.dispose()
    },
    [textures],
  )
  return textures
}

/* -------------------------------------------------- point-sprite layer */

// Shared round-sprite shader (adapted from the supernova starfield):
// depth-attenuated point size, soft radial falloff, per-point twinkle.
const SPRITE_VERTEX = `
  uniform float uTime;
  uniform float uPixelRatio;
  attribute float size;
  attribute float twinkle;
  varying vec3 vColor;
  varying float vTwinkle;
  void main() {
    vColor = color;
    vTwinkle = sin(uTime * 1.8 + twinkle) * 0.5 + 0.5;
    vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = size * uPixelRatio * (280.0 / -mvPosition.z);
    gl_Position = projectionMatrix * mvPosition;
  }`
const SPRITE_FRAGMENT = `
  uniform float uAlpha;
  varying vec3 vColor;
  varying float vTwinkle;
  void main() {
    float dist = distance(gl_PointCoord, vec2(0.5));
    if (dist > 0.5) discard;
    float alpha = 1.0 - smoothstep(0.0, 0.5, dist);
    alpha *= (0.35 + vTwinkle * 0.65) * uAlpha;
    gl_FragColor = vec4(vColor, alpha);
  }`

function SpriteCloud({
  positions,
  colors,
  sizes,
  twinkles,
  alpha,
  additive,
}: {
  positions: Float32Array
  colors: Float32Array
  sizes: Float32Array
  twinkles: Float32Array
  alpha: number
  additive: boolean
}) {
  const material = useRef<ShaderMaterial>(null)
  const points = useRef<Points>(null)
  const geometry = useMemo(() => {
    const g = new BufferGeometry()
    g.setAttribute("position", new BufferAttribute(positions, 3))
    g.setAttribute("color", new BufferAttribute(colors, 3))
    g.setAttribute("size", new BufferAttribute(sizes, 1))
    g.setAttribute("twinkle", new BufferAttribute(twinkles, 1))
    return g
  }, [positions, colors, sizes, twinkles])
  useEffect(() => () => geometry.dispose(), [geometry])
  useFrame(({ clock, gl }) => {
    if (!material.current) return
    material.current.uniforms.uTime.value = clock.elapsedTime
    material.current.uniforms.uPixelRatio.value = gl.getPixelRatio()
  })
  return (
    <points ref={points} geometry={geometry} raycast={() => null}>
      <shaderMaterial
        ref={material}
        vertexShader={SPRITE_VERTEX}
        fragmentShader={SPRITE_FRAGMENT}
        uniforms={{
          uTime: { value: 0 },
          uPixelRatio: { value: 1 },
          uAlpha: { value: alpha },
        }}
        vertexColors
        transparent
        depthWrite={false}
        blending={additive ? AdditiveBlending : NormalBlending}
      />
    </points>
  )
}

/** Distant twinkling backdrop — a scaled-down version of the reference's
 * 30k-particle field, sized for a pane. */
function Starfield({ palette }: { palette: ScenePalette }) {
  const data = useMemo(() => {
    const count = 2400
    const positions = new Float32Array(count * 3)
    const colors = new Float32Array(count * 3)
    const sizes = new Float32Array(count)
    const twinkles = new Float32Array(count)
    const tints = palette.starTints.map((t) => new Color(t))
    for (let i = 0; i < count; i++) {
      // Fibonacci-sphere direction, cube-root radial falloff (reference
      // technique) — an even shell that thickens toward the horizon.
      const phi = Math.acos(-1 + (2 * i + 1) / count)
      const theta = Math.sqrt(count * Math.PI) * phi
      const radius = 60 + Math.cbrt(rnd(i, 1)) * 120
      positions[i * 3] = radius * Math.sin(phi) * Math.cos(theta)
      positions[i * 3 + 1] = radius * Math.cos(phi)
      positions[i * 3 + 2] = radius * Math.sin(phi) * Math.sin(theta)
      const tint = tints[Math.floor(rnd(i, 2) * tints.length) % tints.length]
      const brightness = palette.dark ? 0.3 + rnd(i, 3) * 0.7 : 1
      colors[i * 3] = tint.r * brightness
      colors[i * 3 + 1] = tint.g * brightness
      colors[i * 3 + 2] = tint.b * brightness
      sizes[i] = 0.5 + rnd(i, 4) * 1.8
      twinkles[i] = rnd(i, 5) * Math.PI * 2
    }
    return { positions, colors, sizes, twinkles }
  }, [palette])
  return (
    <SpriteCloud
      {...data}
      alpha={palette.dark ? 0.9 : 0.5}
      additive={palette.dark}
    />
  )
}

/* ------------------------------------------------------------ helpers */

function EdgeLines({
  graph,
  color,
  opacity,
  additive,
}: {
  graph: WorkOrderGraphModel
  color: string
  opacity: number
  additive: boolean
}) {
  const geometry = useMemo(() => {
    const positions = new Float32Array(graph.edges.length * 6)
    graph.edges.forEach((edge, i) => {
      positions.set(graph.nodes[edge.from].position, i * 6)
      positions.set(graph.nodes[edge.to].position, i * 6 + 3)
    })
    const g = new BufferGeometry()
    g.setAttribute("position", new BufferAttribute(positions, 3))
    return g
  }, [graph])
  useEffect(() => () => geometry.dispose(), [geometry])
  return (
    <lineSegments geometry={geometry}>
      <lineBasicMaterial
        color={color}
        transparent
        opacity={opacity}
        blending={additive ? AdditiveBlending : NormalBlending}
        depthWrite={false}
      />
    </lineSegments>
  )
}

/** "$12,340" (or plain qty) floating above each body — the same magnitude
 * that drives the sphere's scale, so the label doubles as the size legend. */
const nodeValueLabel = (
  node: GraphNode,
  metric: WorkOrderGraphModel["sizeMetric"],
): string | null => {
  const value = magnitudeOf(node.row, metric)
  if (value <= 0) return null
  return metric === "cost"
    ? `$${Math.round(value).toLocaleString()}`
    : `${Math.round(value).toLocaleString()} qty`
}

/** Text → CanvasTexture for a sprite label. Self-contained on purpose:
 * troika/drei <Text> spins up a blob web worker and fetches its font over
 * the network, both of which the app's CSP rightly blocks — a 2D-canvas
 * texture needs neither. Duplicate labels share one texture. */
function makeLabelTexture(
  text: string,
  ink: string,
  outline: string,
): { texture: CanvasTexture; aspect: number } | null {
  const font = "600 44px 'Segoe UI', system-ui, sans-serif"
  const canvas = document.createElement("canvas")
  const measure = canvas.getContext("2d")
  if (!measure) return null
  measure.font = font
  const w = Math.ceil(measure.measureText(text).width) + 28
  const h = 64
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext("2d")
  if (!ctx) return null
  ctx.font = font
  ctx.textAlign = "center"
  ctx.textBaseline = "middle"
  ctx.lineJoin = "round"
  ctx.lineWidth = 9
  ctx.strokeStyle = outline
  ctx.strokeText(text, w / 2, h / 2)
  ctx.fillStyle = ink
  ctx.fillText(text, w / 2, h / 2)
  const texture = new CanvasTexture(canvas)
  texture.colorSpace = SRGBColorSpace
  return { texture, aspect: w / h }
}

/** Value tags above every sphere — three.js sprites (camera-facing by
 * construction), never intercepting pointer picks. */
function ValueLabels({
  graph,
  ink,
  outline,
}: {
  graph: WorkOrderGraphModel
  ink: string
  outline: string
}) {
  const labels = useMemo(() => {
    if (!graph.sizeMetric) return []
    const textures = new Map<
      string,
      { texture: CanvasTexture; aspect: number }
    >()
    const out: {
      uid: string
      position: [number, number, number]
      scale: [number, number, number]
      texture: CanvasTexture
    }[] = []
    for (const node of graph.nodes) {
      const label = nodeValueLabel(node, graph.sizeMetric)
      if (!label) continue
      let entry = textures.get(label)
      if (entry === undefined) {
        const made = makeLabelTexture(label, ink, outline)
        if (!made) continue
        textures.set(label, made)
        entry = made
      }
      const height = Math.max(0.5, node.size * 0.55)
      out.push({
        uid: node.uid,
        position: [
          node.position[0],
          node.position[1] + node.size + 0.3 + height / 2,
          node.position[2],
        ],
        scale: [height * entry.aspect, height, 1],
        texture: entry.texture,
      })
    }
    return out
  }, [graph, ink, outline])
  useEffect(
    () => () => {
      for (const l of labels) l.texture.dispose()
    },
    [labels],
  )
  return (
    <>
      {labels.map((l) => (
        <sprite
          key={l.uid}
          position={l.position}
          scale={l.scale}
          raycast={() => null}
        >
          <spriteMaterial map={l.texture} transparent depthWrite={false} />
        </sprite>
      ))}
    </>
  )
}

/** Pulsing halo that marks the selected node. */
function SelectionHalo({ node, color }: { node: GraphNode; color: string }) {
  const ref = useRef<Mesh>(null)
  const base = node.size * 1.9
  useFrame(({ clock }) => {
    const s = base * (1 + 0.12 * Math.sin(clock.elapsedTime * 3.2))
    ref.current?.scale.setScalar(s)
  })
  return (
    <mesh ref={ref} position={node.position}>
      <sphereGeometry args={[1, 24, 24]} />
      <meshBasicMaterial color={color} wireframe transparent opacity={0.55} />
    </mesh>
  )
}

/** Eases the camera out/in when the constellation extent changes. */
function CameraFit({
  radius,
  controls,
}: {
  radius: number
  controls: React.RefObject<OrbitControlsImpl | null>
}) {
  useEffect(() => {
    const c = controls.current
    if (!c) return
    const distance = Math.max(12, radius * 1.5)
    c.object.position.set(distance * 0.8, distance * 0.45, distance * 0.8)
    c.target.set(0, 0, 0)
    c.update()
  }, [radius, controls])
  return null
}

/* ---------------------------------------------------------- component */

export const WorkOrderGraph3D = memo(function WorkOrderGraph3D({
  rows,
  selectedUid,
  onSelect,
}: {
  rows: ApiWorkOrderRow[]
  selectedUid: string | null
  onSelect: (uid: string | null) => void
}) {
  const { theme, resolvedTheme } = useTheme()
  const sceneKey = theme === "future" ? "future" : resolvedTheme
  const palette = SCENE_THEME[sceneKey]
  const textures = useBodyTextures()

  const graph = useMemo(() => buildWorkOrderGraph(rows), [rows])
  const genealogy = useMemo(() => descendantStats(rows), [rows])
  const legend = useMemo(() => {
    const counts = new Map<BodyClass, number>()
    for (const n of graph.nodes) {
      const cls = bodyClassOf(n.depth)
      counts.set(cls, (counts.get(cls) ?? 0) + 1)
    }
    return (Object.keys(BODY_CLASSES) as BodyClass[])
      .filter((cls) => (counts.get(cls) ?? 0) > 0)
      .map((cls) => [cls, counts.get(cls) ?? 0] as const)
  }, [graph])
  const byClass = useMemo(
    () => ({
      root: graph.nodes.filter((n) => bodyClassOf(n.depth) === "root"),
      child: graph.nodes.filter((n) => bodyClassOf(n.depth) === "child"),
      grand: graph.nodes.filter((n) => bodyClassOf(n.depth) === "grand"),
    }),
    [graph],
  )

  const [hovered, setHovered] = useState<GraphNode | null>(null)
  // Static view on load; the toolbar button opts into the slow orbit.
  const [rotating, setRotating] = useState(false)
  const [backdrop, setBackdrop] = useState<BackdropMode>("auto")
  const stage = stageFor(backdrop, palette)
  const controls = useRef<OrbitControlsImpl>(null)
  const selected = selectedUid
    ? (graph.nodes.find((n) => n.uid === selectedUid) ?? null)
    : null
  const constellations = useMemo(
    () => new Set(graph.nodes.map((n) => n.rootUid)).size,
    [graph],
  )

  useEffect(() => {
    document.body.style.cursor = hovered ? "pointer" : ""
    return () => {
      document.body.style.cursor = ""
    }
  }, [hovered])

  if (rows.length === 0) return null

  return (
    <div className="relative h-[400px] overflow-hidden rounded-lg border">
      <Canvas
        dpr={[1, 1.5]}
        camera={{ position: [22, 12, 22], fov: 45 }}
        gl={{ antialias: true, powerPreference: "high-performance" }}
        onPointerMissed={() => onSelect(null)}
      >
        <color attach="background" args={[stage.bg]} />
        <fog attach="fog" args={[stage.bg, 60, 170]} />

        <ambientLight intensity={stage.dark ? 0.55 : 1.05} />
        <directionalLight
          position={[12, 18, 8]}
          intensity={stage.dark ? 1.5 : 1.7}
        />
        <directionalLight
          position={[-10, 6, -8]}
          intensity={0.5}
          color={stage.dark ? "#bcd3ff" : "#ffffff"}
        />

        {stage.stars && <Starfield palette={stage} />}

        {/* one instanced draw call PER BODY CLASS, each with its own
            procedural surface texture × per-instance hue: self-luminous
            granulated stars, banded lit planets, cratered matte moons.
            limit is the server's row cap and MUST be static: drei allocates
            the instance buffer once at mount, so a grown result set would
            otherwise silently drop its tail nodes. frustumCulled off —
            instanced culling uses the base unit-sphere bounds, which can
            wrongly cull far-flung constellation members mid-orbit. */}
        {(Object.keys(BODY_CLASSES) as BodyClass[]).map((cls) => (
          <Instances
            key={`${sceneKey}-${cls}`}
            limit={1024}
            frustumCulled={false}
          >
            <sphereGeometry args={[1, 24, 24]} />
            {cls === "root" ? (
              // Stars emit their own light — unlit material, no shadowing.
              <meshBasicMaterial map={textures.root ?? undefined} />
            ) : (
              <meshStandardMaterial
                map={textures[cls] ?? undefined}
                roughness={cls === "grand" ? 0.9 : 0.55}
                metalness={0.05}
              />
            )}
            {byClass[cls].map((node) => (
              <Instance
                key={node.uid}
                position={node.position}
                scale={node.size * (node.uid === selectedUid ? 1.35 : 1)}
                color="#ffffff"
                onPointerOver={(e) => {
                  e.stopPropagation()
                  setHovered(node)
                }}
                onPointerOut={() => setHovered(null)}
                onClick={(e) => {
                  e.stopPropagation()
                  onSelect(node.uid === selectedUid ? null : node.uid)
                }}
              />
            ))}
          </Instances>
        ))}

        <EdgeLines
          graph={graph}
          color={stage.edge}
          opacity={stage.dark ? 0.5 : 0.45}
          additive={stage.dark}
        />
        <ValueLabels
          graph={graph}
          ink={stage.dark ? "#e7edf9" : "#2b3446"}
          outline={stage.bg}
        />
        {selected && <SelectionHalo node={selected} color={stage.halo} />}

        <OrbitControls
          ref={controls}
          makeDefault
          enableDamping
          autoRotate={rotating}
          autoRotateSpeed={0.35}
          maxPolarAngle={Math.PI / 1.7}
          minDistance={6}
          maxDistance={140}
        />
        <CameraFit radius={graph.radius} controls={controls} />

        {/* post-processing: a soft bloom lifts the self-luminous star
            cores off the canvas; the vignette recedes on light stages. */}
        <EffectComposer multisampling={4}>
          <Bloom
            mipmapBlur
            intensity={stage.dark ? 0.55 : 0.18}
            luminanceThreshold={stage.dark ? 0.7 : 0.92}
            luminanceSmoothing={0.25}
          />
          <Vignette
            eskil={false}
            offset={0.22}
            darkness={stage.dark ? 0.5 : 0.12}
          />
        </EffectComposer>
      </Canvas>

      {/* legend — hierarchy classes with their gradient swatches; identity
          is always in the label, never color alone */}
      <div className="pointer-events-none absolute left-3 top-3 flex max-w-[70%] flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-background/70 px-2.5 py-1.5 text-xs backdrop-blur">
        {legend.map(([cls, count]) => (
          <span key={cls} className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-5 rounded-full"
              style={{ background: classGradientCss(cls) }}
            />
            <span className="text-foreground/90">
              {BODY_CLASSES[cls].label}
            </span>
            <span className="text-muted-foreground">{count}</span>
          </span>
        ))}
      </div>

      <div className="absolute right-3 top-3 flex items-center gap-2">
        <span className="rounded-md bg-background/70 px-2 py-1 text-xs text-muted-foreground backdrop-blur">
          {graph.nodes.length.toLocaleString()} orders ·{" "}
          {constellations.toLocaleString()} constellations
          {graph.sizeMetric &&
            ` · size ∝ ${graph.sizeMetric === "cost" ? "value" : "qty"}`}
        </span>
        <Button
          size="icon"
          variant="secondary"
          className="size-7 bg-background/70 backdrop-blur"
          aria-label="Reset view"
          onClick={() => {
            controls.current?.reset()
          }}
        >
          <RotateCcw className="size-3.5" />
        </Button>
        <Button
          size="icon"
          variant="secondary"
          className="size-7 bg-background/70 backdrop-blur"
          aria-label={BACKDROP_META[backdrop].label}
          title={BACKDROP_META[backdrop].label}
          onClick={() =>
            setBackdrop(
              (current) =>
                BACKDROP_ORDER[
                  (BACKDROP_ORDER.indexOf(current) + 1) % BACKDROP_ORDER.length
                ],
            )
          }
        >
          {(() => {
            const Icon = BACKDROP_META[backdrop].icon
            return <Icon className="size-3.5" />
          })()}
        </Button>
        <Button
          size="icon"
          variant="secondary"
          className="size-7 bg-background/70 backdrop-blur"
          aria-label={rotating ? "Pause rotation" : "Resume rotation"}
          title={rotating ? "Pause rotation" : "Resume rotation"}
          onClick={() => setRotating((r) => !r)}
        >
          {rotating ? (
            <Pause className="size-3.5" />
          ) : (
            <Play className="size-3.5" />
          )}
        </Button>
      </div>

      {/* hover card — identity, status and the click affordance. Pointer
          events stay ON so the text can be highlighted and copied. */}
      {(hovered ?? selected) && (
        <div className="absolute bottom-3 left-3 select-text cursor-text rounded-md bg-background/80 px-3 py-2 text-xs shadow backdrop-blur">
          {(() => {
            const n = hovered ?? selected
            if (!n) return null
            return (
              <>
                <div className="font-medium text-foreground">
                  {n.row.wo_number ?? n.uid.slice(0, 8)}
                  <span className="ml-2 font-normal text-muted-foreground">
                    {n.depth === 0
                      ? "root star"
                      : n.depth === 1
                        ? "child"
                        : "grandchild"}
                  </span>
                </div>
                {n.row.title && (
                  <div className="max-w-72 truncate text-muted-foreground">
                    {n.row.title}
                  </div>
                )}
                <div className="mt-0.5 text-muted-foreground">
                  {STATUS_KEY(n.row)}
                  {n.row.machine_code ? ` · ${n.row.machine_code}` : ""}
                  {" · "}
                  {Number(n.row.qty_completed ?? 0)}/
                  {Number(n.row.qty_ordered ?? 0)} qty
                  {graph.sizeMetric === "cost" &&
                    n.row.cost_total != null &&
                    ` · $${Math.round(n.row.cost_total).toLocaleString()}`}
                  {hovered && " — click to locate in table"}
                </div>
                {formatDescendants(genealogy.get(n.uid)) && (
                  <div className="text-muted-foreground">
                    downstream: {formatDescendants(genealogy.get(n.uid))}
                  </div>
                )}
              </>
            )
          })()}
        </div>
      )}
    </div>
  )
})
