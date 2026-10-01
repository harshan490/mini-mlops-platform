import clsx from "clsx";
import { Box, ChevronRight, Database, FlaskConical, Home, Rocket, Settings, SquareActivity, Workflow } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { Avatar } from "@/components/ui/primitives";
import { gsap } from "@/lib/motion";
import { useTeam } from "@/lib/queries";
import { useUI } from "@/store/ui";
import { UserMenu } from "./UserMenu";

export const NAV = [
  { to: "/", icon: Home, label: "Dashboard" },
  { to: "/datasets", icon: Database, label: "Datasets" },
  { to: "/experiments", icon: FlaskConical, label: "Experiments" },
  { to: "/models", icon: Box, label: "Model Registry" },
  { to: "/deployments", icon: Rocket, label: "Deployments" },
  { to: "/monitoring", icon: SquareActivity, label: "Monitoring" },
  { to: "/pipelines", icon: Workflow, label: "Pipelines" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

function activeIndex(pathname: string) {
  if (pathname === "/") return 0;
  return NAV.findIndex((n) => n.to !== "/" && pathname.startsWith(n.to));
}

export function Sidebar() {
  const { pathname } = useLocation();
  const listRef = useRef<HTMLDivElement>(null);
  const pill = useRef<HTMLSpanElement>(null);
  const first = useRef(true);
  const idx = activeIndex(pathname);
  const { data: team } = useTeam();
  const user = useUI((s) => s.user);
  const me = team?.find((u) => u.username === user);
  const [menuOpen, setMenuOpen] = useState(false);

  // One glowing pill that tweens between items (FLIP-style) instead of re-rendering per item.
  useLayoutEffect(() => {
    const list = listRef.current;
    const el = pill.current;
    if (!list || !el) return;
    if (idx < 0) {
      gsap.to(el, { opacity: 0, duration: 0.2 });
      return;
    }
    const item = list.querySelectorAll<HTMLElement>("[data-nav]")[idx];
    if (!item) return;
    const y = item.offsetTop;
    if (first.current) {
      gsap.set(el, { y, opacity: 1 });
      first.current = false;
    } else {
      gsap.to(el, { y, opacity: 1, duration: 0.5, ease: "power3.inOut" });
    }
  }, [idx]);

  return (
    <aside className="fixed inset-y-0 left-0 z-30 flex w-[var(--sidebar-w)] flex-col items-center border-r border-line/10 bg-bg0/30 backdrop-blur-[2px]">
      <div className="h-[118px] shrink-0" />
      <nav ref={listRef} className="relative flex flex-col items-center gap-[clamp(6px,1.3vh,14px)]" aria-label="Main">
        <span
          ref={pill}
          aria-hidden
          className="pointer-events-none absolute left-1/2 top-0 h-[52px] w-[52px] -translate-x-1/2 rounded-2xl border border-accent/70 bg-gradient-to-b from-accent/40 to-accent/15 opacity-0 shadow-[0_0_24px_rgb(var(--accent)/0.55),inset_0_1px_0_rgba(255,255,255,0.15)]"
        />
        {NAV.map(({ to, icon: Icon, label }, i) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            data-nav
            title={label}
            aria-label={label}
            className={clsx(
              "group relative z-10 grid h-[52px] w-[52px] place-items-center rounded-2xl transition-colors",
              i === idx ? "text-white" : "text-ink/70 hover:text-ink",
            )}
          >
            <Icon size={21} strokeWidth={1.7} />
            <span className="pointer-events-none absolute left-[62px] whitespace-nowrap rounded-md bg-bg1/95 px-2 py-1 text-[11.5px] text-ink opacity-0 shadow-lg ring-1 ring-line/20 transition-opacity group-hover:opacity-100">
              {label}
            </span>
          </NavLink>
        ))}
      </nav>

      <div className="mt-auto flex flex-col items-center gap-3 pb-5">
        <div className="mb-1 h-px w-8 bg-line/20" />
        <span className="text-[9px] uppercase tracking-[0.25em] text-muted">Team</span>
        {(team ?? []).map((u) => (
          <NavLink
            key={u.username}
            to={`/users/${u.username}`}
            title={`${u.display_name} · ${u.title}`}
            aria-label={`${u.display_name} profile`}
            className={({ isActive }) =>
              clsx("group relative rounded-full transition-transform hover:scale-105", isActive && "ring-2 ring-accent ring-offset-2 ring-offset-bg0")
            }
          >
            <Avatar name={u.display_name} accent={u.accent} size={34} />
            <span className="pointer-events-none absolute left-[46px] top-1/2 -translate-y-1/2 whitespace-nowrap rounded-md bg-bg1/95 px-2 py-1 text-[11.5px] text-ink opacity-0 shadow-lg ring-1 ring-line/20 transition-opacity group-hover:opacity-100">
              {u.display_name}
            </span>
          </NavLink>
        ))}
        <div className="relative mt-2">
          <button
            onClick={() => setMenuOpen((v) => !v)}
            className="relative flex items-center"
            aria-label="Account menu"
            title={me ? `Signed in as ${me.display_name}` : "Account"}
          >
            <span className="grid h-[50px] w-[50px] place-items-center rounded-full bg-[radial-gradient(circle_at_35%_30%,#a5b4fc_0%,#4f46e5_32%,#1e1b4b_62%,#020617_80%)] shadow-[0_0_24px_rgba(99,102,241,0.55),inset_0_0_12px_rgba(255,255,255,0.25)] ring-1 ring-white/20">
              <span className="text-[13px] font-semibold text-white/95">{me ? me.display_name[0] : "·"}</span>
            </span>
            <ChevronRight size={12} className="absolute -right-4 text-muted" />
          </button>
          {menuOpen && <UserMenu onClose={() => setMenuOpen(false)} placement="sidebar" />}
        </div>
      </div>
    </aside>
  );
}
