import clsx from "clsx";
import { X } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { create } from "zustand";
import { gsap } from "@/lib/motion";

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  width = 560,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
}) {
  const card = useRef<HTMLDivElement>(null);
  const backdrop = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", esc);
    if (backdrop.current) gsap.fromTo(backdrop.current, { opacity: 0 }, { opacity: 1, duration: 0.2 });
    if (card.current) gsap.fromTo(card.current, { opacity: 0, scale: 0.95, y: 12 }, { opacity: 1, scale: 1, y: 0, duration: 0.3, ease: "power3.out" });
    return () => document.removeEventListener("keydown", esc);
  }, [open, onClose]);
  if (!open) return null;
  return createPortal(
    <div ref={backdrop} className="fixed inset-0 z-[90] grid place-items-center bg-[#02040d]/70 p-4 backdrop-blur-sm" onMouseDown={onClose}>
      <div
        ref={card}
        role="dialog"
        aria-modal="true"
        className="glass glass-strong flex max-h-[88vh] w-full flex-col"
        style={{ maxWidth: width }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-line/15 px-5 py-3.5">
          <h3 className="text-[15px] font-semibold">{title}</h3>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </header>
        <div className="scroll-area min-h-0 flex-1 px-5 py-4">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-line/15 px-5 py-3">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}

export function Drawer({
  open,
  onClose,
  title,
  children,
  width = 520,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  width?: number;
}) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", esc);
    if (panel.current) gsap.fromTo(panel.current, { x: 60, opacity: 0 }, { x: 0, opacity: 1, duration: 0.35, ease: "power3.out" });
    return () => document.removeEventListener("keydown", esc);
  }, [open, onClose]);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-[85] bg-[#02040d]/50 backdrop-blur-[2px]" onMouseDown={onClose}>
      <aside
        ref={panel}
        className="glass glass-strong absolute bottom-3 right-3 top-3 flex flex-col"
        style={{ width: `min(${width}px, calc(100vw - 24px))` }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-line/15 px-5 py-3.5">
          <h3 className="text-[15px] font-semibold">{title}</h3>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </header>
        <div className="min-h-0 flex-1">{children}</div>
      </aside>
    </div>,
    document.body,
  );
}

/* ----------------------------------------------------- Confirm dialogs */
interface ConfirmRequest {
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  resolve: (ok: boolean) => void;
}
const useConfirmStore = create<{ req: ConfirmRequest | null; set: (r: ConfirmRequest | null) => void }>((set) => ({
  req: null,
  set: (req) => set({ req }),
}));

export function confirmAction(opts: Omit<ConfirmRequest, "resolve">): Promise<boolean> {
  return new Promise((resolve) => useConfirmStore.getState().set({ ...opts, resolve }));
}

export function ConfirmHost() {
  const { req, set } = useConfirmStore();
  const [busy, setBusy] = useState(false);
  const close = (ok: boolean) => {
    req?.resolve(ok);
    setBusy(false);
    set(null);
  };
  return (
    <Modal
      open={!!req}
      onClose={() => close(false)}
      title={req?.title ?? ""}
      width={440}
      footer={
        <>
          <button className="btn btn-ghost" onClick={() => close(false)}>
            Cancel
          </button>
          <button
            className={clsx("btn", req?.danger ? "btn-danger" : "btn-primary")}
            disabled={busy}
            onClick={() => {
              setBusy(true);
              close(true);
            }}
          >
            {req?.confirmLabel ?? "Confirm"}
          </button>
        </>
      }
    >
      <div className="text-[13px] leading-relaxed text-ink/85">{req?.message}</div>
    </Modal>
  );
}
