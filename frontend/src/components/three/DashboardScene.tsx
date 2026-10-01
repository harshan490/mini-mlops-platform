import { Float, Html, Line } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { Box, Database, FlaskConical, Rocket } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { CountUp, reducedMotion } from "@/lib/motion";

export interface HeroCounts {
  datasets: number;
  delta_datasets: number;
  experiments: number;
  delta_experiments: number;
  models: number;
  delta_models: number;
  deployments: number;
  delta_deployments: number;
}

const RX = 5.6;
const RZ = 1.9;
const RING_Y = -1.2;

function ringPoint(x: number): [number, number, number] {
  const c = Math.max(-0.98, Math.min(0.98, x / RX));
  const theta = Math.acos(c);
  return [RX * Math.cos(theta), RING_Y, RZ * Math.sin(theta)];
}

/** Low-poly "data mountain" with luminous edges at the centre of the orbit. */
export function Peak() {
  const geo = useMemo(() => {
    const g = new THREE.ConeGeometry(3.0, 4.6, 11, 7, true);
    const pos = g.attributes.position as THREE.BufferAttribute;
    const v = new THREE.Vector3();
    for (let i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i);
      const k = (2.3 - v.y) / 4.6; // 0 at tip, 1 at base
      const n = Math.sin(v.x * 3.1 + v.z * 1.7) * 0.22 + Math.cos(v.z * 2.3 - v.y * 1.3) * 0.18;
      v.x += n * k;
      v.z += n * 0.6 * k;
      v.y += Math.sin(v.x * 2.0) * 0.18 * k;
      pos.setXYZ(i, v.x, v.y, v.z);
    }
    g.computeVertexNormals();
    return g;
  }, []);
  const edges = useMemo(() => new THREE.EdgesGeometry(geo, 18), [geo]);
  return (
    <group position={[0, 1.1, -0.4]}>
      <mesh geometry={geo}>
        <meshStandardMaterial color="#0b1030" roughness={0.85} metalness={0.15} flatShading emissive="#1b1d5a" emissiveIntensity={0.35} side={THREE.DoubleSide} />
      </mesh>
      <lineSegments geometry={edges}>
        <lineBasicMaterial color="#8f9bff" transparent opacity={0.55} blending={THREE.AdditiveBlending} />
      </lineSegments>
    </group>
  );
}

function OrbitRing() {
  const dashed = useRef<THREE.Object3D & { material: { dashOffset: number } }>(null);
  const points = useMemo(() => {
    const pts: [number, number, number][] = [];
    for (let i = 0; i <= 160; i++) {
      const t = (i / 160) * Math.PI * 2;
      pts.push([RX * Math.cos(t), RING_Y, RZ * Math.sin(t)]);
    }
    return pts;
  }, []);
  useFrame((_, dt) => {
    if (dashed.current && !reducedMotion()) dashed.current.material.dashOffset -= dt * 0.8;
  });
  return (
    <group>
      <Line points={points} color="#3b82f6" lineWidth={6} transparent opacity={0.18} />
      <Line points={points} color="#7aa7ff" lineWidth={1.6} transparent opacity={0.9} />
      <Line ref={dashed as never} points={points} color="#c4b5fd" lineWidth={2.2} dashed dashSize={0.9} gapSize={0.6} transparent opacity={0.9} />
    </group>
  );
}

function Connector({ from, color }: { from: [number, number, number]; color: string }) {
  const to = ringPoint(from[0]);
  const dot = useRef<THREE.Mesh>(null);
  useFrame(({ clock }) => {
    if (dot.current) dot.current.scale.setScalar(1 + Math.sin(clock.elapsedTime * 3 + from[0]) * 0.25);
  });
  return (
    <group>
      <Line points={[[from[0], from[1] - 0.75, from[2]], to]} color={color} lineWidth={1.4} transparent opacity={0.85} />
      <mesh ref={dot} position={to}>
        <sphereGeometry args={[0.09, 16, 16]} />
        <meshBasicMaterial color={color} />
      </mesh>
      <mesh position={to}>
        <sphereGeometry args={[0.22, 16, 16]} />
        <meshBasicMaterial color={color} transparent opacity={0.25} blending={THREE.AdditiveBlending} depthWrite={false} />
      </mesh>
    </group>
  );
}

