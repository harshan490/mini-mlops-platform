import { useQueryClient } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { lazy, Suspense, useRef, useState } from "react";
import { StaticBackdrop } from "@/components/three/CosmicBackground";
import { BACKGROUNDS } from "@/components/three/presets";
import { api, errorMessage } from "@/lib/api";
import { usePageIntro } from "@/lib/motion";
import { useUI } from "@/store/ui";

const CosmicBackground = lazy(() => import("@/components/three/CosmicBackground"));

export default function Login() {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { setToken, setAuthRequired, appearance } = useUI();
  const qc = useQueryClient();
  const ref = useRef<HTMLDivElement>(null);
  usePageIntro(ref);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<{ access_token: string }>("/api/auth/login", { username, password });
      setToken(res.access_token);
      setAuthRequired(false);
      qc.invalidateQueries();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0">
      <Suspense fallback={<StaticBackdrop preset={BACKGROUNDS[appearance.background] ?? BACKGROUNDS.cosmic} />}>
        <CosmicBackground preset={appearance.background} />
      </Suspense>
      <div ref={ref} className="relative z-10 grid h-full place-items-center px-4">
        <form onSubmit={submit} data-intro="panel" className="glass w-full max-w-[400px] space-y-4 p-7">
          <div className="flex items-center gap-3">
            <span className="grid h-11 w-11 place-items-center rounded-xl bg-accent/15 text-accent">
              <Lock size={20} />
            </span>
            <div>
              <div className="text-lg font-semibold">Mini MLOps</div>
              <div className="text-xs text-muted">Authentication is required for this workspace</div>
            </div>
          </div>
          <label className="block space-y-1.5 text-[12.5px]">
            <span className="text-muted">Username</span>
            <input className="field w-full" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
          </label>
          <label className="block space-y-1.5 text-[12.5px]">
            <span className="text-muted">Password</span>
            <input className="field w-full" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" autoFocus />
          </label>
          {error && <p className="text-xs text-[#F87171]">{error}</p>}
          <button className="btn btn-primary w-full py-2.5" disabled={busy || !password}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
          <p className="text-center text-[11px] text-muted">Local account. The default is admin / admin; change it in Settings → Security.</p>
        </form>
      </div>
    </div>
  );
}
