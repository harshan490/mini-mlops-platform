import { useQuery } from "@tanstack/react-query";
import { ArrowRight, ChevronRight, Sparkles } from "lucide-react";
import { lazy, Suspense, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Panel, Select, SkeletonRows, EmptyState, ErrorState, StatusDot, Skeleton } from "@/components/ui/primitives";
import { ChartTooltip, Legend, PALETTE, ProgressBar, RingGauge, SERIES, Sparkline } from "@/components/ui/viz";
import type { HeroCounts } from "@/components/three/DashboardScene";
import { api } from "@/lib/api";
import { formatDuration, timeAgo } from "@/lib/format";
import { CountUp, Eyebrow, useChartDraw, usePageIntro, useRowCascade } from "@/lib/motion";
import { useLiveSystem, useTeam } from "@/lib/queries";
import type { RunDetail, RunRow } from "@/lib/types";
import { useSocket } from "@/lib/ws";
import { useUI } from "@/store/ui";

const DashboardScene = lazy(() => import("@/components/three/DashboardScene"));

interface Live {
  epoch: number;
  total: number;
  progress: number;
  loss: number | null;
  acc: number | null;
  eta: number | null;
  status: string;
}

function ActivePipeline() {
  const navigate = useNavigate();
  const active = useQuery({ queryKey: ["experiments", "active"], queryFn: () => api.get<RunDetail | null>("/api/experiments/active"), refetchInterval: 4000 });
  const latest = useQuery({ queryKey: ["experiments", "latest"], queryFn: () => api.get<RunRow[]>("/api/experiments?limit=1"), enabled: active.data === null });
  const run: RunRow | undefined = active.data ?? latest.data?.[0];
  const [live, setLive] = useState<Live | null>(null);
  const liveId = active.data?.id ?? null;

  useSocket<Record<string, unknown>>(liveId ? `/ws/runs/${liveId}` : null, (m) => {
    if (m.type === "snapshot" || m.type === "epoch" || m.type === "progress") {
      setLive((prev) => ({
        epoch: Number(m.epoch ?? m.trial ?? prev?.epoch ?? 0),
        total: Number(m.total_epochs ?? m.trials ?? prev?.total ?? 0),
        progress: Number(m.progress ?? prev?.progress ?? 0),
        loss: (m.train_loss as number) ?? ((m.metrics as Record<string, number>)?.loss ?? prev?.loss ?? null),
        acc: (m.val_acc as number) ?? ((m.metrics as Record<string, number>)?.accuracy ?? prev?.acc ?? null),
        eta: (m.eta_s as number) ?? prev?.eta ?? null,
        status: String(m.status ?? prev?.status ?? "Training"),
      }));
    } else if (m.type === "status") {
      setLive((prev) => (prev ? { ...prev, status: String(m.status), progress: m.status === "Completed" ? 100 : prev.progress } : prev));
      active.refetch();
    }
  });

  const isLive = !!active.data && !!live;
  const progress = isLive ? live!.progress : run?.progress ?? 0;
  const epoch = isLive ? live!.epoch : run?.epoch ?? 0;
  const total = isLive ? live!.total : run?.total_epochs ?? 0;
  const loss = isLive ? live!.loss : run?.loss ?? null;
  const status = isLive ? live!.status : run?.status ?? "";

  return (
    <div
      data-intro="panel"
      className="glass glass-hover mt-7 w-full max-w-[460px] cursor-pointer px-6 py-5"
      onClick={() => navigate(run ? `/experiments?select=${run.id}` : "/experiments")}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-[16px] font-semibold">{active.data ? "Active Pipeline" : "Latest Run"}</h3>
        <ChevronRight size={16} className="text-muted" />
      </div>
      {active.isLoading ? (
        <Skeleton className="mt-4 h-20" />
      ) : !run ? (
        <EmptyState title="No runs yet" hint="Start a training run from Experiments." />
      ) : (
        <>
          <div className="mt-3 flex items-center gap-2.5 text-[15px]">
            <StatusDot status={status} label="" />
            <span className="font-medium">{run.code}</span>
            <span className="text-ink/80">{run.algorithm_label}</span>
            <span className="text-muted">•</span>
            <span className={status === "Training" ? "text-[#34D399]" : "text-ink/80"}>{status}</span>
          </div>
          <div className="mt-4 flex items-center gap-4">
            <ProgressBar value={progress} className="flex-1" />
            <span className="w-12 text-right text-[15px] tabular-nums">
              <CountUp value={progress} suffix="%" />
            </span>
          </div>
          <div className="mt-4 grid grid-cols-3 text-[12.5px]">
            <div>
              <div className="text-muted">{run.kind === "autotune" ? "Trial" : "Epoch"}</div>
              <div className="mt-0.5 text-[15px] tabular-nums">
                {epoch} / {total}
              </div>
            </div>
            <div>
              <div className="text-muted">Loss</div>
              <div className="mt-0.5 text-[15px] tabular-nums">
                <CountUp value={loss} decimals={3} />
              </div>
            </div>
            <div>
              <div className="text-muted">{active.data ? "ETA" : "Duration"}</div>
              <div className="mt-0.5 text-[15px] tabular-nums">
                {active.data ? (live?.eta != null ? formatDuration(live.eta) : "…") : formatDuration(run.duration_s)}
              </div>
            </div>
          </div>
          {!active.data && (
            <Link to="/experiments" onClick={(e) => e.stopPropagation()} className="mt-4 inline-flex items-center gap-1 text-[12px] text-accent hover:underline">
              Start a new run <ArrowRight size={12} />
            </Link>
          )}
        </>
      )}
    </div>
  );
}

