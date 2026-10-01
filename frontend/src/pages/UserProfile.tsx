import { useParams } from "react-router-dom";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Box, Database, FlaskConical, Rocket, Target, TrendingUp } from "lucide-react";
import { StatCard } from "@/components/ui/blocks";
import { Avatar } from "@/components/ui/primitives";
import { ChartTooltip, PALETTE } from "@/components/ui/viz";
import type { UserProfile as P } from "@/lib/types";
import { useUI } from "@/store/ui";
import { Page, Panel, StatusPill, timeAgo, useGet } from "./kit";

export default function UserProfile() {
  const { username = "" } = useParams();
  const q = useGet<P>(["user", username], `/api/users/${username}`, 15000);
  const { user, setUser } = useUI();
  const u = q.data;
  if (q.error) return <Page eyebrow="Team member" title="Not found" subtitle={String(q.error)}><div /></Page>;
  return (
    <Page key={username} eyebrow="Team member" title={u?.display_name ?? "…"} subtitle={u ? `${u.title} · ${u.role}` : ""}
      right={u && (
        <div className="glass flex items-center gap-4 px-5 py-4 text-xs" data-intro="quote">
          <Avatar name={u.display_name} accent={u.accent} size={64} />
          <div className="space-y-1">
            <div>{u.email}</div><div className="text-muted">{u.location} · joined {timeAgo(u.joined_at)} · active {timeAgo(u.last_active)}</div>
            <div className="max-w-sm text-ink/80">{u.bio}</div>
            {user === u.username ? <span className="text-accent">You are acting as {u.display_name}</span>
              : <button className="btn btn-primary py-1" onClick={() => setUser(u.username)}>Switch to {u.display_name}</button>}
          </div>
        </div>
      )}>
      <div className="grid grid-cols-6 gap-4">
        <StatCard icon={<Database size={18} />} color={PALETTE.blue} label="Datasets" value={u?.stats.datasets} />
        <StatCard icon={<FlaskConical size={18} />} color={PALETTE.violet} label="Experiments" value={u?.stats.experiments} />
        <StatCard icon={<Box size={18} />} color={PALETTE.emerald} label="Models" value={u?.stats.models} />
        <StatCard icon={<Rocket size={18} />} color={PALETTE.amber} label="Deployments" value={u?.stats.deployments} />
        <StatCard icon={<Target size={18} />} color={PALETTE.cyan} label="Best Accuracy" value={u?.stats.best_accuracy} decimals={3} />
        <StatCard icon={<TrendingUp size={18} />} color={PALETTE.pink} label="Success Rate %" value={u?.stats.success_rate} decimals={1} />
      </div>
      <div className="grid grid-cols-12 gap-5">
        <Panel title="Activity (30 days)" className="col-span-7 h-[280px]">
          <ResponsiveContainer>
            <BarChart data={u?.activity_series ?? []}>
              <CartesianGrid vertical={false} /><XAxis dataKey="date" tickFormatter={(d) => String(d).slice(5)} minTickGap={20} /><YAxis width={28} allowDecimals={false} />
              <Tooltip content={<ChartTooltip />} />
              {(["experiment", "dataset", "model", "deployment", "pipeline"] as const).map((k, i) => (
                <Bar key={k} dataKey={k} name={k} stackId="a" fill={[PALETTE.violet, PALETTE.blue, PALETTE.emerald, PALETTE.amber, PALETTE.cyan][i]} isAnimationActive={false} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </Panel>
        <Panel title="Team comparison" className="col-span-5">
          {(u?.team ?? []).map((t) => (
            <Link key={t.username} to={`/users/${t.username}`} className="flex items-center gap-3 border-t border-line/10 py-2 text-xs">
              <Avatar name={t.display_name} accent={t.accent} size={30} /><b className="w-20">{t.display_name}</b>
              <span>{t.experiments} runs</span><span>{t.models} models</span><span>{t.datasets} datasets</span><span>avg acc {t.avg_accuracy?.toFixed(3) ?? "—"}</span>
            </Link>
          ))}
        </Panel>
        <Panel title="Recent experiments" className="col-span-4">
          {(u?.recent_runs ?? []).map((r) => (
            <Link key={r.id} to={`/experiments?select=${r.id}`} className="flex gap-2 border-t border-line/10 py-1.5 text-xs"><b className="w-14">{r.code}</b><span className="flex-1">{r.algorithm}</span><StatusPill status={r.status} /><span>{r.accuracy?.toFixed(3) ?? "—"}</span></Link>
          ))}
        </Panel>
        <Panel title="Models & deployments" className="col-span-4">
          {(u?.models ?? []).map((m) => <Link key={m.id} to={`/models?select=${m.id}`} className="flex gap-2 border-t border-line/10 py-1.5 text-xs"><b className="flex-1">{m.name} {m.version}</b><StatusPill status={m.stage} /></Link>)}
          {(u?.deployments ?? []).map((d) => <Link key={d.id} to={`/deployments?select=${d.id}`} className="flex gap-2 border-t border-line/10 py-1.5 text-xs"><span className="flex-1">🚀 {d.name} ({d.environment})</span><StatusPill status={d.status} /></Link>)}
        </Panel>
        <Panel title="Activity feed" className="col-span-4">
          <div className="scroll-area max-h-[300px]">{(u?.feed ?? []).map((a) => <Link key={a.id} to={a.link || "#"} className="block border-t border-line/10 py-1.5 text-xs">{a.message}<span className="float-right text-muted">{timeAgo(a.ts)}</span></Link>)}</div>
        </Panel>
      </div>
    </Page>
  );
}
