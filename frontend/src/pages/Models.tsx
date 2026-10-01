import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Box, Rocket } from "lucide-react";
import { StatCard } from "@/components/ui/blocks";
import { PALETTE } from "@/components/ui/viz";
import { api } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import type { DeploymentRow, ModelDetail, ModelRow, ModelStats } from "@/lib/types";
import { Page, Panel, StatusPill, Table, timeAgo, useAct, useGet } from "./kit";

export default function Models() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const act = useAct();
  const stats = useGet<ModelStats>(["m-stats"], "/api/models/stats");
  const list = useGet<ModelRow[]>(["models"], "/api/models");
  const id = Number(params.get("select")) || list.data?.[0]?.id || null;
  const d = useGet<ModelDetail>(["model", id], `/api/models/${id}`);
  const [env, setEnv] = useState("Production");
  const s = stats.data;
  const m = d.data;
  const newest = m?.version_list[0];
  return (
    <Page eyebrow="Model Management" title="Model Registry" subtitle="Track, version, and manage all your machine learning models.">
      <div className="grid grid-cols-4 gap-5">
        <StatCard icon={<Box size={20} />} color={PALETTE.blue} label="Registered Models" value={s?.registered} delta={s?.delta_registered} spark={s?.spark_registered} />
        <StatCard icon={<Rocket size={20} />} color={PALETTE.violet} label="Production Models" value={s?.production} spark={s?.spark_production} />
        <StatCard icon={<Box size={20} />} color={PALETTE.cyan} label="Model Versions" value={s?.versions} spark={s?.spark_versions} />
        <StatCard icon={<Box size={20} />} color={PALETTE.emerald} label="Average Accuracy" value={s?.avg_accuracy} decimals={3} />
      </div>
      <div className="grid grid-cols-12 gap-5">
        <Panel title="Model Registry" className="col-span-7">
          <Table q={list} selected={id} onRow={(x) => setParams({ select: String(x.id) })} cols={[
            { h: "Model Name", r: (x) => <span className="font-medium">{x.name}</span> }, { h: "Version", r: (x) => x.version },
            { h: "Framework", r: (x) => x.framework }, { h: "Accuracy", r: (x) => x.accuracy?.toFixed(3) ?? "—" },
            { h: "Size", r: (x) => formatBytes(x.size_bytes) }, { h: "Status", r: (x) => <StatusPill status={x.status} /> },
            { h: "Updated", r: (x) => timeAgo(x.updated_at) },
          ]} />
        </Panel>
        <Panel title={m?.name ?? "Model"} className="col-span-5" actions={m && <StatusPill status={m.status} />}>
          {m && (
            <div className="space-y-3 text-xs">
              <p className="text-muted">{m.description}</p>
              <div className="flex gap-2">
                <select className="field" value={env} onChange={(e) => setEnv(e.target.value)}>
                  {["Production", "Staging", "Development"].map((e) => <option key={e}>{e}</option>)}
                </select>
                <button className="btn btn-primary flex-1" disabled={!newest?.servable} title={m.servable ? "" : "Seeded history: no artifact"}
                  onClick={() => act(async () => {
                    const dep = await api.post<DeploymentRow>("/api/deployments", { model_id: m.id, version_id: newest!.id, environment: env });
                    navigate(`/deployments?select=${dep.id}`);
                  }, `Deploying ${m.name} ${newest!.version}`)}>
                  <Rocket size={14} />Deploy {newest?.version} to {env}
                </button>
              </div>
              <div className="font-medium">Version History</div>
              {m.version_list.map((v) => (
                <div key={v.id} className="flex items-center gap-2 border-t border-line/10 pt-2">
                  <span className="w-14 font-medium">{v.version}</span><StatusPill status={v.stage} />
                  <span>{v.accuracy?.toFixed(3) ?? "—"}</span><span className="text-muted">{v.run_code}</span>
                  <select className="field ml-auto py-0.5 text-[11px]" value={v.stage}
                    onChange={(e) => act(() => api.post(`/api/models/${m.id}/versions/${v.version}/stage`, { stage: e.target.value }), `${v.version} → ${e.target.value}`)}>
                    {["Development", "Staging", "Production", "Archived"].map((st) => <option key={st}>{st}</option>)}
                  </select>
                </div>
              ))}
              {m.deployments.length > 0 && <div className="text-muted">Deployed: {m.deployments.map((x) => `${x.environment} (${x.version})`).join(", ")}</div>}
            </div>
          )}
        </Panel>
      </div>
    </Page>
  );
}
