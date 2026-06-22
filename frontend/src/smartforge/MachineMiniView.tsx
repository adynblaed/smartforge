import {
  ContactShadows,
  Environment,
  Lightformer,
  MeshReflectorMaterial,
  OrbitControls,
} from "@react-three/drei"
import { Canvas } from "@react-three/fiber"
import { Bloom, EffectComposer } from "@react-three/postprocessing"
import { Suspense } from "react"

import { StationCore } from "./machineModels"

/**
 * Compact 3D preview of a single machine for the Machine Health Console — a
 * windowed view of the SAME scene the Factory Simulation renders. It reuses the
 * exact `StationCore` asset and mirrors the sim's premium look: reflective dark
 * floor, cyan/purple rim lights, studio environment, contact shadows and a
 * subtle emissive bloom, framed from the sim's 3/4 camera angle.
 *
 * It stays synced in real time because the caller passes the live, telemetry-
 * derived `accent` (health colour) and `running` state, so the plinth glow and
 * the model's motion (spindle/arm/ram) track the machine exactly as in-scene.
 *
 * Kept lean (no shadow maps, low dpr/resolution, multisampling off) so several
 * cards can render at once.
 */
export function MachineMiniView({
  type,
  running,
  accent,
}: {
  type: string
  running: boolean
  accent: string
}) {
  return (
    <Canvas
      dpr={[1, 1.5]}
      camera={{ position: [4.8, 3.4, 5.6], fov: 40 }}
      gl={{ antialias: true, powerPreference: "low-power" }}
    >
      {/* a touch lighter stage so the machine reads clearly in the thumbnail */}
      <color attach="background" args={["#11161f"]} />
      <fog attach="fog" args={["#11161f", 12, 30]} />

      <ambientLight intensity={0.85} />
      <directionalLight position={[5, 9, 5]} intensity={2.4} />
      <directionalLight position={[-4, 4, -3]} intensity={0.9} color="#bcd3ff" />
      <pointLight position={[-4, 4, -3]} intensity={24} color="#38bdf8" distance={24} />
      <pointLight position={[4, 3, 4]} intensity={18} color="#a855f7" distance={24} />
      <Environment resolution={128}>
        <Lightformer intensity={3} position={[0, 6, -2]} scale={[10, 5, 1]} color="#cfe0ff" />
        <Lightformer intensity={2.2} position={[5, 4, 4]} scale={[5, 5, 1]} color="#ffffff" />
        <Lightformer intensity={1.6} position={[-5, 3, 3]} scale={[4, 4, 1]} color="#bcd3ff" />
      </Environment>

      <Suspense fallback={null}>
        <group position={[0, -0.35, 0]}>
          {/* highlighted (active) for parity with a selected machine in-scene */}
          <StationCore type={type} running={running} color={accent} active />

          {/* reflective interior floor — same material as the sim */}
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]}>
            <planeGeometry args={[14, 14]} />
            <MeshReflectorMaterial
              resolution={128}
              mixBlur={1}
              mixStrength={5}
              blur={[200, 60]}
              roughness={0.85}
              depthScale={1}
              minDepthThreshold={0.4}
              maxDepthThreshold={1.2}
              color="#0c0f14"
              metalness={0.6}
            />
          </mesh>
          <ContactShadows position={[0, 0.01, 0]} opacity={0.5} scale={6} blur={2.4} far={5} />
        </group>
      </Suspense>

      <EffectComposer enableNormalPass={false} multisampling={0}>
        <Bloom intensity={0.8} luminanceThreshold={1} luminanceSmoothing={0.2} mipmapBlur />
      </EffectComposer>

      <OrbitControls
        enablePan={false}
        enableZoom={false}
        autoRotate
        autoRotateSpeed={0.8}
        minPolarAngle={0.6}
        maxPolarAngle={Math.PI / 2.1}
        target={[0, 0.95, 0]}
      />
    </Canvas>
  )
}
