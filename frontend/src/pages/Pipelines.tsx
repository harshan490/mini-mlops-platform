import { useEffect, useMemo, useState } from "react";
import { Background, type Edge, type Node, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Play, Square } from "lucide-react";
import { api } from "@/lib/api";
import type { LogLine, NodeState, PipelineDetail, PipelineRow } from "@/lib/types";
import { useSocket } from "@/lib/ws";
import { Page, Panel, StatusPill, timeAgo, useAct, useGet } from "./kit";

export default function Pipelines() {
  const act = useAct();
  const list = useGet<PipelineRow[]>(["pipes"], "/api/pipelines", 5000);
  const [pid, setPid] = useState<number | null>(null);
  const id = pid ?? list.data?.[0]?.id ?? null;
  const p = useGet<PipelineDetail>(["pipe", id], `/api/pipelines/${id}`, 3000);
  const run = p.data?.runs[0];
  const [live, setLive] = useState<Record<string, NodeState>>({});
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [yaml, setYaml] = useState("");
  const [tab, setTab] = useState<"dag" | "yaml">("dag");
  useEffect(() => { if (p.data) setYaml(p.data.yaml); }, [p.data?.id, p.data?.version]); // eslint-disable-line react-hooks/exhaustive-deps
  useSocket<{ type: string; nodes?: Record<string, NodeState>; logs?: LogLine[]; node?: string } & LogLine & NodeState>(run ? `/ws/pipelines/${run.id}` : null, (m) => {
    if (m.type === "snapshot") { setLive(m.nodes ?? {}); setLogs(m.logs ?? []); }
    if (m.type === "node" && m.node) setLive((s) => ({ ...s, [m.node as string]: m }));
    if (m.type === "log") setLogs((l) => [...l.slice(-200), m]);
  });
  const states = { ...(run?.nodes ?? {}), ...live };
  const { nodes, edges } = useMemo(() => {
    const spec = p.data?.spec;
    if (!spec) return { nodes: [] as Node[], edges: [] as Edge[] };
    const depth: Record<string, number> = {};
    const d = (id: string): number => depth[id] ?? (depth[id] = Math.max(0, ...spec.nodes.find((n) => n.id === id)!.depends_on.map((x) => d(x) + 1)));
    spec.nodes.forEach((n) => d(n.id));
    const lanes: Record<number, number> = {};
    const nodes: Node[] = spec.nodes.map((n) => {
      const lane = (lanes[depth[n.id]] = (lanes[depth[n.id]] ?? -1) + 1);
      const st = states[n.id]?.status ?? "pending";
      return {
        id: n.id, position: { x: depth[n.id] * 190, y: 80 + lane * 110 - (spec.nodes.filter((m) => depth[m.id] === depth[n.id]).length - 1) * 55 },
        data: { label: <div className="text-left text-[11px]"><b>{n.name}</b><br /><StatusPill status={st} /> {states[n.id]?.duration_s ? `${states[n.id].duration_s}s` : ""}<br /><span className="text-muted">{states[n.id]?.message}</span></div> },
        style: { background: "rgba(15,22,50,0.85)", color: "#E6EBFF", border: `1px solid ${st === "running" ? "#3B82F6" : st === "success" ? "#10B981" : st === "failed" ? "#EF4444" : "rgba(90,130,255,.3)"}`, borderRadius: 12, width: 170 },
      };
    });
    const edges: Edge[] = spec.nodes.flatMap((n) => n.depends_on.map((s) => ({ id: `${s}-${n.id}`, source: s, target: n.id, animated: states[n.id]?.status === "running" })));
    return { nodes, edges };
  }, [p.data?.spec, JSON.stringify(states)]); // eslint-disable-line react-hooks/exhaustive-deps
  const running = run && (run.status === "Running" || run.status === "Queued");
  return (
    <Page eyebrow="Pipelines" title="Pipelines" subtitle="Build, automate and manage your ML workflows.">
      <div className="flex flex-wrap gap-3">
        <select className="field" value={id ?? ""} onChange={(e) => setPid(Number(e.target.value))}>{(list.data ?? []).map((x) => <option key={x.id} value={x.id}>{x.name} ({x.version})</option>)}</select>
        <button className="btn btn-primary" disabled={!id || !!running} onClick={() => act(() => api.post(`/api/pipelines/${id}/run`, {}), "Pipeline started")}><Play size={14} />Run Pipeline</button>
        {running && <button className="btn btn-danger" onClick={() => act(() => api.post(`/api/pipelines/runs/${run!.id}/stop`), "Stopping")}><Square size={13} />Stop</button>}
        <button className="btn btn-ghost" onClick={() => { const cron = prompt("Cron schedule (blank to clear), e.g. 0 * * * *", p.data?.schedule ?? ""); if (cron !== null) act(() => api.post(`/api/pipelines/${id}/schedule`, { cron }), "Schedule saved"); }}>Schedule{p.data?.schedule ? `: ${p.data.schedule}` : ""}</button>
        <button className={`btn ${tab === "dag" ? "btn-primary" : "btn-ghost"}`} onClick={() => setTab("dag")}>DAG View</button>
        <button className={`btn ${tab === "yaml" ? "btn-primary" : "btn-ghost"}`} onClick={() => setTab("yaml")}>YAML</button>
      </div>
      <div className="grid grid-cols-12 gap-5">
        <Panel title={run ? `Run #${run.number} · ${run.status}` : "DAG"} className="col-span-8 h-[440px]">
          {tab === "dag" ? (
            <ReactFlow nodes={nodes} edges={edges} fitView proOptions={{ hideAttribution: true }} nodesDraggable={false}><Background color="#334" gap={22} /></ReactFlow>
          ) : (
            <div className="flex h-full flex-col gap-2">
              <textarea className="field flex-1 font-mono text-[11px]" value={yaml} onChange={(e) => setYaml(e.target.value)} />
              <button className="btn btn-primary self-end" onClick={() => act(() => api.put(`/api/pipelines/${id}`, { yaml }), "YAML saved")}>Save YAML</button>
            </div>
          )}
        </Panel>
        <Panel title="Logs" className="col-span-4 h-[440px]">
          <div className="scroll-area h-full font-mono text-[11px]">{logs.map((l, i) => <div key={i} className={l.level === "ERROR" ? "text-[#F87171]" : ""}>{l.ts.slice(11, 19)} {l.node}: {l.message}</div>)}</div>
        </Panel>
      </div>
      <Panel title="Pipeline Runs">
        {(p.data?.runs ?? []).map((r) => (
          <div key={r.id} className="flex gap-4 border-t border-line/10 py-1.5 text-xs"><b>#{r.number}</b><span>{r.version}</span><span>{r.triggered_by}</span><StatusPill status={r.status} /><span>{r.duration_s}s</span><span className="text-muted">{timeAgo(r.started_at)}</span></div>
        ))}
      </Panel>
    </Page>
  );
}
