"""Health, host stats, platform status, global search, dashboard summary, /metrics."""
from __future__ import annotations

import shutil
import time
from datetime import timedelta
from typing import Any, Optional

import numpy as np
from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import text
from sqlmodel import Session, select

from app.config import APP_VERSION, STORAGE_DIR
from app.db import get_session
from app.models import Activity, Dataset, Deployment, Pipeline, PredictionLog, RegisteredModel, Run, SystemMetric, User
from app.services.pipeline_runner import pipeline_runner
from app.services.system import system_monitor
from app.services.trainer import trainer
from app.services.users import find_user, owner_brief, user_map
from app.utils import iso, utcnow

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health(session: Session = Depends(get_session)) -> dict[str, Any]:
    session.exec(text("SELECT 1"))
    return {"status": "ok", "version": APP_VERSION, "time": iso(utcnow()),
            "uptime_s": round(time.time() - system_monitor.started_at, 1)}


@router.get("/api/system/stats")
def system_stats() -> dict[str, Any]:
    return system_monitor.latest or system_monitor.sample()


@router.get("/api/system/history")
def system_history(hours: int = Query(24, ge=1, le=168), bucket_min: int = Query(30, ge=1, le=240),
                   session: Session = Depends(get_session)) -> dict[str, Any]:
    start = utcnow() - timedelta(hours=hours)
    rows = session.exec(select(SystemMetric).where(SystemMetric.ts >= start)).all()
    n = hours * 60 // bucket_min
    buckets: list[list[SystemMetric]] = [[] for _ in range(n)]
    for r in rows:
        idx = int((r.ts - start).total_seconds() // (bucket_min * 60))
        if 0 <= idx < n:
            buckets[idx].append(r)

    def avg(b, attr):
        return round(float(np.mean([getattr(r, attr) for r in b])), 1) if b else None

    return {"bucket_minutes": bucket_min, "points": [
        {"ts": iso(start + timedelta(minutes=i * bucket_min)), "cpu": avg(b, "cpu"), "ram": avg(b, "ram"), "gpu": avg(b, "gpu")}
        for i, b in enumerate(buckets)]}


@router.get("/api/system/status")
def platform_status(session: Session = Depends(get_session)) -> dict[str, Any]:
    t = time.perf_counter()
    try:
        session.exec(text("SELECT 1"))
        db_ok, db_ms = True, (time.perf_counter() - t) * 1000
    except Exception:  # noqa: BLE001
        db_ok, db_ms = False, None
    usage = shutil.disk_usage(STORAGE_DIR)
    probe = STORAGE_DIR / ".write_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        storage_ok = True
    except OSError:
        storage_ok = False
    active_jobs = len(trainer.active)
    workers_ok = not getattr(trainer.executor, "_shutdown", False)
    items = [
        {"key": "api", "label": "API", "ok": True, "status": "Healthy", "detail": f"v{APP_VERSION}"},
        {"key": "database", "label": "Database", "ok": db_ok, "status": "Healthy" if db_ok else "Down",
         "detail": f"SQLite {db_ms:.1f} ms" if db_ms is not None else "unreachable"},
        {"key": "workers", "label": "Workers", "ok": workers_ok, "status": "Running" if workers_ok else "Stopped",
         "detail": f"{active_jobs} active job{'s' if active_jobs != 1 else ''}"},
        {"key": "storage", "label": "Storage", "ok": storage_ok and usage.free > 1e9,
         "status": "Healthy" if storage_ok and usage.free > 1e9 else "Degraded",
         "detail": f"{usage.free / 1e9:.0f} GB free"},
    ]
    return {"all_ok": all(i["ok"] for i in items), "items": items, "scheduler": pipeline_runner.scheduler is not None}


@router.get("/api/search")
def search(q: str = Query("", max_length=100), session: Session = Depends(get_session)) -> dict[str, Any]:
    ql = q.strip().lower()
    if not ql:
        return {"query": q, "results": []}
    results: list[dict[str, Any]] = []

    def hit(*fields: Optional[str]) -> bool:
        return any(ql in (f or "").lower() for f in fields)

    for d in session.exec(select(Dataset)).all():
        if hit(d.name, d.description, d.dtype, " ".join(d.tags or [])):
            results.append({"type": "dataset", "id": d.id, "title": d.name, "subtitle": f"{d.dtype} dataset · {d.status}",
                            "link": f"/datasets?select={d.id}"})
    for r in session.exec(select(Run).where(Run.kind != "trial")).all():
        if hit(r.code, r.name, r.algorithm_label):
            acc = (r.metrics or {}).get("accuracy")
            results.append({"type": "experiment", "id": r.id, "title": f"{r.code} · {r.name}",
                            "subtitle": f"{r.algorithm_label} · {r.status}" + (f" · {acc:.3f}" if isinstance(acc, (int, float)) else ""),
                            "link": f"/experiments?select={r.id}"})
    for m in session.exec(select(RegisteredModel)).all():
        if hit(m.name, m.description, m.framework, " ".join(m.tags or [])):
            results.append({"type": "model", "id": m.id, "title": m.name, "subtitle": f"{m.framework} · {m.model_type}",
                            "link": f"/models?select={m.id}"})
    for d in session.exec(select(Deployment)).all():
        if hit(d.name, d.slug, d.environment):
            results.append({"type": "deployment", "id": d.id, "title": d.name, "subtitle": f"{d.environment} · {d.status} · /serve/{d.slug}/predict",
                            "link": f"/deployments?select={d.id}"})
    for p in session.exec(select(Pipeline)).all():
        if hit(p.name, p.description):
            results.append({"type": "pipeline", "id": p.id, "title": p.name, "subtitle": f"Pipeline {p.version}",
                            "link": f"/pipelines?select={p.id}"})
    for u in session.exec(select(User)).all():
        if hit(u.username, u.display_name, u.title):
            results.append({"type": "user", "id": u.id, "title": u.display_name, "subtitle": u.title or "Team member",
                            "link": f"/users/{u.username}"})
    order = {"user": 0, "deployment": 1, "model": 2, "experiment": 3, "dataset": 4, "pipeline": 5}
    results.sort(key=lambda r: (not r["title"].lower().startswith(ql), order.get(r["type"], 9)))
    return {"query": q, "results": results[:30]}


@router.get("/api/dashboard/summary")
def dashboard_summary(session: Session = Depends(get_session)) -> dict[str, Any]:
    week = utcnow() - timedelta(days=7)
    datasets = session.exec(select(Dataset)).all()
    runs = session.exec(select(Run).where(Run.kind != "trial")).all()
    models = session.exec(select(RegisteredModel)).all()
    deps = session.exec(select(Deployment)).all()
    running = [d for d in deps if d.status == "Running"]
    return {
        "datasets": len(datasets), "delta_datasets": sum(1 for d in datasets if d.created_at >= week),
        "experiments": len(runs), "delta_experiments": sum(1 for r in runs if r.created_at >= week),
        "models": len(models), "delta_models": sum(1 for m in models if m.created_at >= week),
        "deployments": len(running), "delta_deployments": sum(1 for d in running if d.created_at >= week),
    }


@router.get("/api/activity")
def activity(user: str = "", limit: int = Query(30, le=200), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    q = select(Activity)
    if user:
        u = find_user(session, user)
        q = q.where(Activity.user_id == (u.id if u else -1))
    rows = session.exec(q.order_by(Activity.ts.desc(), Activity.id.desc()).limit(limit)).all()
    umap = user_map(session)
    return [{"id": a.id, "ts": iso(a.ts), "kind": a.kind, "action": a.action, "message": a.message, "link": a.link,
             "user": owner_brief(umap, a.user_id)} for a in rows]


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
def prometheus_metrics(session: Session = Depends(get_session)) -> str:
    d = system_monitor.latest
    since = utcnow() - timedelta(minutes=5)
    rows = session.exec(select(PredictionLog.latency_ms, PredictionLog.is_error).where(PredictionLog.ts >= since)).all()
    total_runs = session.exec(select(Run.id)).all()
    lines = [
        "# HELP mlops_cpu_percent Host CPU utilisation", "# TYPE mlops_cpu_percent gauge", f"mlops_cpu_percent {d.get('cpu', 0)}",
        "# HELP mlops_ram_percent Host RAM utilisation", "# TYPE mlops_ram_percent gauge", f"mlops_ram_percent {d.get('ram', 0)}",
        "# HELP mlops_gpu_percent GPU utilisation", "# TYPE mlops_gpu_percent gauge", f"mlops_gpu_percent {d.get('gpu', 0)}",
        "# HELP mlops_predictions_5m Predictions in the last 5 minutes", "# TYPE mlops_predictions_5m gauge",
        f"mlops_predictions_5m {len(rows)}",
        "# HELP mlops_prediction_errors_5m Failed predictions in the last 5 minutes", "# TYPE mlops_prediction_errors_5m gauge",
        f"mlops_prediction_errors_5m {sum(1 for r in rows if r[1])}",
        "# HELP mlops_runs_total Experiment runs recorded", "# TYPE mlops_runs_total gauge", f"mlops_runs_total {len(total_runs)}",
        "# HELP mlops_training_active Active training jobs", "# TYPE mlops_training_active gauge", f"mlops_training_active {len(trainer.active)}",
    ]
    return "\n".join(lines) + "\n"
