import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { type RefObject, useEffect, useRef } from "react";

gsap.registerPlugin(useGSAP, ScrollTrigger);

export const reducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/**
 * Route intro, reused by every page:
 * eyebrow letters stagger in -> title slides up 40px and un-blurs -> subtitle fades ->
 * stat cards stagger up (0.08s) -> glass panels scale 0.97 -> 1 in grid order.
 */
export function usePageIntro(scope: RefObject<HTMLElement>) {
  useGSAP(
    () => {
      if (reducedMotion()) return;
      const q = gsap.utils.selector(scope);
      const tl = gsap.timeline({ defaults: { ease: "power3.out" } });
      const letters = q("[data-intro=eyebrow] .ch");
      if (letters.length) tl.from(letters, { opacity: 0, y: 8, stagger: 0.022, duration: 0.35 });
      const title = q("[data-intro=title]");
      if (title.length)
        tl.from(title, { y: 40, opacity: 0, filter: "blur(8px)", duration: 0.8, clearProps: "transform,opacity,filter" }, letters.length ? "-=0.25" : 0);
      const sub = q("[data-intro=subtitle]");
      if (sub.length) tl.from(sub, { opacity: 0, y: 10, duration: 0.6, stagger: 0.08, clearProps: "transform,opacity" }, "-=0.55");
      const quote = q("[data-intro=quote]");
      if (quote.length) tl.from(quote, { opacity: 0, x: 24, duration: 0.8, clearProps: "transform,opacity" }, "<");
      const stats = q("[data-intro=stat]");
      if (stats.length) tl.from(stats, { y: 24, opacity: 0, stagger: 0.08, duration: 0.6, clearProps: "transform,opacity" }, "-=0.55");
      const panels = q("[data-intro=panel]");
      if (panels.length)
        tl.from(panels, { scale: 0.97, opacity: 0, stagger: 0.06, duration: 0.6, clearProps: "transform,opacity" }, "-=0.45");
    },
    { scope },
  );
}

/** Letter-split eyebrow label (letters animate in via usePageIntro). */
export function Eyebrow({ text, className = "" }: { text: string; className?: string }) {
  return (
    <div className={`eyebrow ${className}`} data-intro="eyebrow" aria-label={text}>
      {text.split("").map((c, i) => (
        <span key={i} className="ch inline-block" aria-hidden>
          {c === " " ? " " : c}
        </span>
      ))}
    </div>
  );
}

/** Number that tweens from its previous value to the new one (never jumps). */
export function CountUp({
  value,
  decimals = 0,
  prefix = "",
  suffix = "",
  duration = 1.1,
  format,
}: {
  value: number | null | undefined;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  duration?: number;
  format?: (v: number) => string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const current = useRef(0);
  const render = (v: number) => `${prefix}${format ? format(v) : v.toFixed(decimals)}${suffix}`;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (value === null || value === undefined || Number.isNaN(value)) {
      el.textContent = "—";
      return;
    }
    if (reducedMotion()) {
      current.current = value;
      el.textContent = render(value);
      return;
    }
    const obj = { v: current.current };
    const tween = gsap.to(obj, {
      v: value,
      duration,
      ease: "power2.out",
      onUpdate: () => {
        current.current = obj.v;
        el.textContent = render(obj.v);
      },
    });
    return () => {
      tween.kill();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, decimals, prefix, suffix]);

  return <span ref={ref}>{value === null || value === undefined ? "—" : render(0)}</span>;
}

/** Draw chart strokes (strokeDashoffset) then fade area fills in, once per `key`. */
export function useChartDraw(ref: RefObject<HTMLElement>, ready: boolean, key: unknown = null) {
  useEffect(() => {
    if (!ready || reducedMotion()) return;
    const el = ref.current;
    if (!el) return;
    const timer = window.setTimeout(() => {
      const paths = Array.from(el.querySelectorAll<SVGPathElement>(".recharts-line-curve, .recharts-area-curve")).filter(
        (p) => !p.getAttribute("stroke-dasharray"),
      );
      paths.forEach((p) => {
        const len = p.getTotalLength?.() ?? 0;
        if (!len) return;
        gsap.fromTo(
          p,
          { strokeDasharray: len, strokeDashoffset: len },
          {
            strokeDashoffset: 0,
            duration: 1.3,
            ease: "power2.inOut",
            onComplete: () => {
              p.style.strokeDasharray = "";
              p.style.strokeDashoffset = "";
            },
          },
        );
      });
      const fills = el.querySelectorAll(".recharts-area-area");
      if (fills.length) gsap.fromTo(fills, { opacity: 0 }, { opacity: 1, duration: 0.9, delay: 0.7 });
      const bars = el.querySelectorAll(".recharts-bar-rectangle path");
      if (bars.length)
        gsap.fromTo(bars, { scaleY: 0, transformOrigin: "50% 100%" }, { scaleY: 1, duration: 0.7, stagger: 0.04, ease: "power3.out", clearProps: "transform" });
    }, 90);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, key]);
}

/** Cascade table rows in (0.04s stagger) the first time rows appear. */
export function useRowCascade(ref: RefObject<HTMLElement>, count: number) {
  const done = useRef(false);
  useEffect(() => {
    if (done.current || count === 0 || reducedMotion()) return;
    const el = ref.current;
    if (!el) return;
    done.current = true;
    gsap.from(el.querySelectorAll("[data-row]"), { opacity: 0, y: 8, stagger: 0.04, duration: 0.45, ease: "power2.out", clearProps: "transform,opacity" });
  }, [count, ref]);
}

/** Global cursor-following highlight for .glass cards (sets --mx/--my). */
export function useSpotlight() {
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const el = (e.target as HTMLElement | null)?.closest?.(".glass") as HTMLElement | null;
      if (!el) return;
      const r = el.getBoundingClientRect();
      el.style.setProperty("--mx", `${e.clientX - r.left}px`);
      el.style.setProperty("--my", `${e.clientY - r.top}px`);
    };
    window.addEventListener("mousemove", onMove, { passive: true });
    return () => window.removeEventListener("mousemove", onMove);
  }, []);
}

export { gsap };