function HeroCard({
  position,
  color,
  icon,
  label,
  value,
  delta,
  to,
  tilt,
  onNavigate,
}: {
  position: [number, number, number];
  color: string;
  icon: ReactNode;
  label: string;
  value: number | undefined;
  delta: number | undefined;
  to: string;
  tilt: number;
  onNavigate: (to: string) => void;
}) {
  return (
    <>
      <Float speed={1.3} rotationIntensity={0.08} floatIntensity={0.45} floatingRange={[-0.08, 0.08]}>
        <group position={position} rotation={[0, tilt, 0.04 * Math.sign(-tilt)]}>
          <Html transform distanceFactor={7} center zIndexRange={[20, 10]}>
            <button
              onClick={() => onNavigate(to)}
              className="glass glass-hover flex w-[170px] items-center gap-3 px-4 py-3 text-left"
              style={{ borderColor: `${color}66`, boxShadow: `0 0 26px ${color}33, inset 0 1px 0 rgba(255,255,255,0.1)` }}
            >
              <span className="grid h-10 w-10 place-items-center rounded-xl" style={{ color, background: `${color}22`, boxShadow: `0 0 16px ${color}55` }}>
                {icon}
              </span>
              <span className="min-w-0">
                <span className="block text-[12px] text-ink/85">{label}</span>
                <span className="flex items-baseline gap-2">
                  <span className="text-[26px] font-semibold leading-none tabular-nums">
                    <CountUp value={value} />
                  </span>
                  {delta !== undefined && delta > 0 && <span className="text-[11px] font-medium text-[#34D399]">↑ +{delta}</span>}
                </span>
              </span>
            </button>
          </Html>
        </group>
      </Float>
      <Connector from={position} color={color} />
    </>
  );
}

/** Router context does not reach drei <Html> roots, so navigation is passed in. */
export default function DashboardScene({ counts, onNavigate }: { counts: HeroCounts | undefined; onNavigate: (to: string) => void }) {
  const [visible, setVisible] = useState(() => !document.hidden);
  useEffect(() => {
    const onVis = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);
  return (
    <Canvas
      linear
      dpr={[1, 1.5]}
      frameloop={visible ? "always" : "never"}
      camera={{ position: [0, 1.6, 12.5], fov: 38 }}
      gl={{ alpha: true, antialias: true, powerPreference: "high-performance" }}
      style={{ background: "transparent" }}
    >
      <ambientLight intensity={0.25} />
      <directionalLight position={[-6, 8, 6]} intensity={1.1} color="#8aa4ff" />
      <pointLight position={[2, 4, 3]} intensity={18} distance={14} color="#a78bfa" />

      <OrbitRing />
      <HeroCard position={[-4.4, 1.7, 0.9]} color="#3B82F6" icon={<Database size={20} />} label="Datasets" value={counts?.datasets} delta={counts?.delta_datasets} to="/datasets" tilt={0.18} onNavigate={onNavigate} />
      <HeroCard position={[-1.1, 3.4, 0.2]} color="#8B5CF6" icon={<FlaskConical size={20} />} label="Experiments" value={counts?.experiments} delta={counts?.delta_experiments} to="/experiments" tilt={0.06} onNavigate={onNavigate} />
      <HeroCard position={[2.3, 2.3, 0.6]} color="#10B981" icon={<Box size={20} />} label="Models" value={counts?.models} delta={counts?.delta_models} to="/models" tilt={-0.08} onNavigate={onNavigate} />
      <HeroCard position={[5.3, 1.3, 0.5]} color="#F59E0B" icon={<Rocket size={20} />} label="Deployments" value={counts?.deployments} delta={counts?.delta_deployments} to="/deployments" tilt={-0.2} onNavigate={onNavigate} />
    </Canvas>
  );
}
