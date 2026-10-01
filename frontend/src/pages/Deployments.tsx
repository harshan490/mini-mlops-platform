import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Rocket, RotateCcw, Zap } from "lucide-react";
import { StatCard } from "@/components/ui/blocks";
import { CopyButton, KV, Toggle } from "@/components/ui/primitives";
import { PALETTE, ProgressBar } from "@/components/ui/viz";
import { api } from "@/lib/api";
import type { DeploymentDetail, DeploymentRow, PredictionLogRow } from "@/lib/types";
import { Page, Panel, StatusPill, Table, timeAgo, useAct, useGet } from "./kit";

export default function Deployments() {
  const [params, setParams] = useSearchParams();
  const act = useAct();
  const stats = useGet<{ active: number; production: number; requests_24h: number; avg_latency_ms: number | null; delta_requests_pct: number | null }>(["d-stats"], "/api/deployments/stats", 5000);
  const list = useGet<DeploymentRow[]>(["deps"], "/api/deployments", 3000);
  const id = Number(params.get("select")) || list.data?.[0]?.id || null;
  const d = useGet<DeploymentDetail>(["dep", id], `/api/deployments/${id}`, 2000);
  const logs = useGet<PredictionLogRow[]>(["dep-logs", id], `/api/deployments/${id}/logs?limit=12`, 2000);
  const [input, setInput] = useState("");
  const [result, setResult] = useState<string>("");
  const dep = d.data;
  useEffect(() => {
    if (dep?.sample_input) setInput(JSON.stringify({ features: dep.sample_input }, null, 2));
  }, [dep?.id, dep?.sample_input]);
  const s = stats.data;
  const predict = async () => {
    if (!dep) return;
    try {
      const res = await fetch(dep.endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: input });
      setResult(JSON.stringify(await res.json(), null, 2));
    } catch (e) {
      setResult(String(e));
    }
  };
  return (
    <Page eyebrow="Deployments" title="Deployments" subtitle="Manage, monitor and scale your machine learning models in production.">
      <div className="grid grid-cols-4 gap-5">
        <StatCard icon={<Rocket size={20} />} color={PALETTE.blue} label="Active Deployments" value={s?.active} />
        <StatCard icon={<Rocket size={20} />} color={PALETTE.emerald} label="Production Endpoints" value={s?.production} />
        <StatCard icon={<Zap size={20} />} color={PALETTE.cyan} label="Requests (24h)" value={s?.requests_24h} delta={s?.delta_requests_pct} deltaSuffix="%" />
        <StatCard icon={<Zap size={20} />} color={PALETTE.violet} label="Avg Latency (ms)" value={s?.avg_latency_ms} decimals={1} />
      </div>
      <div className="grid grid-cols-12 gap-5">
        <Panel title="Model Deployments" className="col-span-7">
          <Table q={list} selected={id} onRow={(x) => setParams({ select: String(x.id) })} cols={[
            { h: "Service", r: (x) => <span className="font-medium">{x.name}</span> }, { h: "Version", r: (x) => x.version },
            { h: "Env", r: (x) => <StatusPill status={x.environment} dot={false} /> }, { h: "Replicas", r: (x) => `${x.ready_replicas}/${x.replicas}` },
            { h: "Health", r: (x) => <StatusPill status={x.health} /> }, { h: "Latency", r: (x) => (x.latency_ms != null ? `${x.latency_ms.toFixed(1)} ms` : "—") },
            { h: "Traffic", r: (x) => `${x.traffic_pct}%` }, { h: "Updated", r: (x) => timeAgo(x.updated_at) },
          ]} />
          <div className="mt-4 font-medium">Live prediction log</div>
          <div className="scroll-area mt-2 max-h-[220px] font-mono text-[11px]">
            {(logs.data ?? []).slice().reverse().map((l) => (
              <div key={l.id} className={l.is_error ? "text-[#F87171]" : "text-ink/80"}>
                {timeAgo(l.ts)} · r{l.replica} · {l.latency_ms.toFixed(1)}ms · {l.is_error ? l.error : JSON.stringify(l.prediction)} · {l.source}
              </div>
            ))}
          </div>
        </Panel>
        <Panel title={dep ? `${dep.name} ${dep.version ?? ""}` : "Deployment"} className="col-span-5" actions={dep && <StatusPill status={dep.status} />}>
          {dep && (
            <div className="space-y-3 text-xs">
              <div className="flex items-center gap-2"><span className="font-mono text-accent">{dep.endpoint}</span><CopyButton text={`${location.origin}${dep.endpoint}`} /></div>
              <div><ProgressBar value={dep.progress} /><div className="mt-1 text-muted">{dep.stage_label}</div></div>
              <KV label="Environment">{dep.environment}</KV>
              <KV label="Serving process CPU / RAM">{dep.resources.process_cpu}% / {dep.resources.process_ram_mb} MB</KV>
              <div className="flex items-center justify-between">
                <span>Autoscaling ({dep.min_replicas}-{dep.max_replicas}, target CPU {dep.target_cpu}%)</span>
                <Toggle checked={dep.autoscaling} onChange={(v) => act(() => api.patch(`/api/deployments/${dep.id}`, { autoscaling: v }), `Autoscaling ${v ? "on" : "off"}`)} />
              </div>
              <div className="flex flex-wrap gap-2">
                <button className="btn btn-ghost" onClick={() => act(() => api.post(`/api/deployments/${dep.id}/scale`, { replicas: dep.replicas + 1 }), "Scaled up")}>Scale +1</button>
                <button className="btn btn-ghost" onClick={() => act(() => api.post(`/api/deployments/${dep.id}/restart`), "Restarting")}>Restart</button>
                <button className="btn btn-ghost" onClick={() => act(() => api.post(`/api/deployments/${dep.id}/stop`), "Stopped")}>Stop</button>
                <button className="btn btn-danger" disabled={!dep.has_previous} onClick={() => act(() => api.post(`/api/deployments/${dep.id}/rollback`), "Rolling back")}><RotateCcw size={13} />Rollback</button>
              </div>
              <div className="font-medium">Try it</div>
              <textarea className="field h-[150px] w-full font-mono text-[11px]" value={input} onChange={(e) => setInput(e.target.value)} />
              <div className="flex flex-wrap gap-2">
                <button className="btn btn-primary" onClick={predict}>Predict</button>
                <button className="btn btn-ghost" onClick={() => act(() => api.post(`/api/deployments/${dep.id}/simulate?n=200`), "Sending 200 requests")}>Simulate traffic</button>
                <button className="btn btn-ghost" onClick={() => act(() => api.post(`/api/deployments/${dep.id}/simulate?n=300&drift=1&error_rate=0.05`), "Sending drifted traffic")}>Simulate drift</button>
              </div>
              {result && <pre className="field max-h-[180px] overflow-auto whitespace-pre-wrap font-mono text-[11px]">{result}</pre>}
            </div>
          )}
        </Panel>
      </div>
    </Page>
  );
}
