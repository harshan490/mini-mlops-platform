export const NOISE = /* glsl */ `
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123); }
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
}
float fbm(vec2 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 5; i++) { v += a * noise(p); p *= 2.03; a *= 0.5; }
  return v;
}
float ridged(vec2 p) {
  float v = 0.0, a = 0.55;
  for (int i = 0; i < 5; i++) { float n = 1.0 - abs(noise(p) * 2.0 - 1.0); v += a * n * n; p *= 2.1; a *= 0.5; }
  return v;
}
`;

/** Screen-space sky: vertical gradient, horizon glow band (warm on the right), faint nebula. */
export const skyVertex = /* glsl */ `
varying vec2 vUv;
void main() { vUv = uv; gl_Position = vec4(position.xy, 0.9999, 1.0); }
`;
export const skyFragment = /* glsl */ `
uniform vec3 uTop; uniform vec3 uMid; uniform vec3 uHorizon; uniform vec3 uGlowA; uniform vec3 uGlowB;
uniform float uTime;
varying vec2 vUv;
${NOISE}
void main() {
  float y = vUv.y;
  vec3 col = mix(uHorizon, uMid, smoothstep(0.30, 0.64, y));
  col = mix(col, uTop, smoothstep(0.62, 1.0, y));
  float band = exp(-pow((y - 0.42) * 6.5, 2.0));
  vec3 glow = mix(uGlowA, uGlowB, smoothstep(0.45, 1.05, vUv.x));
  col += glow * band * (0.28 + 0.42 * smoothstep(0.25, 1.0, vUv.x));
  float n = fbm(vUv * vec2(3.2, 2.2) + vec2(uTime * 0.006, uTime * 0.002));
  col += uGlowA * pow(n, 3.2) * 0.22 * smoothstep(0.38, 0.95, y);
  gl_FragColor = vec4(col, 1.0);
}
`;

/** Mountain ridge layer: silhouette from ridged noise plus an optional central peak with a luminous rim. */
export const ridgeVertex = /* glsl */ `
varying vec2 vUv;
void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
`;
export const ridgeFragment = /* glsl */ `
uniform vec3 uColor; uniform vec3 uRim; uniform vec3 uGlow;
uniform float uSeed; uniform float uAmp; uniform float uBase; uniform float uFreq;
uniform float uPeakX; uniform float uPeakH; uniform float uPeakW; uniform float uRimStrength; uniform float uHaze;
varying vec2 vUv;
${NOISE}
float ridgeH(float x) {
  float h = uBase + uAmp * ridged(vec2(x * uFreq, uSeed));
  h += uPeakH * exp(-pow((x - uPeakX) / uPeakW, 2.0)) * (0.85 + 0.3 * noise(vec2(x * 30.0, uSeed)));
  return h;
}
void main() {
  float h = ridgeH(vUv.x);
  float y = vUv.y;
  if (y > h) discard;
  float depth = h - y;
  vec3 col = mix(uColor * 1.15, uColor * 0.45, smoothstep(0.0, 0.3, depth));
  float strata = fbm(vec2(vUv.x * 14.0 + y * 6.0, y * 60.0 + uSeed * 3.0));
  col *= 0.86 + 0.24 * strata;
  float slope = (ridgeH(vUv.x + 0.0025) - h) / 0.0025;
  col += uRim * clamp(-slope * 0.08, 0.0, 1.0) * smoothstep(0.16, 0.0, depth) * 0.35;
  float edge = smoothstep(h - 0.006, h, y);
  col += uRim * edge * uRimStrength;
  col = mix(col, uGlow, uHaze * smoothstep(0.2, 0.0, depth));
  gl_FragColor = vec4(col, 1.0);
}
`;

/** Lake: dark water reflecting the horizon glow with drifting horizontal glints. */
export const lakeFragment = /* glsl */ `
uniform vec3 uLake; uniform vec3 uGlowA; uniform vec3 uGlowB; uniform float uTime;
varying vec2 vUv;
${NOISE}
void main() {
  float far = smoothstep(0.0, 1.0, vUv.y);
  vec3 col = mix(uLake * 0.6, uLake * 1.4, far);
  float streak = noise(vec2(vUv.x * 6.0 + uTime * 0.03, vUv.y * 140.0));
  vec3 glow = mix(uGlowA, uGlowB, smoothstep(0.4, 1.0, vUv.x));
  col += glow * pow(streak, 6.0) * 0.7 * far;
  col += glow * 0.18 * pow(far, 3.0);
  gl_FragColor = vec4(col, 1.0);
}
`;

/** Planet with Fresnel rim light. */
export const planetVertex = /* glsl */ `
varying vec3 vN; varying vec3 vV; varying vec3 vPos;
void main() {
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vN = normalize(normalMatrix * normal);
  vV = normalize(-mv.xyz);
  vPos = position;
  gl_Position = projectionMatrix * mv;
}
`;
export const planetFragment = /* glsl */ `
uniform vec3 uBody; uniform vec3 uRim; uniform float uTime;
varying vec3 vN; varying vec3 vV; varying vec3 vPos;
${NOISE}
void main() {
  float fres = pow(1.0 - max(dot(vN, vV), 0.0), 2.6);
  float lit = max(dot(vN, normalize(vec3(-0.35, -0.55, 0.75))), 0.0);
  float bands = fbm(vec2(vPos.y * 1.6 + uTime * 0.01, vPos.x * 0.35 + vPos.z * 0.35));
  vec3 col = uBody * (0.04 + 0.28 * lit) * (0.75 + 0.5 * bands) + uRim * pow(fres, 1.4) * 0.75;
  gl_FragColor = vec4(col, 1.0);
}
`;
export const atmosphereFragment = /* glsl */ `
uniform vec3 uRim;
varying vec3 vN; varying vec3 vV; varying vec3 vPos;
void main() {
  float i = pow(clamp(0.7 - dot(vN, vV), 0.0, 1.0), 3.0);
  gl_FragColor = vec4(uRim * i * 0.9, i);
}
`;

/** Extra twinkling stars: per-star phase modulates size and brightness. */
export const twinkleVertex = /* glsl */ `
attribute float aPhase; attribute float aSize;
uniform float uTime;
varying float vAlpha;
void main() {
  float t = 0.55 + 0.45 * sin(uTime * (0.8 + aPhase * 0.6) + aPhase * 6.2831);
  vAlpha = t;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_PointSize = aSize * (0.6 + 0.6 * t) * (60.0 / -mv.z);
  gl_Position = projectionMatrix * mv;
}
`;
export const twinkleFragment = /* glsl */ `
uniform vec3 uColor;
varying float vAlpha;
void main() {
  vec2 c = gl_PointCoord - 0.5;
  float d = length(c);
  float a = smoothstep(0.5, 0.0, d) * vAlpha;
  gl_FragColor = vec4(uColor * (0.6 + vAlpha), a);
}
`;
