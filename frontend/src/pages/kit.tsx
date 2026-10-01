import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useRef } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/ui/blocks";
import { ErrorState, Panel, SkeletonRows, StatusPill } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { usePageIntro } from "@/lib/motion";

export function Page({ eyebrow, title, subtitle, children, right }: { eyebrow: string; title: string; subtitle: string; children: ReactNode; right?: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  usePageIntro(ref);
  return (
    <div ref={ref} className="space-y-5 pb-6">
      <PageHeader eyebrow={eyebrow} title={title} subtitle={subtitle} right={right} />
      {children}
    </div>
  );
}

export function useGet<T>(key: unknown[], path: string, refetch?: number) {
  return useQuery({ queryKey: key, queryFn: () => api.get<T>(path), refetchInterval: refetch });
}

export function useAct() {
  const qc = useQueryClient();
  return async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      toast.success(ok);
      qc.invalidateQueries();
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };
}

export type Col<T> = { h: string; r: (row: T) => ReactNode };

export function Table<T extends { id: number }>({ q, cols, onRow, selected }: { q: { data?: T[]; isLoading: boolean; error: unknown; refetch: () => void }; cols: Col<T>[]; onRow?: (r: T) => void; selected?: number | null }) {
  if (q.isLoading) return <SkeletonRows rows={6} />;
  if (q.error) return <ErrorState error={q.error} onRetry={q.refetch} />;
  return (
    <div className="scroll-area max-h-[460px]">
      <table className="w-full">
        <thead><tr>{cols.map((c) => <th key={c.h} className="th">{c.h}</th>)}</tr></thead>
        <tbody>
          {(q.data ?? []).map((r) => (
            <tr key={r.id} data-row onClick={() => onRow?.(r)} className={`table-row cursor-pointer ${selected === r.id ? "selected" : ""}`}>
              {cols.map((c) => <td key={c.h} className="td">{c.r(r)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export { Panel, StatusPill, timeAgo };
