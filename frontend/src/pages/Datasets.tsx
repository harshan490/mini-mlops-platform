import { useState } from "react";
import { useDropzone } from "react-dropzone";
import { Database, Upload, Trash2 } from "lucide-react";
import { StatCard } from "@/components/ui/blocks";
import { ProgressBar, PALETTE } from "@/components/ui/viz";
import { api, upload } from "@/lib/api";
import { formatBytes, formatNumber } from "@/lib/format";
import type { DatasetRow, DatasetStats, Preview } from "@/lib/types";
import { Page, Panel, StatusPill, Table, timeAgo, useAct, useGet } from "./kit";

export default function Datasets() {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<number | null>(null);
  const [pct, setPct] = useState<number | null>(null);
  const act = useAct();
  const stats = useGet<DatasetStats>(["ds-stats"], "/api/datasets/stats");
  const list = useGet<DatasetRow[]>(["ds", q], `/api/datasets?q=${encodeURIComponent(q)}`);
  const preview = useGet<Preview>(["ds-prev", sel], `/api/datasets/${sel}/preview`);
  const drop = useDropzone({
    multiple: false,
    accept: { "text/csv": [".csv"], "application/zip": [".zip"], "application/octet-stream": [".parquet"] },
    onDrop: (files) => {
      if (!files[0]) return;
      const fd = new FormData();
      fd.append("file", files[0]);
      setPct(0);
      act(() => upload("/api/datasets", fd, setPct), `Uploaded ${files[0].name}`).finally(() => setPct(null));
    },
  });
  const s = stats.data;
  return (
    <Page eyebrow="Datasets" title="Dataset Library" subtitle="Manage, version and explore your data assets.">
      <div className="grid grid-cols-3 gap-5">
        <StatCard icon={<Database size={20} />} color={PALETTE.blue} label="Total Datasets" value={s?.total_datasets} delta={s?.delta_datasets} />
        <StatCard icon={<Database size={20} />} color={PALETTE.cyan} label="Total Size (GB)" value={s ? s.total_size_bytes / 1e9 : null} decimals={1} />
        <StatCard icon={<Database size={20} />} color={PALETTE.violet} label="Total Versions" value={s?.total_versions} delta={s?.delta_versions} />
      </div>
      <div className="grid grid-cols-12 gap-5">
        <Panel title="Datasets" className="col-span-8" actions={<input className="field w-64 text-xs" placeholder="Search datasets, tags…" value={q} onChange={(e) => setQ(e.target.value)} />}>
          <div {...drop.getRootProps()} className={`mb-3 cursor-pointer rounded-xl border border-dashed p-3 text-center text-xs ${drop.isDragActive ? "border-accent bg-accent/10" : "border-line/30 text-muted"}`}>
            <input {...drop.getInputProps()} />
            <Upload size={14} className="mr-2 inline" />Drop a CSV / ZIP / Parquet here or click to upload (profiled + quality-scored)
            {pct !== null && <ProgressBar value={pct} className="mt-2" />}
          </div>
          <Table q={list} selected={sel} onRow={(r) => setSel(r.id)} cols={[
            { h: "Name", r: (d) => <span className="font-medium">{d.name}</span> },
            { h: "Type", r: (d) => d.type },
            { h: "Size", r: (d) => formatBytes(d.size_bytes) },
            { h: "Samples", r: (d) => formatNumber(d.samples) },
            { h: "Versions", r: (d) => `v${d.current_version}` },
            { h: "Quality", r: (d) => `${d.quality.toFixed(0)}%` },
            { h: "Status", r: (d) => <StatusPill status={d.status} /> },
            { h: "Owner", r: (d) => d.owner?.display_name ?? "—" },
            { h: "Updated", r: (d) => timeAgo(d.updated_at) },
            { h: "", r: (d) => <button className="icon-btn" onClick={(e) => { e.stopPropagation(); act(() => api.del(`/api/datasets/${d.id}`), `Deleted ${d.name}`); }}><Trash2 size={14} /></button> },
          ]} />
        </Panel>
        <Panel title="Preview" className="col-span-4">
          {!sel ? <p className="text-xs text-muted">Select a dataset.</p> : preview.data?.kind === "images" ? (
            <div className="grid grid-cols-2 gap-2">{preview.data.images.map((u) => <img key={u} src={u} className="rounded-lg" />)}</div>
          ) : preview.data?.kind === "table" ? (
            <div className="scroll-area max-h-[480px] text-[11px]"><table><thead><tr>{preview.data.columns.map((c) => <th key={c} className="th">{c}</th>)}</tr></thead>
              <tbody>{(() => { const t = preview.data; return t.rows.map((r, i) => <tr key={i}>{t.columns.map((c) => <td key={c} className="td">{String(r[c])}</td>)}</tr>); })()}</tbody></table></div>
          ) : <p className="text-xs text-muted">{preview.data?.note}</p>}
        </Panel>
      </div>
    </Page>
  );
}
