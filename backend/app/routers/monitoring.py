"""Monitoring: KPIs from prediction logs, time series, PSI drift, alerts."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.db import get_session
from app.models import Alert, Deployment, ModelVersion, PredictionLog, RegisteredModel, SystemMetric
from app.services.drift import THRESHOLD, deployment_drift, drift_series
from app.services.serving import health_of, serving
from app.services.system import system_monitor
from app.utils import iso, pct_delta, percentile, utcnow

router = APIRouter(tags=["monitoring"])


def _logs(session: Session, start, end, dep_id: Optional[int] = None):
    q = select(PredictionLog.deployment_id, PredictionLog.ts, PredictionLog.latency_ms, PredictionLog.is_error).where(
        PredictionLog.ts >= start, PredictionLog.ts < end)
    if dep_id is not None:
        q = q.where(PredictionLog.deployment_id == dep_id)
    return session.exec(q).all()


def _hourly(values_by_hour: list[list[float]], fn) -> list[Optional[float]]:
    return [round(fn(v), 3) if v else None for v in values_by_hour]


def _uptime(session: Session, start, end) -> float:
    """Share of 5-minute buckets in the window in which the backend recorded a system sample."""
    rows = session.exec(select(SystemMetric.ts).where(SystemMetric.ts >= start, SystemMetric.ts < end)).all()
    total = int((end - start).total_seconds() // 300)
    buckets = {int((ts - start).total_seconds() // 300) for ts in rows}
    return round(len(buckets) / total * 100, 2) if total else 0.0


@router.get("/api/monitoring/summary")
def summary(session: Session = Depends(get_session)) -> dict[str, Any]:
    now = utcnow()
    day, prev_day = now - timedelta(hours=24), now - timedelta(hours=48)
    cur = _logs(session, day, now)
    prev = _logs(session, prev_day, day)

    def kpis(rows):
        lat = [r[2] for r in rows if not r[3]]
        errors = sum(1 for r in rows if r[3])
        return {"requests": len(rows), "avg_latency": float(np.mean(lat)) if lat else None,
                "error_rate": (errors / len(rows) * 100) if rows else 0.0}

    k_cur, k_prev = kpis(cur), kpis(prev)
    hours: list[list] = [[] for _ in range(24)]
    for r in cur:
        idx = int((r[1] - day).total_seconds() // 3600)
        if 0 <= idx < 24:
            hours[idx].append(r)
    spark_requests = [len(h) for h in hours]
    spark_latency = _hourly([[r[2] for r in h if not r[3]] for h in hours], lambda v: float(np.mean(v)))
    spark_errors = [round(sum(1 for r in h if r[3]) / len(h) * 100, 3) if h else 0.0 for h in hours]

    versions = session.exec(select(ModelVersion)).all()
    prod_versions = [v for v in versions if v.stage == "Production"]
    week = now - timedelta(days=7)
    deps = session.exec(select(Deployment)).all()
    running = [d for d in deps if d.status == "Running"]
    drift_vals = []
    for d in running:
        dr = deployment_drift(session, d.id)
        if dr.get("available"):
            drift_vals.append(dr["data_drift"])
    series_drift = drift_series(session, [d.id for d in running], 24, 1)
    prev_drift_pts = [p["data_drift"] for p in series_drift[:12] if p["data_drift"] is not None]
    avg_drift = float(np.mean(drift_vals)) if drift_vals else None
    uptime = _uptime(session, day, now)
    uptime_prev = _uptime(session, prev_day, day)

    models = {m.id: m for m in session.exec(select(RegisteredModel)).all()}
    vmap = {v.id: v for v in versions}
    health_rows = []
    for d in deps:
        rows = [r for r in cur if r[0] == d.id]
        lat = [r[2] for r in rows if not r[3]]
        recent = [r for r in rows if r[1] >= now - timedelta(hours=1)]
        dr = deployment_drift(session, d.id) if d.status == "Running" else {}
        health_rows.append({
            "deployment_id": d.id, "name": d.name, "model": models[d.model_id].name if d.model_id in models else "",
            "version": vmap[d.version_id].version if d.version_id in vmap else "", "environment": d.environment,
            "status": health_of(session, d, serving), "req_per_min": round(len(recent) / 60, 2),
            "latency_ms": round(float(np.mean(lat)), 2) if lat else None,
            "error_rate": round(sum(1 for r in rows if r[3]) / len(rows) * 100, 2) if rows else 0.0,
            "drift": dr.get("data_drift") if dr.get("available") else None,
        })
    sysd = system_monitor.latest
    sys_rows = session.exec(select(SystemMetric).where(SystemMetric.ts >= day)).all()
    sys_hours: list[list[SystemMetric]] = [[] for _ in range(24)]
    for r in sys_rows:
        idx = int((r.ts - day).total_seconds() // 3600)
        if 0 <= idx < 24:
            sys_hours[idx].append(r)
    return {
        "production_models": len(prod_versions),
        "delta_production_models": sum(1 for v in prod_versions if v.created_at >= week),
        "total_requests": k_cur["requests"], "delta_requests_pct": pct_delta(k_cur["requests"], k_prev["requests"]),
        "avg_latency_ms": round(k_cur["avg_latency"], 2) if k_cur["avg_latency"] is not None else None,
        "delta_latency_pct": pct_delta(k_cur["avg_latency"], k_prev["avg_latency"]) if k_cur["avg_latency"] and k_prev["avg_latency"] else None,
        "error_rate_pct": round(k_cur["error_rate"], 3),
        "delta_error_pct": pct_delta(k_cur["error_rate"], k_prev["error_rate"]) if k_prev["error_rate"] else None,
        "avg_drift": round(avg_drift, 4) if avg_drift is not None else None,
        "delta_drift_pct": pct_delta(avg_drift, float(np.mean(prev_drift_pts))) if avg_drift is not None and prev_drift_pts else None,
        "uptime_pct": uptime, "delta_uptime": round(uptime - uptime_prev, 2),
        "spark": {
            "requests": spark_requests, "latency": spark_latency, "errors": spark_errors,
            "drift": [p["data_drift"] for p in series_drift],
            "models": [sum(1 for v in prod_versions if v.created_at <= day + timedelta(hours=i + 1)) for i in range(24)],
            "uptime": [100.0 if h else 0.0 for h in sys_hours],
        },
        "model_health": health_rows,
        "infrastructure": {
            **sysd,
            "spark_cpu": _hourly([[r.cpu for r in h] for h in sys_hours], lambda v: float(np.mean(v))),
            "spark_ram": _hourly([[r.ram for r in h] for h in sys_hours], lambda v: float(np.mean(v))),
            "spark_gpu": _hourly([[r.gpu for r in h] for h in sys_hours], lambda v: float(np.mean(v))),
        },
        "threshold": THRESHOLD,
    }


@router.get("/api/monitoring/timeseries")
def timeseries(hours: int = Query(24, ge=1, le=168), bucket_min: int = Query(5, ge=1, le=240),
               deployment_id: Optional[int] = None, session: Session = Depends(get_session)) -> dict[str, Any]:
    now = utcnow()
    start = now - timedelta(hours=hours)
    n = hours * 60 // bucket_min
    rows = _logs(session, start, now, deployment_id)
    counts = [0] * n
    errs = [0] * n
    lats: list[list[float]] = [[] for _ in range(n)]
    for r in rows:
        idx = int((r[1] - start).total_seconds() // (bucket_min * 60))
        if 0 <= idx < n:
            counts[idx] += 1
            if r[3]:
                errs[idx] += 1
            else:
                lats[idx].append(r[2])
    deps = [deployment_id] if deployment_id else [d.id for d in session.exec(select(Deployment)).all()]
    drift = drift_series(session, deps, hours, 1) if hours <= 48 else []
    points = []
    for i in range(n):
        t = start + timedelta(minutes=i * bucket_min)
        hour_idx = int((t - start).total_seconds() // 3600)
        dpt = drift[hour_idx] if hour_idx < len(drift) else {}
        points.append({
            "ts": iso(t), "requests": counts[i],
            "p95_ms": round(percentile(lats[i], 95), 2) if lats[i] else None,
            "error_rate": round(errs[i] / counts[i] * 100, 3) if counts[i] else None,
            "drift": dpt.get("data_drift"), "prediction_drift": dpt.get("prediction_drift"),
        })
    total = len(rows)
    all_lat = [r[2] for r in rows if not r[3]]
    return {"bucket_minutes": bucket_min, "points": points, "total_requests": total,
            "p95_ms": round(percentile(all_lat, 95), 2) if all_lat else None,
            "error_rate": round(sum(1 for r in rows if r[3]) / total * 100, 3) if total else 0.0}


@router.get("/api/monitoring/drift")
def drift(deployment_id: Optional[int] = None, session: Session = Depends(get_session)) -> dict[str, Any]:
    deps = session.exec(select(Deployment).where(Deployment.status == "Running")).all()
    if deployment_id is not None:
        deps = [d for d in deps if d.id == deployment_id]
        if not deps:
            raise HTTPException(404, "Running deployment not found")
    details = [deployment_drift(session, d.id) for d in deps]
    daily = drift_series(session, [d.id for d in deps], 24 * 7, 24)
    return {"threshold": THRESHOLD, "deployments": details, "daily": daily}


@router.get("/api/monitoring/alerts")
def alerts(category: str = "", unread: bool = False, limit: int = Query(50, le=200), after_id: int = 0,
           session: Session = Depends(get_session)) -> dict[str, Any]:
    q = select(Alert)
    if category:
        q = q.where(Alert.category.in_(category.split(",")))
    if unread:
        q = q.where(Alert.read == False)  # noqa: E712
    if after_id:
        q = q.where(Alert.id > after_id)
    rows = session.exec(q.order_by(Alert.id.desc()).limit(limit)).all()
    unread_count = len(session.exec(select(Alert.id).where(Alert.read == False)).all())  # noqa: E712
    latest = session.exec(select(Alert.id).order_by(Alert.id.desc())).first() or 0
    return {"unread": unread_count, "latest_id": latest, "items": [{
        "id": a.id, "ts": iso(a.ts), "severity": a.severity, "kind": a.kind, "category": a.category, "title": a.title,
        "message": a.message, "deployment_id": a.deployment_id, "read": a.read, "resolved": a.resolved} for a in rows]}


@router.post("/api/alerts/{alert_id}/read")
def mark_read(alert_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    a = session.get(Alert, alert_id)
    if a is None:
        raise HTTPException(404, "Alert not found")
    a.read = True
    session.add(a)
    session.commit()
    return {"id": alert_id, "read": True}


@router.post("/api/alerts/read-all")
def mark_all_read(session: Session = Depends(get_session)) -> dict[str, Any]:
    rows = session.exec(select(Alert).where(Alert.read == False)).all()  # noqa: E712
    for a in rows:
        a.read = True
        session.add(a)
    session.commit()
    return {"updated": len(rows)}
