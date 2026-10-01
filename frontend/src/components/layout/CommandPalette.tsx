import clsx from "clsx";
import { Box, CornerDownLeft, Database, FlaskConical, Rocket, Search, Sparkles, UserRound, Workflow } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { gsap } from "@/lib/motion";
import { useTeam } from "@/lib/queries";
import type { SearchResult } from "@/lib/types";
import { useUI } from "@/store/ui";
import { NAV } from "./Sidebar";

const ICONS: Record<SearchResult["type"], JSX.Element> = {
  dataset: <Database size={15} />,
  experiment: <FlaskConical size={15} />,
  model: <Box size={15} />,
  deployment: <Rocket size={15} />,
  pipeline: <Workflow size={15} />,
  user: <UserRound size={15} />,
};

function useDebounced<T>(value: T, ms: number) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Global search across datasets, experiments, models, deployments, pipelines and team (Ctrl+K). */
export function CommandPalette() {
  const { paletteOpen: open, setPaletteOpen } = useUI();
  const [q, setQ] = useState("");
  const [cursor, setCursor] = useState(0);
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const query = useDebounced(q.trim(), 160);
  const { data: team } = useTeam();
  const { data, isFetching } = useQuery({
    queryKey: ["search", query],
    queryFn: () => api.get<{ results: SearchResult[] }>(`/api/search?q=${encodeURIComponent(query)}`),
    enabled: open && query.length > 0,
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen(!useUI.getState().paletteOpen);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setPaletteOpen]);

  useEffect(() => {
    if (!open) return;
    setQ((prev) => prev);
    setCursor(0);
    setTimeout(() => input.current?.focus(), 30);
    if (card.current) gsap.fromTo(card.current, { opacity: 0, y: -14, scale: 0.98 }, { opacity: 1, y: 0, scale: 1, duration: 0.25, ease: "power3.out" });
  }, [open]);

  const items: SearchResult[] = useMemo(() => {
    if (query) return data?.results ?? [];
    const pages: SearchResult[] = NAV.map((n, i) => ({ type: "pipeline", id: -i - 1, title: n.label, subtitle: "Go to page", link: n.to }));
    const people: SearchResult[] = (team ?? []).map((u) => ({ type: "user", id: u.id, title: u.display_name, subtitle: `${u.title} · profile`, link: `/users/${u.username}` }));
    return [...people, ...pages];
  }, [query, data, team]);

  useEffect(() => setCursor(0), [query]);

  if (!open) return null;
  const go = (r: SearchResult | undefined) => {
    if (!r) return;
    navigate(r.link);
    setPaletteOpen(false);
    setQ("");
  };

  return createPortal(
    <div className="fixed inset-0 z-[95] flex justify-center bg-[#02040d]/60 px-4 pt-[12vh] backdrop-blur-sm" onMouseDown={() => setPaletteOpen(false)}>
      <div ref={card} className="glass glass-strong h-fit w-full max-w-[640px] overflow-hidden shadow-2xl" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-line/15 px-4 py-3.5">
          <Sparkles size={18} className="text-accent" />
          <input
            ref={input}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setCursor((c) => Math.min(items.length - 1, c + 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setCursor((c) => Math.max(0, c - 1));
              } else if (e.key === "Enter") go(items[cursor]);
              else if (e.key === "Escape") setPaletteOpen(false);
            }}
            placeholder="Search datasets, runs, models, deployments, people…"
            className="flex-1 bg-transparent text-[15px] outline-none placeholder:text-muted"
          />
          {isFetching ? <span className="h-4 w-4 animate-spin-slow rounded-full border-2 border-accent border-t-transparent" /> : <Search size={16} className="text-muted" />}
          <kbd className="rounded border border-line/30 px-1.5 text-[10.5px] text-muted">Esc</kbd>
        </div>
        <div className="scroll-area max-h-[52vh] p-2">
          {!query && <div className="px-3 pb-1 pt-2 text-[10.5px] uppercase tracking-[0.25em] text-muted">Quick links</div>}
          {query && !isFetching && items.length === 0 && <div className="p-8 text-center text-sm text-muted">No results for “{query}”.</div>}
          {items.map((r, i) => (
            <button
              key={`${r.type}-${r.id}-${r.link}`}
              onMouseEnter={() => setCursor(i)}
              onClick={() => go(r)}
              className={clsx("flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left", i === cursor ? "bg-accent/15" : "hover:bg-accent/5")}
            >
              <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent/10 text-accent">{query || r.type === "user" ? ICONS[r.type] : <CornerDownLeft size={14} />}</span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium">{r.title}</span>
                <span className="block truncate text-[11.5px] text-muted">{r.subtitle}</span>
              </span>
              {query && <span className="text-[10.5px] uppercase tracking-wider text-muted">{r.type}</span>}
            </button>
          ))}
        </div>
      </div>
    </div>,
    document.body,
  );
}
