import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { useAlerts } from "@/lib/queries";
import type { AlertItem, Settings } from "@/lib/types";
import { useUI } from "@/store/ui";

function allowed(a: AlertItem, n: Settings["notifications"] | null): boolean {
  if (!n) return true;
  if (a.kind === "run_completed" || a.kind === "pipeline_success") return n.experiment_completion;
  if (a.kind === "run_failed" || a.kind === "pipeline_failed" || a.kind === "deploy_failed") return n.job_failures;
  return n.system_alerts;
}

/** Turns new alerts into toasts (+ browser notifications), gated by the Settings toggles. */
export function AlertWatcher() {
  const { data } = useAlerts(20);
  const lastSeen = useRef<number | null>(null);
  const notifications = useUI((s) => s.notifications);

  useEffect(() => {
    if (!data) return;
    if (lastSeen.current === null) {
      lastSeen.current = data.latest_id; // do not replay history on first load
      return;
    }
    const fresh = data.items.filter((a) => a.id > (lastSeen.current ?? 0)).sort((a, b) => a.id - b.id);
    lastSeen.current = Math.max(lastSeen.current, data.latest_id);
    for (const a of fresh) {
      if (!allowed(a, notifications)) continue;
      const fn = a.severity === "critical" ? toast.error : a.severity === "warning" ? toast.warning : a.severity === "success" ? toast.success : toast.info;
      fn(a.title, { description: a.message });
      if (notifications?.browser && typeof Notification !== "undefined" && Notification.permission === "granted") {
        try {
          new Notification(a.title, { body: a.message, icon: "/logo.svg" });
        } catch {
          /* some browsers only allow notifications from a service worker */
        }
      }
    }
  }, [data, notifications]);

  return null;
}
