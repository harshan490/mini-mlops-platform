import { lazy, type ReactNode, Suspense, useEffect, useLayoutEffect, useRef, useState } from "react";
import { type Location, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import { ConfirmHost } from "@/components/ui/overlays";
import { Skeleton } from "@/components/ui/primitives";
import { StaticBackdrop } from "@/components/three/CosmicBackground";
import { BACKGROUNDS } from "@/components/three/presets";
import { gsap, reducedMotion, useSpotlight } from "@/lib/motion";
import { useUI } from "@/store/ui";
import { AlertWatcher } from "./AlertWatcher";
import { CommandPalette } from "./CommandPalette";
import { Sidebar } from "./Sidebar";
import { Logo, TopBar } from "./TopBar";

const CosmicBackground = lazy(() => import("@/components/three/CosmicBackground"));

export function PageFallback() {
  return (
    <div className="space-y-5 pt-2">
      <Skeleton className="h-4 w-40" />
      <Skeleton className="h-16 w-[420px]" />
      <div className="grid grid-cols-4 gap-5">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <Skeleton className="h-[360px]" />
    </div>
  );
}

/**
 * Keeps the outgoing page on screen while it fades/blurs out (0.25s), then swaps
 * in the new route whose own intro plays. The WebGL background never unmounts.
 */
function Transition({ render }: { render: (location: Location) => ReactNode }) {
  const location = useLocation();
  const [shown, setShown] = useState(location);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (location.pathname === shown.pathname) {
      if (location.key !== shown.key) setShown(location);
      return;
    }
    const el = box.current;
    if (!el || reducedMotion()) {
      setShown(location);
      return;
    }
    const tween = gsap.to(el, { opacity: 0, y: -8, filter: "blur(6px)", duration: 0.25, ease: "power2.in", onComplete: () => setShown(location) });
    return () => {
      tween.kill();
    };
  }, [location, shown]);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    gsap.set(el, { opacity: 1, y: 0, filter: "blur(0px)", clearProps: "opacity,transform,filter" });
    el.closest("main")?.scrollTo({ top: 0 });
  }, [shown.pathname]);

  return <div ref={box}>{render(shown)}</div>;
}

export function AppLayout({ render }: { render: (location: Location) => ReactNode }) {
  const appearance = useUI((s) => s.appearance);
  const theme = useUI((s) => s.appearance.theme);
  useSpotlight();
  return (
    <div className="fixed inset-0 overflow-hidden">
      <Suspense fallback={<StaticBackdrop preset={BACKGROUNDS[appearance.background] ?? BACKGROUNDS.cosmic} />}>
        <CosmicBackground preset={appearance.background} />
      </Suspense>
      {/* Light theme dims the scene so glass cards stay legible. */}
      <div className="light-veil pointer-events-none fixed inset-0 z-0" />

      <Logo />
      <Sidebar />
      <div className="absolute inset-y-0 left-[var(--sidebar-w)] right-0 z-10 flex flex-col">
        <TopBar />
        <main className="scroll-area relative min-h-0 flex-1 px-[clamp(16px,2.2vw,36px)] pb-8">
          <Suspense fallback={<PageFallback />}>
            <Transition render={render} />
          </Suspense>
        </main>
      </div>
      <CommandPalette />
      <ConfirmHost />
      <AlertWatcher />
      <Toaster
        position="bottom-right"
        theme={theme === "light" ? "light" : "dark"}
        richColors
        closeButton
        toastOptions={{ style: { backdropFilter: "blur(16px)" } }}
      />
    </div>
  );
}
