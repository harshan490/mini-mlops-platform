import { useQuery } from "@tanstack/react-query";
import { lazy, useEffect } from "react";
import { Route, Routes } from "react-router-dom";
import { AppLayout } from "@/components/layout/AppLayout";
import { api } from "@/lib/api";
import type { Settings } from "@/lib/types";
import { applyAppearance, useUI } from "@/store/ui";

const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Datasets = lazy(() => import("@/pages/Datasets"));
const Experiments = lazy(() => import("@/pages/Experiments"));
const Models = lazy(() => import("@/pages/Models"));
const Deployments = lazy(() => import("@/pages/Deployments"));
const Pipelines = lazy(() => import("@/pages/Pipelines"));
const Monitoring = lazy(() => import("@/pages/Monitoring"));
const SettingsPage = lazy(() => import("@/pages/Settings"));
const UserProfile = lazy(() => import("@/pages/UserProfile"));
const NotFound = lazy(() => import("@/pages/NotFound"));
const Login = lazy(() => import("@/pages/Login"));

export default function App() {
  const { appearance, setAppearance, setNotifications, authRequired, setAuthRequired, token } = useUI();

  const status = useQuery({
    queryKey: ["auth-status", token],
    queryFn: () => api.get<{ require_auth: boolean; authenticated: boolean }>("/api/auth/status"),
    retry: 2,
  });
  useEffect(() => {
    if (status.data) setAuthRequired(status.data.require_auth && !status.data.authenticated);
  }, [status.data, setAuthRequired]);

  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.get<Settings>("/api/settings"),
    enabled: !authRequired,
  });
  useEffect(() => {
    if (!settings.data) return;
    setAppearance(settings.data.appearance);
    setNotifications(settings.data.notifications);
  }, [settings.data, setAppearance, setNotifications]);

  useEffect(() => {
    applyAppearance(appearance);
    if (appearance.theme !== "auto") return;
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => applyAppearance(appearance);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [appearance]);

  if (authRequired) return <Login />;

  return (
    <AppLayout
      render={(location) => (
        <Routes location={location}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/datasets" element={<Datasets />} />
          <Route path="/experiments" element={<Experiments />} />
          <Route path="/models" element={<Models />} />
          <Route path="/deployments" element={<Deployments />} />
          <Route path="/pipelines" element={<Pipelines />} />
          <Route path="/monitoring" element={<Monitoring />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/users/:username" element={<UserProfile />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      )}
    />
  );
}
