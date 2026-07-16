import { Edges, RoundedBox } from "@react-three/drei"
import { useFrame } from "@react-three/fiber"
import type { ReactNode } from "react"
import { useRef } from "react"
import type { Group, Mesh } from "three"

// Shared procedural machine art used by the Factory Simulation and the
// Machine Health Console mini-viewer.

const STEEL = "#2b2f38"
const STEEL_LIGHT = "#3a3f4b"
const CHROME = "#aeb6c4"

export function CncMill({ running }: { running: boolean }) {
  const spindle = useRef<Mesh>(null)
  useFrame((_, dt) => {
    if (running && spindle.current) spindle.current.rotation.y += dt * 8
  })
  return (
    <group>
      <RoundedBox
        args={[1.7, 0.7, 1.3]}
        radius={0.08}
        smoothness={4}
        position={[0, 0.35, 0]}
        castShadow
        receiveShadow
      >
        <meshStandardMaterial
          color={STEEL_LIGHT}
          metalness={0.85}
          roughness={0.28}
          envMapIntensity={1.2}
        />
      </RoundedBox>
      <RoundedBox
        args={[0.36, 1.25, 0.36]}
        radius={0.05}
        smoothness={4}
        position={[-0.55, 1.2, -0.32]}
        castShadow
      >
        <meshStandardMaterial color={STEEL} metalness={0.9} roughness={0.25} />
      </RoundedBox>
      <mesh ref={spindle} position={[0.1, 1.05, 0]} castShadow>
        <cylinderGeometry args={[0.12, 0.12, 0.55, 24]} />
        <meshStandardMaterial
          color={CHROME}
          metalness={1}
          roughness={0.12}
          envMapIntensity={1.5}
        />
      </mesh>
    </group>
  )
}

export function RoboticArm({ running }: { running: boolean }) {
  const arm = useRef<Group>(null)
  useFrame((s) => {
    if (running && arm.current)
      arm.current.rotation.y = Math.sin(s.clock.elapsedTime) * 0.9
  })
  return (
    <group>
      <mesh position={[0, 0.25, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[0.5, 0.62, 0.5, 36]} />
        <meshStandardMaterial
          color={STEEL_LIGHT}
          metalness={0.85}
          roughness={0.28}
        />
      </mesh>
      <group ref={arm} position={[0, 0.5, 0]}>
        <RoundedBox
          args={[0.26, 1.05, 0.26]}
          radius={0.06}
          smoothness={4}
          position={[0, 0.5, 0]}
          castShadow
        >
          <meshStandardMaterial
            color="#ea7a09"
            metalness={0.6}
            roughness={0.35}
          />
        </RoundedBox>
        <RoundedBox
          args={[1.05, 0.22, 0.22]}
          radius={0.06}
          smoothness={4}
          position={[0.5, 1, 0]}
          rotation={[0, 0, 0.6]}
          castShadow
        >
          <meshStandardMaterial
            color="#f59e0b"
            metalness={0.6}
            roughness={0.35}
          />
        </RoundedBox>
        <mesh position={[0.95, 1.35, 0]} castShadow>
          <sphereGeometry args={[0.12, 20, 20]} />
          <meshStandardMaterial color={CHROME} metalness={1} roughness={0.15} />
        </mesh>
      </group>
    </group>
  )
}

export function Press({ running }: { running: boolean }) {
  const ram = useRef<Mesh>(null)
  useFrame((s) => {
    if (running && ram.current)
      ram.current.position.y =
        1.15 + Math.abs(Math.sin(s.clock.elapsedTime * 3)) * 0.3
  })
  return (
    <group>
      <RoundedBox
        args={[1.5, 0.7, 1.5]}
        radius={0.08}
        smoothness={4}
        position={[0, 0.35, 0]}
        castShadow
        receiveShadow
      >
        <meshStandardMaterial
          color={STEEL_LIGHT}
          metalness={0.85}
          roughness={0.28}
        />
      </RoundedBox>
      {[-0.62, 0.62].map((x) => (
        <RoundedBox
          key={x}
          args={[0.22, 2, 0.22]}
          radius={0.05}
          smoothness={3}
          position={[x, 1.45, 0]}
          castShadow
        >
          <meshStandardMaterial
            color={STEEL}
            metalness={0.9}
            roughness={0.25}
          />
        </RoundedBox>
      ))}
      <RoundedBox
        ref={ram}
        args={[1.25, 0.32, 1.25]}
        radius={0.06}
        smoothness={4}
        position={[0, 1.15, 0]}
        castShadow
      >
        <meshStandardMaterial
          color={CHROME}
          metalness={1}
          roughness={0.16}
          envMapIntensity={1.4}
        />
      </RoundedBox>
    </group>
  )
}

export function ProceduralModel({
  type,
  running,
}: {
  type: string
  running: boolean
}) {
  if (type === "cnc_mill") return <CncMill running={running} />
  if (type === "robotic_arm") return <RoboticArm running={running} />
  return <Press running={running} />
}

/**
 * A complete machine station — health-tinted plinth + model + status beacon.
 * Shared verbatim by the Factory Simulation and the Machine Console mini-view so
 * the card previews are a 1:1 match for the in-scene asset. `active` drives the
 * highlighted/selected emissive glow. Pass `children` to substitute an imported
 * model for the procedural one.
 */
export function StationCore({
  type,
  running,
  color,
  active,
  children,
}: {
  type: string
  running: boolean
  color: string
  active: boolean
  children?: ReactNode
}) {
  return (
    <group>
      {/* sleek plinth */}
      <RoundedBox
        args={[2.6, 0.14, 2.6]}
        radius={0.06}
        smoothness={4}
        position={[0, 0.07, 0]}
        receiveShadow
      >
        <meshStandardMaterial
          color={active ? color : "#14171d"}
          emissive={color}
          emissiveIntensity={active ? 2.4 : 0.12}
          metalness={0.5}
          roughness={0.45}
        />
        <Edges
          scale={1.005}
          threshold={15}
          color={active ? color : "#2a2f3a"}
        />
      </RoundedBox>

      <group position={[0, 0.14, 0]}>
        {children ?? <ProceduralModel type={type} running={running} />}
      </group>

      {/* status beacon (blooms in the full scene) */}
      <mesh position={[0, 2.5, 0]}>
        <sphereGeometry args={[0.11, 18, 18]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={3}
        />
      </mesh>
    </group>
  )
}