function ModelPerformance() {
  const [metric, setMetric] = useState<"accuracy" | "loss" | "f1">("accuracy");
  const q = useQuery({
    queryKey: ["experiments", "performance", metric],
    queryFn: () => api.get<{ series: { label: string; run: string; points: { epoch: number; value: number }[] }[] }>(`/api/experiments/performance?metric=${metric}`),
  });
  const ref = useRef<HTMLDivElement>(null);
  const { data, labels } = useMemo(() => {
    const series = q.data?.series ?? [];
    const rows = new Map<number, Record<string, number>>();
    series.forEach((s) => {
      // Normalise each run to 0..100% of its training so curves are comparable.
      const n = s.points.length;
      s.points.forEach((p, i) => {
        const x = Math.round(((i + 1) / n) * 50);
        const row = rows.get(x) ?? { x };
        row[s.label] = p.value;
        rows.set(x, row);
      });
    });
    return { data: [...rows.values()].sort((a, b) => a.x - b.x), labels: series.map((s) => s.label) };
  }, [q.data]);
  useChartDraw(ref, data.length > 0, metric);
  return (
    <Panel
      title="Model Performance"
      className="col-span-12 h-[310px] lg:col-span-4"
      actions={<Select value={metric} onChange={setMetric} options={[{ value: "accuracy", label: "Accuracy" }, { value: "loss", label: "Loss" }, { value: "f1", label: "F1" }]} className="w-28" />}
    >
      {q.isLoading ? (
        <Skeleton className="h-full" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : data.length === 0 ? (
        <EmptyState title="No completed runs yet" />
      ) : (
        <div className="flex h-full flex-col">
          <div ref={ref} className="min-h-0 flex-1">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                <defs>
                  {labels.map((l, i) => (
                    <linearGradient key={l} id={`perf${i}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={SERIES[i]} stopOpacity={0.3} />
                      <stop offset="100%" stopColor={SERIES[i]} stopOpacity={0} />
                    </linearGradient>
                  ))}
                </defs>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="x" tickLine={false} axisLine={false} ticks={[0, 10, 20, 30, 40, 50]} />
                <YAxis tickLine={false} axisLine={false} domain={metric === "loss" ? ["auto", "auto"] : [0, 1]} tickFormatter={(v) => Number(v).toFixed(1)} />
                <Tooltip content={<ChartTooltip labelFormatter={(l) => `${Number(l) * 2}% of training`} />} />
                {labels.map((l, i) => (
                  <Area key={l} type="monotone" dataKey={l} name={l} stroke={SERIES[i]} strokeWidth={2} fill={`url(#perf${i})`} connectNulls dot={false}
                    activeDot={{ r: 4, strokeWidth: 0, fill: SERIES[i] }} isAnimationActive={false} />
                ))}
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <Legend items={labels.map((l, i) => ({ label: l, color: SERIES[i] }))} />
        </div>
      )}
    </Panel>
  );
}

function RecentExperiments() {
  const q = useQuery({ queryKey: ["experiments", "recent"], queryFn: () => api.get<RunRow[]>("/api/experiments?limit=5"), refetchInterval: 8000 });
  const ref = useRef<HTMLDivElement>(null);
  useRowCascade(ref, q.data?.length ?? 0);
  return (
    <Panel
      title="Recent Experiments"
      className="col-span-12 h-[310px] lg:col-span-4"
      actions={
        <Link to="/experiments" className="btn btn-ghost py-1.5 text-[12px]">
          View All <ArrowRight size={13} />
        </Link>
      }
    >
      {q.isLoading ? (
        <SkeletonRows rows={5} />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : (
        <div ref={ref} className="divide-y divide-line/10">
          {(q.data ?? []).map((r) => (
            <Link key={r.id} data-row to={`/experiments?select=${r.id}`} className="grid grid-cols-[18px_64px_1fr_56px_60px] items-center gap-2 py-[11px] text-[12.5px] hover:bg-accent/5">
              <StatusDot status={r.status} label="" />
              <span className="font-medium">{r.code}</span>
              <span className="truncate text-ink/80">{r.algorithm_label}</span>
              <span className="tabular-nums">{r.accuracy != null ? r.accuracy.toFixed(3) : "—"}</span>
              <span className="text-right text-muted">{timeAgo(r.created_at)}</span>
            </Link>
          ))}
        </div>
      )}
    </Panel>
  );
}

function SystemHealth() {
  const live = useLiveSystem();
  const [hours, setHours] = useState(24);
  const hist = useQuery({
    queryKey: ["system", "history", hours],
    queryFn: () => api.get<{ points: { cpu: number | null; ram: number | null; gpu: number | null }[] }>(`/api/system/history?hours=${hours}&bucket_min=${hours === 24 ? 60 : hours === 6 ? 15 : 5}`),
    refetchInterval: 30_000,
  });
  const fallback = useQuery({ queryKey: ["system", "stats"], queryFn: () => api.get<{ cpu: number; ram: number; gpu: number }>("/api/system/stats"), enabled: !live });
  const s = live ?? fallback.data;
  const pts = hist.data?.points ?? [];
  const items = [
    { label: "CPU", value: s?.cpu, color: PALETTE.blue, data: pts.map((p) => p.cpu) },
    { label: "RAM", value: s?.ram, color: PALETTE.violet, data: pts.map((p) => p.ram) },
    { label: "GPU", value: s?.gpu, color: "#2DD4BF", data: pts.map((p) => p.gpu) },
  ];
  return (
    <Panel
      title="System Health"
      className="col-span-12 h-[310px] lg:col-span-4"
      actions={<Select value={hours} onChange={setHours} options={[{ value: 24, label: "Last 24 hours" }, { value: 6, label: "Last 6 hours" }, { value: 1, label: "Last hour" }]} className="w-36" />}
    >
      <div className="grid h-full grid-cols-3 items-center gap-2">
        {items.map((it) => (
          <div key={it.label} className="flex flex-col items-center gap-3">
            <RingGauge value={it.value} label={it.label} color={it.color} size={112} />
            <div className="w-full overflow-hidden rounded-lg bg-gradient-to-b from-transparent to-bg0/30">
              <Sparkline data={it.data} color={it.color} width={128} height={46} className="w-full" />
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

export default function Dashboard() {
  const ref = useRef<HTMLDivElement>(null);
  usePageIntro(ref);
  const navigate = useNavigate();
  const setPaletteOpen = useUI((s) => s.setPaletteOpen);
  const user = useUI((s) => s.user);
  const { data: team } = useTeam();
  const me = team?.find((u) => u.username === user);
  const counts = useQuery({ queryKey: ["dashboard", "summary"], queryFn: () => api.get<HeroCounts>("/api/dashboard/summary"), refetchInterval: 15_000 });

  return (
    <div ref={ref} className="relative pb-2">
      <div className="relative grid min-h-[500px] grid-cols-12 gap-5">
        <section className="relative z-10 col-span-12 pl-[6%] pt-1 xl:col-span-5">
          <Eyebrow text="Welcome back" className="mb-1" />
          <h1 data-intro="title" className="hero-title pb-2 text-[clamp(48px,5vw,76px)]">
            {me?.display_name ?? " "}
          </h1>
          <p data-intro="subtitle" className="text-[clamp(16px,1.35vw,21px)] tracking-wide text-ink/90">
            Build.&nbsp;&nbsp;Train.&nbsp;&nbsp;Deploy.&nbsp;&nbsp;Monitor.
          </p>
          <p data-intro="subtitle" className="mt-1 text-[13.5px] tracking-[0.06em] text-muted">
            Your complete MLOps workspace in one place.
          </p>
          <button
            data-intro="subtitle"
            onClick={() => setPaletteOpen(true)}
            className="glass mt-7 flex w-full max-w-[380px] items-center gap-3 rounded-full px-5 py-3 text-left text-[13.5px] text-muted hover:border-accent/60"
          >
            <Sparkles size={18} className="text-accent" />
            <span className="flex-1">Ask or search anything...</span>
            <kbd className="hidden rounded border border-line/30 px-1.5 text-[10px] md:inline">Ctrl K</kbd>
            <span className="grid h-7 w-7 place-items-center rounded-full border border-line/30">
              <ArrowRight size={14} />
            </span>
          </button>
          <ActivePipeline />
        </section>
        <div className="pointer-events-none relative col-span-12 hidden xl:col-span-7 xl:block">
          <div data-intro="quote" className="quote absolute right-2 top-2 z-10">
            <div>&ldquo;Turn data</div>
            <div>into impact&rdquo;</div>
            <div className="ml-auto mt-3 h-px w-12 bg-ink/40" />
          </div>
          <div className="pointer-events-auto absolute -left-[6%] -top-[70px] bottom-[-10px] right-0">
            <Suspense fallback={null}>
              <DashboardScene counts={counts.data} onNavigate={navigate} />
            </Suspense>
          </div>
        </div>
      </div>
      <div className="mt-5 grid grid-cols-12 gap-5">
        <ModelPerformance />
        <RecentExperiments />
        <SystemHealth />
      </div>
    </div>
  );
}
