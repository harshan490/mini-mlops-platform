import clsx from "clsx";
import { Check, LogOut, UserRound } from "lucide-react";
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { Avatar } from "@/components/ui/primitives";
import { gsap } from "@/lib/motion";
import { useTeam } from "@/lib/queries";
import { useUI } from "@/store/ui";

/** Workspace member switcher: the acting user is sent as X-User on every request. */
export function UserMenu({ onClose, placement }: { onClose: () => void; placement: "sidebar" | "top" }) {
  const ref = useRef<HTMLDivElement>(null);
  const { data: team } = useTeam();
  const { user, setUser, token, setToken, authRequired } = useUI();
  const navigate = useNavigate();
  const qc = useQueryClient();

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) onClose();
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    const t = setTimeout(() => document.addEventListener("mousedown", close), 0);
    document.addEventListener("keydown", esc);
    if (ref.current) gsap.fromTo(ref.current, { opacity: 0, y: 6, scale: 0.97 }, { opacity: 1, y: 0, scale: 1, duration: 0.2 });
    return () => {
      clearTimeout(t);
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      className={clsx(
        "glass glass-strong absolute z-[70] w-[260px] p-2 shadow-2xl",
        placement === "sidebar" ? "bottom-0 left-[64px]" : "right-0 top-[60px]",
      )}
    >
      <div className="px-2 pb-1 pt-1 text-[10.5px] uppercase tracking-[0.25em] text-muted">Workspace members</div>
      {(team ?? []).map((u) => (
        <div key={u.username} className="flex items-center gap-2.5 rounded-xl px-2 py-2 hover:bg-accent/10">
          <Avatar name={u.display_name} accent={u.accent} size={34} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5 text-[13px] font-medium">
              {u.display_name}
              {u.username === user && <span className="rounded bg-accent/20 px-1.5 text-[10px] text-accent">active</span>}
            </div>
            <div className="truncate text-[11px] text-muted">{u.title}</div>
          </div>
          <button
            className="icon-btn"
            title="View profile"
            aria-label={`View ${u.display_name} profile`}
            onClick={() => {
              navigate(`/users/${u.username}`);
              onClose();
            }}
          >
            <UserRound size={14} />
          </button>
          <button
            className="icon-btn"
            title={u.username === user ? "Active" : `Switch to ${u.display_name}`}
            aria-label={`Switch to ${u.display_name}`}
            disabled={u.username === user}
            onClick={() => {
              setUser(u.username);
              qc.invalidateQueries();
              toast.success(`Now acting as ${u.display_name}`, { description: "New runs, uploads and deployments are credited to this member." });
              onClose();
            }}
          >
            <Check size={14} className={u.username === user ? "text-m-emerald" : "opacity-40"} />
          </button>
        </div>
      ))}
      {authRequired && token && (
        <button
          className="mt-1 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-[12.5px] text-[#F87171] hover:bg-m-red/10"
          onClick={() => {
            setToken(null);
            onClose();
          }}
        >
          <LogOut size={14} /> Sign out
        </button>
      )}
    </div>
  );
}
