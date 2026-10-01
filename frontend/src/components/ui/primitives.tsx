import clsx from "clsx";
import { AlertTriangle, Check, ChevronDown, Copy, Inbox, Minus, MoreHorizontal, Plus, RefreshCw } from "lucide-react";
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { gsap } from "@/lib/motion";
import { initials } from "@/lib/format";

/* ------------------------------------------------------------------ Panel */
export function Panel({
  title,
  icon,
  subtitle,
  actions,
  className,
  bodyClass,
  children,
  intro = true,
}: {
  title?: ReactNode;
  icon?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  className?: string;
  bodyClass?: string;
  children: ReactNode;
  intro?: boolean;
}) {
  return (
    <section className={clsx("glass flex min-h-0 flex-col", className)} data-intro={intro ? "panel" : undefined}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 px-5 pb-2 pt-4">
          <div className="flex min-w-0 items-center gap-2.5">
            {icon && <span className="shrink-0 text-accent">{icon}</span>}
            {title && <h3 className="truncate text-[15.5px] font-semibold text-ink">{title}</h3>}
            {subtitle && <span className="truncate text-xs text-muted">{subtitle}</span>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={clsx("min-h-0 flex-1", bodyClass ?? "px-5 pb-4")}>{children}</div>
    </section>
  );
}

/* ----------------------------------------------------------- Status pills */
type Tone = "emerald" | "blue" | "amber" | "red" | "violet" | "slate" | "cyan" | "pink";
const TONE_BY_STATUS: Record<string, Tone> = {
  production: "emerald", healthy: "emerald", completed: "emerald", ready: "emerald", success: "emerald",
  connected: "emerald", active: "emerald", operational: "emerald",
  staging: "blue", processing: "blue", training: "blue", running: "blue", queued: "blue", deploying: "blue", info: "blue",
  development: "amber", degraded: "amber", warning: "amber", skipped: "amber", paused: "amber", seeded: "violet",
  failed: "red", down: "red", critical: "red", disconnected: "red", error: "red",
  archived: "slate", stopped: "slate", pending: "slate", idle: "slate", planned: "slate",
};
const TONE_CLASSES: Record<Tone, { pill: string; dot: string; text: string }> = {
  emerald: { pill: "bg-m-emerald/15 border-m-emerald/40 text-[#4ADE9F]", dot: "bg-m-emerald", text: "text-[#34D399]" },
  blue: { pill: "bg-m-blue/15 border-m-blue/45 text-[#93C5FD]", dot: "bg-m-blue", text: "text-[#60A5FA]" },
  amber: { pill: "bg-m-amber/15 border-m-amber/45 text-[#FCD34D]", dot: "bg-m-amber", text: "text-[#FBBF24]" },
  red: { pill: "bg-m-red/15 border-m-red/45 text-[#FCA5A5]", dot: "bg-m-red", text: "text-[#F87171]" },
  violet: { pill: "bg-m-violet/15 border-m-violet/45 text-[#C4B5FD]", dot: "bg-m-violet", text: "text-[#A78BFA]" },
  slate: { pill: "bg-muted/10 border-muted/30 text-muted", dot: "bg-muted", text: "text-muted" },
  cyan: { pill: "bg-m-cyan/15 border-m-cyan/45 text-[#67E8F9]", dot: "bg-m-cyan", text: "text-[#22D3EE]" },
  pink: { pill: "bg-m-pink/15 border-m-pink/45 text-[#F9A8D4]", dot: "bg-m-pink", text: "text-[#F472B6]" },
};

export function toneOf(status: string | null | undefined): Tone {
  return TONE_BY_STATUS[(status || "").toLowerCase()] ?? "slate";
}

export function StatusPill({ status, dot = true, className }: { status: string; dot?: boolean; className?: string }) {
  const tone = TONE_CLASSES[toneOf(status)];
  const live = ["training", "running", "deploying", "processing", "queued"].includes(status.toLowerCase());
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11.5px] font-medium", tone.pill, className)}>
      {dot && <span className={clsx("h-1.5 w-1.5 rounded-full", tone.dot, live && "animate-pulse-dot")} />}
      {status}
    </span>
  );
}

export function StatusDot({ status, label, className }: { status: string; label?: string; className?: string }) {
  const tone = TONE_CLASSES[toneOf(status)];
  const live = ["training", "running", "deploying", "processing"].includes(status.toLowerCase());
  return (
    <span className={clsx("inline-flex items-center gap-2 text-[12.5px]", tone.text, className)}>
      <span className={clsx("h-2 w-2 shrink-0 rounded-full shadow-[0_0_8px_currentColor]", tone.dot, live && "animate-pulse-dot")} />
      {label ?? status}
    </span>
  );
}

export function TypePill({ label, tone }: { label: string; tone: Tone }) {
  return <span className={clsx("inline-flex rounded-md border px-2 py-0.5 text-[11.5px] font-medium", TONE_CLASSES[tone].pill)}>{label}</span>;
}

