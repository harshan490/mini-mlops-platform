import { useEffect, useState } from "react";
import { BACKGROUNDS, previewGradient } from "@/components/three/presets";
import { Toggle } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import type { BackgroundPreset, Settings as S } from "@/lib/types";
import { useUI } from "@/store/ui";
import { Page, Panel, StatusPill, useAct, useGet } from "./kit";

const ACCENTS = ["#3B82F6", "#8B5CF6", "#EC4899", "#22D3EE", "#10B981", "#F59E0B"];

export default function Settings() {
  const act = useAct();
  const q = useGet<S>(["settings"], "/api/settings");
  const status = useGet<{ items: { key: string; label: string; status: string; detail: string }[] }>(["sys-status"], "/api/system/status", 10000);
  const keys = useGet<{ id: number; provider: string; masked: string }[]>(["keys"], "/api/apikeys");
  const [draft, setDraft] = useState<S | null>(null);
  const [tests, setTests] = useState<Record<string, string>>({});
  const setAppearance = useUI((s) => s.setAppearance);
  useEffect(() => { if (q.data) setDraft(q.data); }, [q.data]);
  if (!draft) return <Page eyebrow="Platform" title="Settings" subtitle="Loading…"><div /></Page>;
  const dirty = JSON.stringify(draft) !== JSON.stringify(q.data);
  const set = <K extends keyof S>(k: K, v: Partial<S[K]>) => {
    const next = { ...draft, [k]: { ...draft[k], ...v } };
    setDraft(next);
    if (k === "appearance") setAppearance(next.appearance);
  };
  return (
    <Page eyebrow="Platform" title="Settings" subtitle="Configure your workspace and platform preferences."
      right={<div className="glass flex gap-5 px-5 py-3 text-xs">{(status.data?.items ?? []).map((i) => <div key={i.key}><b>{i.label}</b><br /><StatusPill status={i.status} /></div>)}</div>}>
      <div className="grid grid-cols-3 gap-5">
        <Panel title="Workspace">
          {(["name", "description", "default_project", "storage_path"] as const).map((f) => (
            <label key={f} className="mb-2 block text-xs">{f.replace("_", " ")}<input className="field mt-1 w-full" value={draft.workspace[f]} onChange={(e) => set("workspace", { [f]: e.target.value })} /></label>
          ))}
        </Panel>
        <Panel title="Appearance">
          <div className="flex gap-2">{(["dark", "light", "auto"] as const).map((t) => <button key={t} className={`btn ${draft.appearance.theme === t ? "btn-primary" : "btn-ghost"}`} onClick={() => set("appearance", { theme: t })}>{t}</button>)}</div>
          <div className="mt-3 flex gap-3">{ACCENTS.map((c) => <button key={c} aria-label={c} onClick={() => set("appearance", { accent: c })} className={`h-7 w-7 rounded-full ${draft.appearance.accent === c ? "ring-2 ring-white" : ""}`} style={{ background: c }} />)}</div>
          <div className="mt-3 grid grid-cols-5 gap-2">{(Object.keys(BACKGROUNDS) as BackgroundPreset[]).map((b) => <button key={b} title={BACKGROUNDS[b].label} onClick={() => set("appearance", { background: b })} className={`h-12 rounded-lg ${draft.appearance.background === b ? "ring-2 ring-accent" : ""}`} style={{ background: previewGradient(BACKGROUNDS[b]) }} />)}</div>
        </Panel>
        <Panel title="Compute & Resources">
          <div className="mb-2 flex gap-2">{(["local", "docker", "aws", "gcp"] as const).map((t) => <button key={t} className={`btn ${draft.compute.target === t ? "btn-primary" : "btn-ghost"}`} onClick={() => set("compute", { target: t })}>{t}{t !== "local" && " (soon)"}</button>)}</div>
          {(["cpu_limit", "ram_limit", "gpu_limit"] as const).map((f) => <label key={f} className="mb-2 block text-xs">{f} <input type="number" className="field ml-2 w-20" value={draft.compute[f]} onChange={(e) => set("compute", { [f]: Number(e.target.value) })} /></label>)}
        </Panel>
        <Panel title="Notifications">
          {(Object.keys(draft.notifications) as (keyof S["notifications"])[]).map((k) => (
            <div key={k} className="mb-2 flex items-center justify-between text-xs">{k.replace("_", " ")}<Toggle checked={draft.notifications[k]} onChange={(v) => { set("notifications", { [k]: v }); if (k === "browser" && v && typeof Notification !== "undefined") Notification.requestPermission(); }} /></div>
          ))}
        </Panel>
        <Panel title="Security & Access">
          <div className="mb-2 flex items-center justify-between text-xs">Require authentication (admin/admin)<Toggle checked={draft.security.require_auth} onChange={(v) => set("security", { require_auth: v })} /></div>
          <div className="mb-2 flex items-center justify-between text-xs">Two-factor (planned)<Toggle checked={draft.security.two_factor} onChange={(v) => set("security", { two_factor: v })} /></div>
          <div className="mb-2 flex items-center justify-between text-xs">Team access (planned)<Toggle checked={draft.security.team_access} onChange={(v) => set("security", { team_access: v })} /></div>
          <select className="field text-xs" value={draft.security.session_timeout} onChange={(e) => set("security", { session_timeout: e.target.value as S["security"]["session_timeout"] })}>{["1h", "8h", "24h", "7d"].map((t) => <option key={t}>{t}</option>)}</select>
        </Panel>
        <Panel title="Integrations & API Keys">
          {(["mlflow", "postgres", "prometheus"] as const).map((n) => (
            <div key={n} className="mb-2 flex items-center gap-2 text-xs"><b className="w-20">{n}</b><span className="flex-1 truncate text-muted">{draft.integrations[n].url}</span>
              <span>{tests[n]}</span><button className="btn btn-ghost py-1" onClick={async () => { const r = await api.post<{ connected: boolean; detail: string }>(`/api/integrations/${n}/test`); setTests((t) => ({ ...t, [n]: r.connected ? "Connected" : `Disconnected (${r.detail})` })); }}>Test</button></div>
          ))}
          <div className="mt-3 border-t border-line/10 pt-2 text-xs">
            {(keys.data ?? []).map((k) => (
              <div key={k.id} className="flex items-center gap-2 py-1"><b className="w-24">{k.provider}</b><span className="flex-1 font-mono">{k.masked}</span>
                <button className="btn btn-ghost py-0.5" onClick={async () => { const r = await api.get<{ value: string }>(`/api/apikeys/${k.id}/reveal`); alert(r.value); }}>Reveal</button>
                <button className="btn btn-danger py-0.5" onClick={() => act(() => api.del(`/api/apikeys/${k.id}`), "Key deleted")}>Delete</button></div>
            ))}
            <button className="btn btn-ghost mt-2" onClick={() => { const v = prompt("API key value (stored encrypted)"); if (v) act(() => api.post("/api/apikeys", { provider: "Other", value: v }), "Key added"); }}>+ Add Key</button>
          </div>
        </Panel>
      </div>
      <div className="flex justify-end gap-3">
        <button className="btn btn-ghost" onClick={() => act(() => api.post("/api/settings/reset"), "Settings reset")}>Reset to Default</button>
        <button className="btn btn-ghost" disabled={!dirty} onClick={() => { setDraft(q.data!); setAppearance(q.data!.appearance); }}>Cancel</button>
        <button className="btn btn-primary" disabled={!dirty} onClick={() => act(() => api.put("/api/settings", draft), "Settings saved")}>Save Changes</button>
      </div>
    </Page>
  );
}
