import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "./api";
import type { AlertItem, Settings, SystemStats, TeamMember, UserStats } from "./types";
import { useSocket } from "./ws";

export function useTeam() {
  return useQuery({
    queryKey: ["users"],
    queryFn: () => api.get<(TeamMember & { stats: UserStats })[]>("/api/users"),
    staleTime: 30_000,
  });
}

export function useSettingsQuery() {
  return useQuery({ queryKey: ["settings"], queryFn: () => api.get<Settings>("/api/settings"), staleTime: 60_000 });
}

export function useAlerts(limit = 20) {
  return useQuery({
    queryKey: ["alerts", limit],
    queryFn: () => api.get<{ unread: number; latest_id: number; items: AlertItem[] }>(`/api/monitoring/alerts?limit=${limit}`),
    refetchInterval: 10_000,
  });
}

/** Live host metrics over /ws/system (pushed every 2 s). */
export function useLiveSystem() {
  const [stats, setStats] = useState<SystemStats | null>(null);
  useSocket<{ type: string } & SystemStats>("/ws/system", (msg) => {
    if (msg.type === "system") setStats(msg);
  });
  return stats;
}