/* ---------------------------------------------------------------- Toggle */
export function Toggle({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  label?: string;
}) {
  const knob = useRef<HTMLSpanElement>(null);
  const first = useRef(true);
  useLayoutEffect(() => {
    if (!knob.current) return;
    if (first.current) {
      gsap.set(knob.current, { x: checked ? 18 : 0 });
      first.current = false;
      return;
    }
    gsap.to(knob.current, { x: checked ? 18 : 0, duration: 0.45, ease: "back.out(2)" });
  }, [checked]);
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={clsx(
        "relative inline-flex h-[22px] w-[40px] shrink-0 items-center rounded-full border transition-colors duration-300 disabled:opacity-40",
        checked ? "border-accent/80 bg-accent shadow-glow" : "border-line/40 bg-bg0/60",
      )}
    >
      <span ref={knob} className="absolute left-[2px] h-4 w-4 rounded-full bg-white shadow" />
    </button>
  );
}

/* ---------------------------------------------------------------- Select */
export function Select<T extends string | number>({
  value,
  onChange,
  options,
  className,
  disabled,
  ariaLabel,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string; disabled?: boolean }[];
  className?: string;
  disabled?: boolean;
  ariaLabel?: string;
}) {
  return (
    <div className={clsx("relative", className)}>
      <select
        aria-label={ariaLabel}
        disabled={disabled}
        value={String(value)}
        onChange={(e) => {
          const raw = e.target.value;
          const match = options.find((o) => String(o.value) === raw);
          if (match) onChange(match.value);
        }}
        className="field w-full cursor-pointer appearance-none py-1.5 pl-3 pr-8 text-[12.5px] disabled:cursor-not-allowed disabled:opacity-50"
      >
        {options.map((o) => (
          <option key={String(o.value)} value={String(o.value)} disabled={o.disabled}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown size={14} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-muted" />
    </div>
  );
}

/* ------------------------------------------------------- Loading / empty */
export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("skeleton", className)} />;
}

export function SkeletonRows({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div className={clsx("space-y-2.5", className)}>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-8 w-full" />
      ))}
    </div>
  );
}

