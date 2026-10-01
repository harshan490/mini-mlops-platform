import { Activity } from "lucide-react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { StatCard } from "@/components/ui/blocks";
import { ChartTooltip, PALETTE, RingGauge } from "@/components/ui/viz";
import { formatTime } from "@/lib/format";
import type { AlertItem } from "@/lib/types";
import { Page, Panel, StatusPill, timeAgo, useGet } from "./kit";

interface Summary {
  production_models: number; total_requests: number; delta_requests_pct: number | null; avg_latency_ms: number | null;
  error_rate_pct: number; avg_drift: number | null; uptime_pct: number;
  spark: Record<string, (number | null)[]>;
  model_health: { deployment_id: number; name: string; status: string; req_per_min: number; latency_ms: number | null; error_rate: number; drift: number | null }[];
  infrastructure: { cpu: number; ram: number; gpu: number };
}
type Point = { ts: string; requests: number; p95_ms: number | null; error_rate: number | null; drift: number | null };

export default function Monitoring() {
  const sum = useGet<Summary>(["mon-sum"], "/api/monitoring/summary", 10000);
  const ts = useGet<{ points: Point[] }>(["mon-ts"], "/api/monitoring/timeseries?hours=24&bucket_min=15", 15000);
  const alerts = useGet<{ items: AlertItem[] }>(["mon-alerts"], "/api/monitoring/alerts?limit=8", 10000);
  const s = sum.data;
  const pts = ts.data?.points ?? [];
  const chart = (key: keyof Point, color: string, title: string) => (
    <Panel title={title} className="col-span-4 h-[260px]">
      <ResponsiveContainer>
        <AreaChart data={pts}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="ts" tickFormatter={(v) => formatTime(v)} minTickGap={50} />
          <YAxis width={40} />
          <Tooltip content={<ChartTooltip labelFormatter={(l) => formatTime(String(l))} />} />
          <Area dataKey={key} name={title} stroke={color} fill={color} fillOpacity={0.15} connectNulls isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </Panel>
  );
  return (
    <Page eyebrow="Monitoring" title="Monitoring" subtitle="Observe. Detect. Ensure. Always On.">
      <div className="grid grid-cols-6 gap-4">
        <StatCard icon={<Activity size={18} />} color={PALETTE.emerald} label="Production Models" value={s?.production_models} />
        <StatCard icon={<Activity size={18} />} color={PALETTE.blue} label="Requests (24h)" value={s?.total_requests} delta={s?.delta_requests_pct} deltaSuffix="%" spark={s?.spark.requests} />
        <StatCard icon={<Activity size={18} />} color={PALETTE.violet} label="Avg Latency ms" value={s?.avg_latency_ms} decimals={1} spark={s?.spark.latency} />
        <StatCard icon={<Activity size={18} />} color={PALETTE.red} label="Error Rate %" value={s?.error_rate_pct} decimals={2} spark={s?.spark.errors} />
        <StatCard icon={<Activity size={18} />} color={PALETTE.pink} label="Drift (PSI)" value={s?.avg_drift} decimals={2} spark={s?.spark.drift} />
        <StatCard icon={<Activity size={18} />} color={PALETTE.cyan} label="Uptime %" value={s?.uptime_pct} decimals={2} />
      </div>
      <div className="grid grid-cols-12 gap-5">
        {chart("requests", PALETTE.blue, "Request Volume")}
        {chart("p95_ms", PALETTE.violet, "Latency (P95 ms)")}
        {chart("drift", PALETTE.pink, "Drift (PSI, >0.25 = drift)")}
      </div>
      <div className="grid grid-cols-12 gap-5">
        <Panel title="Model Health" className="col-span-5">
          <table className="w-full"><thead><tr>{["Deployment", "Status", "Req/min", "Latency", "Errors", "Drift"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
            <tbody>{(s?.model_health ?? []).map((m) => (
              <tr key={m.deployment_id} className="table-row"><td className="td">{m.name}</td><td className="td"><StatusPill status={m.status} /></td>
                <td className="td">{m.req_per_min}</td><td className="td">{m.latency_ms?.toFixed(1) ?? "—"} ms</td><td className="td">{m.error_rate}%</td>
                <td className={`td ${m.drift != null && m.drift > 0.25 ? "text-[#F87171]" : ""}`}>{m.drift?.toFixed(2) ?? "—"}</td></tr>
            ))}</tbody></table>
        </Panel>
        <Panel title="Infrastructure Health" className="col-span-3">
          <div className="flex justify-around pt-4">
            <RingGauge value={s?.infrastructure.cpu} label="CPU" size={96} color={PALETTE.blue} />
            <RingGauge value={s?.infrastructure.ram} label="RAM" size={96} color={PALETTE.violet} />
            <RingGauge value={s?.infrastructure.gpu} label="GPU" size={96} color="#2DD4BF" />
          </div>
        </Panel>
        <Panel title="Recent Alerts" className="col-span-4">
          {(alerts.data?.items ?? []).map((a) => (
            <div key={a.id} className="flex gap-2 border-t border-line/10 py-1.5 text-xs">
              <StatusPill status={a.severity} /><span className="flex-1"><b>{a.title}</b><br /><span className="text-muted">{a.message}</span></span><span className="text-muted">{timeAgo(a.ts)}</span>
            </div>
          ))}
        </Panel>
      </div>
    </Page>
  );
}
