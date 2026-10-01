import clsx from "clsx";
import { AlertTriangle, Bell, CheckCheck, CheckCircle2, Info, Search, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { gsap } from "@/lib/motion";
import { useAlerts } from "@/lib/queries";
import type { AlertItem } from "@/lib/types";
import { useUI } from "@/store/ui";
import { UserMenu } from "./UserMenu";

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return now;
}

export function Logo() {
  return (
    <div className="pointer-events-none fixed left-[26px] top-[26px] z-40 flex select-none items-center gap-3">
      <svg width="46" height="40" viewBox="0 0 64 56" aria-hidden>
        <defs>
          <linearGradient id="lg1" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#7CB4FF" />
            <stop offset="1" stopColor="#2F6BFF" />
          </linearGradient>
          <linearGradient id="lg2" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#3B5BFF" />
            <stop offset="1" stopColor="#1E1B6E" />
          </linearGradient>
        </defs>
        <path d="M24 2 48 54H0Z" fill="url(#lg1)" />
        <path d="M42 18 64 54H22Z" fill="url(#lg2)" opacity="0.95" />
      </svg>
      <span className="text-[20px] font-medium tracking-tight text-ink">Mini MLOps</span>
    </div>
  );
}

const SEVERITY_ICON: Record<AlertItem["severity"], JSX.Element> = {
  critical: <XCircle size={15} className="text-[#F87171]" />,
  warning: <AlertTriangle size={15} className="text-[#FBBF24]" />,
  info: <Info size={15} className="text-[#60A5FA]" />,
  success: <CheckCircle2 size={15} className="text-[#34D399]" />,
};

function NotificationBell() {
  const [open, setOpen] = useState(false);
  const { data } = useAlerts(20);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const ref = useRef<HTMLDivElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const unread = data?.unread ?? 0;

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    if (pop.current) gsap.fromTo(pop.current, { opacity: 0, y: -8 }, { opacity: 1, y: 0, duration: 0.2 });
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const markRead = async (a: AlertItem) => {
    if (!a.read) await api.post(`/api/alerts/${a.id}/read`);
    qc.invalidateQueries({ queryKey: ["alerts"] });
  };

  return (
    <div ref={ref} className="relative">
      <button
        className="glass grid h-[46px] w-[46px] place-items-center rounded-xl hover:border-accent/60"
        aria-label={`Notifications (${unread} unread)`}
        onClick={() => setOpen((v) => !v)}
      >
        <Bell size={19} strokeWidth={1.7} />
        {unread > 0 && (
          <span className="absolute right-[9px] top-[8px] h-[9px] w-[9px] rounded-full bg-m-red shadow-[0_0_10px_rgb(var(--m-red))] ring-2 ring-bg0" />
        )}
      </button>
      {open && (
        <div ref={pop} className="glass glass-strong absolute right-0 top-[56px] z-[70] w-[380px] overflow-hidden shadow-2xl">
          <div className="flex items-center justify-between border-b border-line/15 px-4 py-3">
            <div className="text-[13.5px] font-semibold">
              Notifications {unread > 0 && <span className="ml-1 rounded bg-m-red/20 px-1.5 text-[11px] text-[#FCA5A5]">{unread} new</span>}
            </div>
            <button
              className="btn btn-ghost py-1 text-[11.5px]"
              disabled={unread === 0}
              onClick={async () => {
                await api.post("/api/alerts/read-all");
                qc.invalidateQueries({ queryKey: ["alerts"] });
              }}
            >
              <CheckCheck size={13} /> Mark all read
            </button>
          </div>
          <div className="scroll-area max-h-[420px]">
            {(data?.items ?? []).length === 0 && <div className="p-6 text-center text-xs text-muted">No notifications yet.</div>}
            {(data?.items ?? []).map((a) => (
              <button
                key={a.id}
                onClick={() => {
                  markRead(a);
                  if (a.category === "monitoring" || a.category === "deployment") navigate(a.deployment_id ? `/deployments?select=${a.deployment_id}` : "/monitoring");
                  else navigate("/experiments");
                  setOpen(false);
                }}
                className={clsx("flex w-full gap-3 border-b border-line/10 px-4 py-3 text-left hover:bg-accent/5", !a.read && "bg-accent/[0.06]")}
              >
                <span className="mt-0.5">{SEVERITY_ICON[a.severity]}</span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2 text-[12.5px] font-medium">
                    {a.title}
                    {!a.read && <span className="h-1.5 w-1.5 rounded-full bg-accent" />}
                  </span>
                  <span className="mt-0.5 block text-[11.5px] leading-snug text-muted">{a.message}</span>
                </span>
                <span className="shrink-0 text-[11px] text-muted">{timeAgo(a.ts)}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function TopBar() {
  const now = useClock();
  const setPaletteOpen = useUI((s) => s.setPaletteOpen);
  const [menu, setMenu] = useState(false);
  const part = (o: Intl.DateTimeFormatOptions) => now.toLocaleDateString("en-GB", o);
  const date = `${part({ weekday: "short" })}, ${part({ day: "numeric" })} ${part({ month: "short" })} ${part({ year: "numeric" })}`;
  const time = now.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: true });

  return (
    <div className="pointer-events-none flex h-[96px] shrink-0 items-center justify-end gap-4 pr-7">
      <div className="pointer-events-auto mr-6 text-right leading-tight" aria-live="off">
        <div className="text-[15px] text-ink/90">{date}</div>
        <div className="text-[15px] tabular-nums text-ink/90">{time}</div>
      </div>
      <button
        className="glass pointer-events-auto grid h-[46px] w-[46px] place-items-center rounded-xl hover:border-accent/60"
        onClick={() => setPaletteOpen(true)}
        aria-label="Search (Ctrl+K)"
        title="Search (Ctrl+K)"
      >
        <Search size={19} strokeWidth={1.7} />
      </button>
      <div className="pointer-events-auto">
        <NotificationBell />
      </div>
      <div className="pointer-events-auto relative ml-2">
        <button
          onClick={() => setMenu((v) => !v)}
          aria-label="Account menu"
          className="block h-[54px] w-[54px] rounded-full bg-[radial-gradient(circle_at_35%_30%,#e0e7ff_0%,#818cf8_18%,#4338ca_40%,#1e1b4b_66%,#020617_86%)] shadow-[0_0_26px_rgba(129,140,248,0.6),inset_-6px_-8px_16px_rgba(0,0,0,0.55)] ring-2 ring-white/25 transition-transform hover:scale-105"
        />
        {menu && <UserMenu onClose={() => setMenu(false)} placement="top" />}
      </div>
    </div>
  );
}