export function EmptyState({ title, hint, action, icon }: { title: string; hint?: string; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex h-full min-h-[120px] flex-col items-center justify-center gap-2 py-6 text-center">
      <span className="text-muted">{icon ?? <Inbox size={26} />}</span>
      <p className="text-sm font-medium text-ink/90">{title}</p>
      {hint && <p className="max-w-xs text-xs text-muted">{hint}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="flex h-full min-h-[120px] flex-col items-center justify-center gap-2 py-6 text-center">
      <AlertTriangle size={24} className="text-m-amber" />
      <p className="max-w-sm text-xs text-muted">{message}</p>
      {onRetry && (
        <button className="btn btn-ghost mt-1 py-1 text-xs" onClick={onRetry}>
          <RefreshCw size={12} /> Retry
        </button>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ Tabs */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  className,
}: {
  tabs: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  className?: string;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const bar = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    const el = wrap.current?.querySelector<HTMLButtonElement>(`[data-tab="${value}"]`);
    if (!el || !bar.current) return;
    gsap.to(bar.current, { x: el.offsetLeft, width: el.offsetWidth, duration: 0.35, ease: "power3.out" });
  }, [value, tabs.length]);
  return (
    <div ref={wrap} className={clsx("relative flex gap-1 border-b border-line/15", className)}>
      {tabs.map((t) => (
        <button
          key={t.value}
          data-tab={t.value}
          onClick={() => onChange(t.value)}
          className={clsx(
            "relative px-3 pb-2 pt-1.5 text-[12.5px] transition-colors",
            t.value === value ? "font-medium text-ink" : "text-muted hover:text-ink",
          )}
        >
          {t.label}
        </button>
      ))}
      <span ref={bar} className="absolute bottom-0 left-0 h-[2px] w-10 rounded-full bg-accent shadow-glow" />
    </div>
  );
}

/* --------------------------------------------------------------- Stepper */
export function Stepper({
  value,
  min,
  max,
  step = 1,
  onChange,
  suffix = "",
  disabled,
}: {
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (v: number) => void;
  suffix?: string;
  disabled?: boolean;
}) {
  return (
    <div className={clsx("flex items-center overflow-hidden rounded-lg border border-line/30 bg-bg0/40", disabled && "opacity-50")}>
      <button className="icon-btn h-8 w-8 rounded-none" disabled={disabled || value <= min} onClick={() => onChange(Math.max(min, value - step))} aria-label="Decrease">
        <Minus size={13} />
      </button>
      <span className="min-w-[44px] text-center text-[13px] tabular-nums">
        {value}
        {suffix}
      </span>
      <button className="icon-btn h-8 w-8 rounded-none" disabled={disabled || value >= max} onClick={() => onChange(Math.min(max, value + step))} aria-label="Increase">
        <Plus size={13} />
      </button>
    </div>
  );
}

/* ---------------------------------------------------------------- Slider */
export function Slider({
  value,
  min,
  max,
  step = 1,
  onChange,
  disabled,
  ariaLabel,
}: {
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (v: number) => void;
  disabled?: boolean;
  ariaLabel?: string;
}) {
  const fill = ((value - min) / (max - min || 1)) * 100;
  return (
    <input
      type="range"
      className="slider w-full disabled:opacity-40"
      aria-label={ariaLabel}
      min={min}
      max={max}
      step={step}
      value={value}
      disabled={disabled}
      style={{ ["--fill" as string]: `${fill}%` }}
      onChange={(e) => onChange(Number(e.target.value))}
    />
  );
}

/* ------------------------------------------------------------ CopyButton */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}

export function CopyButton({ text, label = "Copied to clipboard", className }: { text: string; label?: string; className?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className={clsx("icon-btn", className)}
      aria-label="Copy"
      title="Copy"
      onClick={async () => {
        if (await copyText(text)) {
          setDone(true);
          toast.success(label);
          setTimeout(() => setDone(false), 1500);
        } else toast.error("Copy failed");
      }}
    >
      {done ? <Check size={14} className="text-m-emerald" /> : <Copy size={14} />}
    </button>
  );
}

/* ------------------------------------------------------------------ Menu */
export interface MenuItem {
  label: string;
  icon?: ReactNode;
  onClick: () => void;
  danger?: boolean;
  disabled?: boolean;
  hint?: string;
}

export function Menu({ items, trigger, align = "right", className }: { items: MenuItem[]; trigger?: ReactNode; align?: "left" | "right"; className?: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    if (pop.current) gsap.fromTo(pop.current, { opacity: 0, y: -6, scale: 0.97 }, { opacity: 1, y: 0, scale: 1, duration: 0.18, ease: "power2.out" });
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  return (
    <div ref={ref} className={clsx("relative inline-flex", className)}>
      <button
        className="icon-btn"
        aria-label="More actions"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
      >
        {trigger ?? <MoreHorizontal size={16} />}
      </button>
      {open && (
        <div
          ref={pop}
          className={clsx(
            "glass glass-strong absolute top-full z-50 mt-1 min-w-[190px] overflow-hidden p-1 shadow-2xl",
            align === "right" ? "right-0" : "left-0",
          )}
          onClick={(e) => e.stopPropagation()}
        >
          {items.map((item) => (
            <button
              key={item.label}
              disabled={item.disabled}
              title={item.hint}
              onClick={() => {
                setOpen(false);
                item.onClick();
              }}
              className={clsx(
                "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[12.5px] transition-colors disabled:cursor-not-allowed disabled:opacity-40",
                item.danger ? "text-[#F87171] hover:bg-m-red/10" : "hover:bg-accent/10",
              )}
            >
              {item.icon && <span className="opacity-80">{item.icon}</span>}
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- Avatar */
export function Avatar({ name, accent, size = 36, ring = false }: { name: string; accent: string; size?: number; ring?: boolean }) {
  return (
    <span
      className={clsx("relative inline-grid shrink-0 place-items-center rounded-full font-semibold text-white", ring && "ring-2 ring-accent/70")}
      style={{
        width: size,
        height: size,
        fontSize: size * 0.36,
        background: `radial-gradient(circle at 32% 28%, ${accent}ee 0%, ${accent}88 38%, #0b1030 78%)`,
        boxShadow: `0 0 ${size / 2.5}px ${accent}66, inset 0 0 ${size / 4}px rgba(255,255,255,0.25)`,
      }}
    >
      {initials(name)}
    </span>
  );
}

/* ------------------------------------------------------------ Delta chip */
export function Delta({
  value,
  suffix = "",
  invert = false,
  digits = 0,
  className,
}: {
  value: number | null | undefined;
  suffix?: string;
  invert?: boolean;
  digits?: number;
  className?: string;
}) {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  const up = value > 0;
  const good = value === 0 ? true : invert ? !up : up;
  return (
    <span className={clsx("inline-flex items-center gap-0.5 text-[12px] font-medium", good ? "text-[#34D399]" : "text-[#F87171]", className)}>
      {up ? "↑" : value < 0 ? "↓" : "•"} {up ? "+" : ""}
      {value.toFixed(digits)}
      {suffix}
    </span>
  );
}

/* ------------------------------------------------------------ Key/value */
export function KV({ label, children, mono }: { label: string; children: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 py-[7px] text-[12.5px]">
      <span className="shrink-0 text-muted">{label}</span>
      <span className={clsx("min-w-0 truncate text-right text-ink/95", mono && "font-mono text-[11.5px]")}>{children}</span>
    </div>
  );
}
