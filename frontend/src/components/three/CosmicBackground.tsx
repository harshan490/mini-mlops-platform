import { Stars } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { gsap, reducedMotion } from "@/lib/motion";
import type { BackgroundPreset } from "@/lib/types";
import { BACKGROUNDS, type Preset } from "./presets";
import {
  atmosphereFragment,
  lakeFragment,
  planetFragment,
  planetVertex,
  ridgeFragment,
  ridgeVertex,
  skyFragment,
  skyVertex,
  twinkleFragment,
  twinkleVertex,
} from "./shaders";

/** sRGB hex -> vec3 (the canvas renders with `linear`, so values pass through unchanged). */
function vec(hex: string): THREE.Vector3 {
  const n = parseInt(hex.replace("#", ""), 16);
  return new THREE.Vector3(((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255);
}

function tweenVec(target: THREE.Vector3, hex: string) {
  const to = vec(hex);
  gsap.to(target, { x: to.x, y: to.y, z: to.z, duration: 1.4, ease: "power2.inOut" });
}

function useTime() {
  return useMemo(() => ({ value: 0 }), []);
}

function Sky({ preset }: { preset: Preset }) {
  const time = useTime();
  const uniforms = useMemo(
    () => ({
      uTop: { value: vec(preset.skyTop) },
      uMid: { value: vec(preset.skyMid) },
      uHorizon: { value: vec(preset.horizon) },
      uGlowA: { value: vec(preset.glowA) },
      uGlowB: { value: vec(preset.glowB) },
      uTime: time,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  useEffect(() => {
    tweenVec(uniforms.uTop.value, preset.skyTop);
    tweenVec(uniforms.uMid.value, preset.skyMid);
    tweenVec(uniforms.uHorizon.value, preset.horizon);
    tweenVec(uniforms.uGlowA.value, preset.glowA);
    tweenVec(uniforms.uGlowB.value, preset.glowB);
  }, [preset, uniforms]);
  useFrame((_, dt) => {
    time.value += dt;
  });
  return (
    <mesh renderOrder={-10} frustumCulled={false}>
      <planeGeometry args={[2, 2]} />
      <shaderMaterial vertexShader={skyVertex} fragmentShader={skyFragment} uniforms={uniforms} depthWrite={false} depthTest={false} />
    </mesh>
  );
}

function Planet({ preset }: { preset: Preset }) {
  const group = useRef<THREE.Group>(null);
  const time = useTime();
  const uniforms = useMemo(() => ({ uBody: { value: vec(preset.planetBody) }, uRim: { value: vec(preset.planetRim) }, uTime: time }), []); // eslint-disable-line react-hooks/exhaustive-deps
  const atmo = useMemo(() => ({ uRim: { value: vec(preset.planetRim) } }), []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    tweenVec(uniforms.uBody.value, preset.planetBody);
    tweenVec(uniforms.uRim.value, preset.planetRim);
    tweenVec(atmo.uRim.value, preset.planetRim);
  }, [preset, uniforms, atmo]);
  useFrame((_, dt) => {
    time.value += dt;
    if (group.current) group.current.rotation.y += dt * 0.012;
  });
  return (
    <group ref={group} position={[20, 58, -60]}>
      <mesh>
        <sphereGeometry args={[50, 128, 128]} />
        <shaderMaterial vertexShader={planetVertex} fragmentShader={planetFragment} uniforms={uniforms} />
      </mesh>
      <mesh scale={1.07}>
        <sphereGeometry args={[50, 96, 96]} />
        <shaderMaterial
          vertexShader={planetVertex}
          fragmentShader={atmosphereFragment}
          uniforms={atmo}
          side={THREE.BackSide}
          transparent
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </mesh>
    </group>
  );
}

interface RidgeSpec {
  z: number;
  y: number;
  base: number;
  amp: number;
  freq: number;
  seed: number;
  color: number;
  rim: number;
  haze: number;
  peak?: [number, number, number];
}
const RIDGES: RidgeSpec[] = [
  { z: -26, y: -0.5, base: 0.46, amp: 0.2, freq: 9.0, seed: 3.1, color: 0, rim: 0.1, haze: 0.3, peak: [0.3, 0.1, 0.03] },
  { z: -18, y: -1.6, base: 0.36, amp: 0.2, freq: 12.0, seed: 7.7, color: 1, rim: 0.32, haze: 0.08, peak: [0.555, 0.34, 0.03] },
  { z: -11, y: -2.8, base: 0.26, amp: 0.16, freq: 16.0, seed: 1.9, color: 2, rim: 0.14, haze: 0.0 },
  { z: -5, y: -3.6, base: 0.1, amp: 0.15, freq: 22.0, seed: 5.3, color: 3, rim: 0.05, haze: 0.0 },
];

function Ridge({ spec, preset }: { spec: RidgeSpec; preset: Preset }) {
  const uniforms = useMemo(
    () => ({
      uColor: { value: vec(preset.ridges[spec.color]) },
      uRim: { value: vec(preset.rim) },
      uGlow: { value: vec(preset.glowA) },
      uSeed: { value: spec.seed },
      uAmp: { value: spec.amp },
      uBase: { value: spec.base },
      uFreq: { value: spec.freq },
      uPeakX: { value: spec.peak?.[0] ?? 0.5 },
      uPeakH: { value: spec.peak?.[1] ?? 0 },
      uPeakW: { value: spec.peak?.[2] ?? 0.1 },
      uRimStrength: { value: spec.rim },
      uHaze: { value: spec.haze },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  useEffect(() => {
    tweenVec(uniforms.uColor.value, preset.ridges[spec.color]);
    tweenVec(uniforms.uRim.value, preset.rim);
    tweenVec(uniforms.uGlow.value, preset.glowA);
  }, [preset, spec.color, uniforms]);
  const width = 30 + Math.abs(spec.z) * 2.6;
  const height = 6 + Math.abs(spec.z) * 0.9;
  return (
    <mesh position={[0, spec.y, spec.z]}>
      <planeGeometry args={[width, height]} />
      <shaderMaterial vertexShader={ridgeVertex} fragmentShader={ridgeFragment} uniforms={uniforms} />
    </mesh>
  );
}

function Lake({ preset }: { preset: Preset }) {
  const time = useTime();
  const uniforms = useMemo(
    () => ({ uLake: { value: vec(preset.lake) }, uGlowA: { value: vec(preset.glowA) }, uGlowB: { value: vec(preset.glowB) }, uTime: time }),
    [], // eslint-disable-line react-hooks/exhaustive-deps
  );
  useEffect(() => {
    tweenVec(uniforms.uLake.value, preset.lake);
    tweenVec(uniforms.uGlowA.value, preset.glowA);
    tweenVec(uniforms.uGlowB.value, preset.glowB);
  }, [preset, uniforms]);
  useFrame((_, dt) => {
    time.value += dt;
  });
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -3.0, -6]}>
      <planeGeometry args={[90, 40]} />
      <shaderMaterial vertexShader={ridgeVertex} fragmentShader={lakeFragment} uniforms={uniforms} />
    </mesh>
  );
}

function Twinkles({ color }: { color: string }) {
  const time = useTime();
  const geo = useMemo(() => {
    const n = 320;
    const pos = new Float32Array(n * 3);
    const phase = new Float32Array(n);
    const size = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      pos[i * 3] = (Math.random() - 0.5) * 120;
      pos[i * 3 + 1] = Math.random() * 40 + 2;
      pos[i * 3 + 2] = -40 - Math.random() * 20;
      phase[i] = Math.random();
      size[i] = 1.5 + Math.random() * 3.5;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("aPhase", new THREE.BufferAttribute(phase, 1));
    g.setAttribute("aSize", new THREE.BufferAttribute(size, 1));
    return g;
  }, []);
  const uniforms = useMemo(() => ({ uTime: time, uColor: { value: vec(color) } }), []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => tweenVec(uniforms.uColor.value, color), [color, uniforms]);
  useFrame((_, dt) => {
    time.value += dt;
  });
  return (
    <points geometry={geo}>
      <shaderMaterial vertexShader={twinkleVertex} fragmentShader={twinkleFragment} uniforms={uniforms} transparent depthWrite={false} blending={THREE.AdditiveBlending} />
    </points>
  );
}

/** Lerped camera offset that follows the mouse. */
function Parallax() {
  const { camera } = useThree();
  const mouse = useRef({ x: 0, y: 0 });
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      mouse.current.x = (e.clientX / window.innerWidth) * 2 - 1;
      mouse.current.y = (e.clientY / window.innerHeight) * 2 - 1;
    };
    window.addEventListener("mousemove", onMove, { passive: true });
    return () => window.removeEventListener("mousemove", onMove);
  }, []);
  useFrame(() => {
    camera.position.x += (mouse.current.x * 0.9 - camera.position.x) * 0.035;
    camera.position.y += (0.6 - mouse.current.y * 0.4 - camera.position.y) * 0.035;
    camera.lookAt(0, 0.4, -20);
  });
  return null;
}

function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

export function StaticBackdrop({ preset }: { preset: Preset }) {
  return (
    <div className="pointer-events-none fixed inset-0 z-0" aria-hidden>
      <div
        className="absolute inset-0"
        style={{
          background: `radial-gradient(70% 45% at 30% 0%, ${preset.planetRim}22 0%, transparent 60%),
            radial-gradient(60% 30% at 80% 48%, ${preset.glowB}33 0%, transparent 70%),
            linear-gradient(180deg, ${preset.skyTop} 0%, ${preset.skyMid} 38%, ${preset.horizon} 52%, ${preset.lake} 100%)`,
        }}
      />
      <svg className="absolute bottom-0 left-0 h-[55%] w-full" viewBox="0 0 1600 500" preserveAspectRatio="none">
        <path d="M0 260 L120 200 L210 240 L340 150 L460 230 L560 170 L700 240 L860 60 L990 210 L1100 160 L1240 230 L1380 180 L1600 240 L1600 500 L0 500Z" fill={preset.ridges[1]} />
        <path d="M0 340 L160 290 L300 330 L450 270 L620 340 L780 300 L940 350 L1120 290 L1300 340 L1460 300 L1600 330 L1600 500 L0 500Z" fill={preset.ridges[2]} />
        <path d="M0 430 L200 390 L420 420 L640 380 L880 430 L1100 395 L1350 430 L1600 400 L1600 500 L0 500Z" fill={preset.ridges[3]} />
      </svg>
    </div>
  );
}

/** Fixed full-screen cosmic scene behind every page. It never unmounts across route changes. */
export default function CosmicBackground({ preset: presetKey }: { preset: BackgroundPreset }) {
  const preset = BACKGROUNDS[presetKey] ?? BACKGROUNDS.cosmic;
  const [visible, setVisible] = useState(() => !document.hidden);
  const [canRender] = useState(() => webglAvailable() && !reducedMotion());

  useEffect(() => {
    const onVis = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  if (!canRender) return <StaticBackdrop preset={preset} />;

  return (
    <div className="pointer-events-none fixed inset-0 z-0" aria-hidden>
      <Canvas
        linear
        flat
        dpr={[1, 1.5]}
        frameloop={visible ? "always" : "never"}
        camera={{ position: [0, 0.6, 10], fov: 50, near: 0.1, far: 400 }}
        gl={{ antialias: false, powerPreference: "high-performance", alpha: false, stencil: false }}
      >
        <Sky preset={preset} />
        <Stars radius={90} depth={40} count={2200} factor={3.2} saturation={0} fade speed={0.7} />
        <Twinkles color={preset.planetRim} />
        <Planet preset={preset} />
        {RIDGES.map((r) => (
          <Ridge key={r.z} spec={r} preset={preset} />
        ))}
        <Lake preset={preset} />
        <Parallax />
        <EffectComposer multisampling={0}>
          <Bloom intensity={0.6} luminanceThreshold={0.42} luminanceSmoothing={0.25} mipmapBlur />
        </EffectComposer>
      </Canvas>
    </div>
  );
}
