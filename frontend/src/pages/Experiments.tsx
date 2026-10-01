import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { FlaskConical, Play, Square, Wand2 } from "lucide-react";
import { StatCard } from "@/components/ui/blocks";
import { KV, Select } from "@/components/ui/primitives";
import { ChartTooltip, PALETTE, ProgressBar } from "@/components/ui/viz";
import { api } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import type { Algorithms, DatasetRow, ExperimentStats, MetricPoint, RunDetail, RunRow } from "@/lib/types";
import { useSocket } from "@/lib/ws";
import { Page, Panel, StatusPill, Table, timeAgo, useAct, useGet } from "./kit";

export default function Experiments() {
  const [params, setParams] = useSearchParams();
  const sel = Number(params.get("select")) || null;
  const act = useAct();
  const stats = useGet<ExperimentStats>(["exp-stats"], "/api/experiments/stats", 5000);
  const runs = useGet<RunRow[]>(["runs"], "/api/experiments?limit=100", 3000);
  const algos = useGet<Algorithms>(["algos"], "/api/experiments/algorithms");
  const datasets = useGet<DatasetRow[]>(["ds", ""], "/api/datasets?q=");
  const runId = sel ?? runs.data?.[0]?.id ?? null;
  const detail = useGet<RunDetail>(["run", runId], `/api/experiments/${runId}`, 2000);
  const [hist, setHist] = useState<MetricPoint[]>([]);
  useSocket<{ type: string; history?: MetricPoint[] } & MetricPoint>(runId ? `/ws/runs/${runId}` : null, (m) => {
    if (m.type === "snapshot") setHist(m.history ?? []);
    if (m.type === "epoch") setHist((h) => [...h.filter((p) => p.epoch !== m.epoch), m]);
  });
  const [algo, setAlgo] = useState("xgboost");
  const [ds, setDs] = useState(4);
  const [lr, setLr] = useState(-1);
  const [batch, setBatch] = useState(32);
  const [epochs, setEpochs] = useState(60);
  const [opt, setOpt] = useState("Adam");
  const r = detail.data;
  const trainable = (datasets.data ?? []).filter((d) => d.trainable);
  const s = stats.data;
  const chart = [...hist].sort((a, b) => a.epoch - b.epoch);
  return (
    <Page eyebrow="Experiments" title="Experiments" subtitle="Train. Track. Compare. Deploy.">
      <div className="grid grid-cols-4 gap-5">
        <StatCard icon={<FlaskConical size={20} />} color={PALETTE.violet} label="Total Experiments" value={s?.total} delta={s?.delta_total} spark={s?.spark_total} />
        <StatCard icon={<FlaskConical size={20} />} color={PALETTE.emerald} label="Working Runs" value={s?.working} />
        <StatCard icon={<FlaskConical size={20} />} color={PALETTE.blue} label="Best Accuracy" value={s?.best_accuracy} decimals={3} spark={s?.spark_best} />
        <StatCard icon={<FlaskConical size={20} />} color={PALETTE.amber} label="GPU Hours" value={s?.gpu_hours} decimals={1} spark={s?.spark_gpu} />
      </div>
      <div className="grid grid-cols-12 gap-5">
        <Panel title="Training Run" className="col-span-6" actions={r && <><StatusPill status={r.status} /><span className="text-xs">{r.code}</span></>}>
          {r && (
            <>
              <div className="mb-2 text-sm">{r.name}</div>
              <div className="flex items-center gap-3"><ProgressBar value={r.progress} className="flex-1" /><span>{r.progress.toFixed(0)}%</span></div>
              <div className="mt-2 grid grid-cols-4 text-xs">
                <span>Epoch {r.epoch}/{r.total_epochs}</span><span>Elapsed {formatDuration(r.duration_s)}</span>
                <span>Loss {r.loss?.toFixed(3) ?? "—"}</span><span>Accuracy {r.accuracy?.toFixed(3) ?? "—"}</span>
              </div>
              <div className="mt-3 grid h-[220px] grid-cols-2 gap-3">
                {(["loss", "acc"] as const).map((k) => (
                  <ResponsiveContainer key={k}>
                    <LineChart data={chart}>
                      <CartesianGrid vertical={false} /><XAxis dataKey="epoch" /><YAxis width={34} /><Tooltip content={<ChartTooltip />} />
                      <Line dataKey={k === "loss" ? "train_loss" : "train_acc"} name={k === "loss" ? "Train loss" : "Train acc"} stroke={PALETTE.blue} dot={false} isAnimationActive={false} />
                      <Line dataKey={k === "loss" ? "val_loss" : "val_acc"} name={k === "loss" ? "Val loss" : "Val acc"} stroke={PALETTE.violet} dot={false} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                ))}
              </div>
              <div className="mt-3 flex gap-2">
                {(r.status === "Training" || r.status === "Queued") && (
                  <button className="btn btn-danger" onClick={() => act(() => api.post(`/api/experiments/${r.id}/stop`), "Stop requested")}><Square size={13} />Stop</button>
                )}
                {r.has_artifact && (
                  <button className="btn btn-ghost" onClick={() => { const name = prompt("Register as model name:", "Travel Recommender"); if (name) act(() => api.post("/api/models", { run_id: r.id, name }), `Registered ${name}`); }}>Register as Model</button>
                )}
                {r.status !== "Training" && r.status !== "Queued" && (
                  <button className="btn btn-ghost" onClick={() => act(() => api.del(`/api/experiments/${r.id}`), `Deleted ${r.code}`)}>Delete</button>
                )}
              </div>
            </>
          )}
        </Panel>
        <Panel title="Hyperparameters" className="col-span-3">
          <div className="space-y-2 text-xs">
            <Select value={algo} onChange={setAlgo} options={(algos.data?.algorithms ?? []).map((a) => ({ value: a.key, label: a.label }))} />
            <Select value={ds} onChange={setDs} options={trainable.map((d) => ({ value: d.id, label: d.name }))} />
            <label className="block">Learning rate {(10 ** lr).toExponential(0)}
              <input type="range" className="slider w-full" min={-6} max={-1} step={0.5} value={lr} onChange={(e) => setLr(+e.target.value)} /></label>
            <Select value={batch} onChange={setBatch} options={[8, 16, 32, 64, 128].map((b) => ({ value: b, label: `Batch size ${b}` }))} />
            <label className="block">Epochs {epochs}
              <input type="range" className="slider w-full" min={10} max={300} step={10} value={epochs} onChange={(e) => setEpochs(+e.target.value)} /></label>
            <Select value={opt} onChange={setOpt} options={["Adam", "SGD", "AdamW", "RMSprop"].map((o) => ({ value: o, label: o }))} />
            <button className="btn btn-primary w-full" onClick={() => act(async () => {
              const run = await api.post<RunRow>("/api/experiments", { dataset_id: ds, algorithm: algo, params: { learning_rate: 10 ** lr, batch_size: batch, epochs, optimizer: opt } });
              setParams({ select: String(run.id) });
            }, "Training started")}><Play size={14} />Start Training</button>
            <button className="btn btn-ghost w-full" onClick={() => act(async () => {
              const run = await api.post<RunRow>("/api/experiments/autotune", { dataset_id: ds, algorithm: algo, trials: 6 });
              setParams({ select: String(run.id) });
            }, "Auto-tune started (6 trials)")}><Wand2 size={14} />Auto Tune</button>
          </div>
        </Panel>
        <Panel title="Run Details" className="col-span-3">
          {r && (
            <>
              <KV label="Experiment ID">{r.code}</KV><KV label="Model">{r.algorithm_label}</KV><KV label="Dataset">{r.dataset}</KV>
              <KV label="Framework">{r.framework}</KV><KV label="Device">{r.device}</KV><KV label="Owner">{r.owner?.display_name}</KV>
              <KV label="Started">{timeAgo(r.started_at)}</KV><KV label="F1">{r.f1?.toFixed(3) ?? "—"}</KV>
              <KV label="Checkpoint" mono>{r.checkpoint_path ?? "—"}</KV>
              {r.error && <p className="text-xs text-[#F87171]">{r.error}</p>}
            </>
          )}
        </Panel>
      </div>
      <Panel title="All Experiments">
        <Table q={runs} selected={runId} onRow={(x) => setParams({ select: String(x.id) })} cols={[
          { h: "ID", r: (x) => x.code }, { h: "Name", r: (x) => x.name }, { h: "Algorithm", r: (x) => x.algorithm_label },
          { h: "Status", r: (x) => <StatusPill status={x.status} /> }, { h: "Accuracy", r: (x) => x.accuracy?.toFixed(3) ?? "—" },
          { h: "Loss", r: (x) => x.loss?.toFixed(3) ?? "—" }, { h: "Duration", r: (x) => formatDuration(x.duration_s) },
          { h: "Owner", r: (x) => x.owner?.display_name ?? "—" }, { h: "Started", r: (x) => timeAgo(x.created_at) },
        ]} />
      </Panel>
    </Page>
  );
}
