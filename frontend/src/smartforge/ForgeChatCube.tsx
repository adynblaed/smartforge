import { Environment, Float, Lightformer, RoundedBox } from "@react-three/drei"
import { Canvas, useFrame } from "@react-three/fiber"
import { Bloom, EffectComposer } from "@react-three/postprocessing"
import { useEffect, useRef } from "react"
import { Color } from "three"
import type { Mesh, MeshStandardMaterial } from "three"

// "thinking" = actively streaming / running inference.
export type CubeState = "idle" | "thinking" | "answer"

const ACCENT = "#38bdf8" // idle cyan
const STREAM = "#22d3ee" // streaming/inference cyan (no purple)
const FLARE = "#e0f2fe" // answer flare

function Core({ state }: { state: CubeState }) {
  const core = useRef<Mesh>(null)
  const coreMat = useRef<MeshStandardMaterial>(null)
  // Transient impulses: `kick` fires on submit (enter), `pop` on a new answer.
  const kick = useRef(0)
  const pop = useRef(0)
  const tColor = useRef(new Color(ACCENT))
  const cur = useRef(new Color(ACCENT))

  useEffect(() => {
    if (state === "thinking") kick.current = 1
    if (state === "answer") pop.current = 1
  }, [state])

  useFrame((s, dt) => {
    const t = s.clock.elapsedTime
    const c = core.current
    if (!c) return
    const thinking = state === "thinking"

    kick.current = Math.max(0, kick.current - dt * 2.2)
    pop.current = Math.max(0, pop.current - dt * 1.6)

    // Gentle multi-axis spin, faster while streaming.
    const spin = thinking ? 2.6 : 0.55
    c.rotation.y += dt * spin
    c.rotation.x += dt * spin * 0.45

    // Streaming ripple + impulse kick on the core scale (seamless lerp).
    const ripple = thinking ? Math.sin(t * 9) * 0.07 : 0
    c.scale.setScalar(1 + ripple + kick.current * 0.25 + pop.current * 0.45)

    // Color: idle cyan → streaming (oscillating) → answer flare.
    const dest =
      pop.current > 0.05
        ? tColor.current.set(FLARE)
        : thinking
          ? tColor.current.set(STREAM).lerp(new Color(ACCENT), (Math.sin(t * 5) + 1) / 2)
          : tColor.current.set(ACCENT)
    cur.current.lerp(dest, Math.min(1, dt * 4))
    if (coreMat.current) {
      coreMat.current.color.copy(cur.current)
      coreMat.current.emissive.copy(cur.current)
      const target = thinking ? 3.4 : 1.7 + pop.current * 3 + kick.current * 1.5
      coreMat.current.emissiveIntensity +=
        (target - coreMat.current.emissiveIntensity) * Math.min(1, dt * 5)
    }
  })

  return (
    <RoundedBox
      ref={core}
      args={[1.5, 1.5, 1.5]}
      radius={0.16}
      smoothness={8}
      bevelSegments={6}
      creaseAngle={0.5}
    >
      <meshStandardMaterial
        ref={coreMat}
        color={ACCENT}
        emissive={ACCENT}
        emissiveIntensity={1.6}
        metalness={0.85}
        roughness={0.18}
        envMapIntensity={1.2}
        toneMapped={false}
      />
    </RoundedBox>
  )
}

/**
 * Compact 3D visualizer for the ForgeAI chat. Seamless idle float; on submit
 * (enter) it kicks and accelerates to signal active streaming/inference; a new
 * answer triggers a bright flare/pop. Cyan-only palette (no purple outline).
 */
export function ForgeChatCube({ state }: { state: CubeState }) {
  return (
    <Canvas
      dpr={[1, 1.5]}
      camera={{ position: [0, 0, 4.2], fov: 38 }}
      gl={{ antialias: true, alpha: true, powerPreference: "low-power" }}
      style={{ background: "transparent" }}
    >
      <ambientLight intensity={0.4} />
      <pointLight position={[3, 3, 4]} intensity={40} color={ACCENT} distance={22} />
      <pointLight position={[-3, -2, 2]} intensity={22} color={STREAM} distance={22} />
      {/* lightweight inline environment → polished metal reflections (no network) */}
      <Environment resolution={64}>
        <Lightformer intensity={2.2} position={[0, 2, 4]} scale={[7, 7, 1]} color="#bae6fd" />
        <Lightformer intensity={1.3} position={[-3, -1, 2]} scale={[5, 5, 1]} color={STREAM} />
        <Lightformer intensity={1} position={[3, 1, -2]} scale={[5, 5, 1]} color="#ffffff" />
      </Environment>
      <Float speed={state === "thinking" ? 3.2 : 1.6} rotationIntensity={0.25} floatIntensity={0.7}>
        <Core state={state} />
      </Float>
      <EffectComposer enableNormalPass={false} multisampling={2}>
        <Bloom intensity={0.7} luminanceThreshold={1} luminanceSmoothing={0.25} mipmapBlur />
      </EffectComposer>
    </Canvas>
  )
}
