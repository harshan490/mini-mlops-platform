import clsx from "clsx";
import { type ReactNode, useEffect, useId, useLayoutEffect, useRef } from "react";
import { gsap, reducedMotion } from "@/lib/motion";

export const PALETTE = {
  blue: "#3B82F6",
  violet: "#8B5CF6",
  cyan: "#22D3EE",
  emerald: "#10B981",
  amber: "#F59E0B",
  pink: "#EC4899",
  red: "#EF4444",
};
export const SERIES = [PALETTE.blue, PALETTE.violet, PALETTE.emerald, PALETTE.amber, PALETTE.pink, PALETTE.cyan];

/* ------------------------------------------------------------ Ring gauge */
export function RingGauge({
  value,
  label,
  color = PALETTE.blue,
  size = 124,
  stroke = 9,
  sub,
}: {
  value: number | null | undefined;
  label: string;
  color?: string;
  size?: number;
  stroke?: number;
  sub?: ReactNode;
}) {
  const arc = useRef<SVGCircleElement>(null);
  const text = useRef<HTMLSpanElement>(null);
  const shown = useRef(0);
  const id = useId();
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(100, value ?? 0));

  useEffect(() => {
    const el = arc.current;
    if (!el) return;
    const obj = { v: shown.current };
    const tween = gsap.to(obj, {
      v,
      duration: reducedMotion() ? 0 : 1.1,
      ease: "power2.out",
      onUpdate: () => {
        shown.current = obj.v;
        el.style.strokeDashoffset = String(c * (1 - obj.v / 100));
        if (text.current) text.current.textContent = value === null || value === undefined ? "—" : `${Math.round(obj.v)}%`;
      },
    });
    return () => {
      tween.kill();
    };
  }, [v, c, value]);

  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <defs>
          <linearGradient id={`g${id}`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.55} />
            <stop offset="100%" stopColor={color} />
          </linearGradient>
        </defs>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgb(var(--line) / 0.14)" strokeWidth={stroke} />
        <circle
          ref={arc}
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={`url(#g${id})`}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c}
          style={{ filter: `drop-shadow(0 0 6px ${color}99)` }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-[12px] text-ink/80">{label}</span>
        <span ref={text} className="text-[24px] font-semibold tabular-nums leading-tight">
          —
        </span>
        {sub && <span className="text-[10.5px] text-muted">{sub}</span>}
      </div>
    </div>
  );
}

/* ----------------------------------------------------------- Progress bar */
export function ProgressBar({
  value,
  className,
  color,
  height = 8,
  indeterminate,
}: {
  value: number;
  className?: string;
  color?: string;
  height?: number;
  indeterminate?: boolean;
}) {
  const bar = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (!bar.current) return;
    gsap.to(bar.current, { width: `${Math.max(0, Math.min(100, value))}%`, duration: reducedMotion() ? 0 : 0.6, ease: "power2.out" });
  }, [value]);
  return (
    <div className={clsx("relative w-full overflow-hidden rounded-full bg-line/15", className)} style={{ height }}>
      <div
        ref={bar}
        className={clsx("h-full rounded-full", indeterminate && "animate-pulse")}
        style={{
          width: 0,
          background: color ?? "linear-gradient(90deg, rgb(var(--accent)), rgb(var(--m-cyan)))",
          boxShadow: "0 0 14px rgb(var(--accent) / 0.55)",
        }}
      />
    </div>
  );
}

/* --------------------------------------------------------------- Sparkline */
export function Sparkline({
  data,
  color = PALETTE.blue,
  width = 120,
  height = 36,
  fill = true,
  className,
}: {
  data: (number | null)[];
  color?: string;
  width?: number;
  height?: number;
  fill?: boolean;
  className?: string;
}) {
  const id = useId();
  const path = useRef<SVGPathElement>(null);
  const clean = data.map((d) => (d === null || Number.isNaN(d) ? null : d));
  const vals = clean.filter((d): d is number => d !== null);
  const drawn = useRef(false);

  useEffect(() => {
    if (drawn.current || !path.current || vals.length < 2 || reducedMotion()) return;
    drawn.current = true;
    const len = path.current.getTotalLength();
    gsap.fromTo(path.current, { strokeDasharray: len, strokeDashoffset: len }, {
      strokeDashoffset: 0,
      duration: 1.2,
      ease: "power2.inOut",
      onComplete: () => {
        if (path.current) {
          path.current.style.strokeDasharray = "";
          path.current.style.strokeDashoffset = "";
        }
      },
    });
  }, [vals.length]);

  if (vals.length < 2) return <div className={className} style={{ width, height }} />;
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const step = width / (clean.length - 1);
  let d = "";
  let started = false;
  clean.forEach((v, i) => {
    if (v === null) return;
    const x = i * step;
    const y = height - 3 - ((v - min) / span) * (height - 6);
    d += `${started ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)} `;
    started = true;
  });
  const firstIdx = clean.findIndex((v) => v !== null);
  const lastIdx = clean.length - 1 - [...clean].reverse().findIndex((v) => v !== null);
  const area = `${d}L${(lastIdx * step).toFixed(1)},${height} L${(firstIdx * step).toFixed(1)},${height} Z`;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={className} preserveAspectRatio="none">
      <defs>
        <linearGradient id={`s${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.45} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      {fill && <path d={area} fill={`url(#s${id})`} />}
      <path ref={path} d={d} fill="none" stroke={color} strokeWidth={1.8} strokeLinejoin="round" strokeLinecap="round"
        style={{ filter: `drop-shadow(0 0 4px ${color}aa)` }} />
    </svg>
  );
}

/* ------------------------------------------------------ Recharts tooltip */
interface TooltipPayload {
  name?: string;
  value?: number | string | null;
  color?: string;
  stroke?: string;
  fill?: string;
  dataKey?: string | number;
}
export function ChartTooltip({
  active,
  payload,
  label,
  labelFormatter,
  valueFormatter,
}: {
  active?: boolean;
  payload?: TooltipPayload[];
  label?: string | number;
  labelFormatter?: (l: string | number) => string;
  valueFormatter?: (v: number, name: string) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="glass glass-strong px-3 py-2 text-[11.5px] shadow-xl">
      {label !== undefined && <div className="mb-1 text-muted">{labelFormatter ? labelFormatter(label) : label}</div>}
      {payload
        .filter((p) => p.value !== null && p.value !== undefined)
        .map((p) => (
          <div key={String(p.dataKey ?? p.name)} className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full" style={{ background: p.color || p.stroke || p.fill }} />
            <span className="text-ink/80">{p.name}</span>
            <span className="ml-auto pl-3 font-medium tabular-nums">
              {typeof p.value === "number" ? (valueFormatter ? valueFormatter(p.value, String(p.name)) : Number(p.value.toFixed(4))) : p.value}
            </span>
          </div>
        ))}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-ink/80">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full" style={{ background: i.color, boxShadow: `0 0 6px ${i.color}` }} />
          {i.label}
        </span>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------ Icon tile */
export function IconTile({ children, color = PALETTE.blue, size = 44 }: { children: ReactNode; color?: string; size?: number }) {
  return (
    <span
      className="grid shrink-0 place-items-center rounded-xl"
      style={{
        width: size,
        height: size,
        color,
        background: `linear-gradient(145deg, ${color}33, ${color}10)`,
        border: `1px solid ${color}55`,
        boxShadow: `0 0 18px ${color}33, inset 0 1px 0 rgba(255,255,255,0.08)`,
      }}
    >
      {children}
    </span>
  );
}
