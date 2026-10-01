"""Deployments API and the public model-serving endpoint."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

import numpy as np
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, delete, select

from app.db import get_session
from app.models import Deployment, DeploymentEvent, ModelVersion, PredictionLog, RegisteredModel, SystemMetric, User
from app.services.activity import add_activity, get_actor
from app.services.deploy import deploy_version
from app.services.serving import health_of, load_bundle, serving
from app.services.system import system_monitor
from app.services.users import owner_brief, user_map
from app.utils import iso, pct_delta, percentile, utcnow

router = APIRouter(prefix="/api/deployments", tags=["deployments"])
serve_router = APIRouter(prefix="/serve", tags=["serving"])


def _window(session: Session, hours: int, end_offset_h: int = 0, dep_id: Optional[int] = None):
    end = utcnow() - timedelta(hours=end_offset_h)
    start = end - timedelta(hours=hours)
    q = select(PredictionLog.deployment_id, PredictionLog.ts, PredictionLog.latency_ms, PredictionLog.is_error).where(
        PredictionLog.ts >= start, PredictionLog.ts < end)
    if dep_id is not None:
        q = q.where(PredictionLog.deployment_id == dep_id)
    return session.exec(q).all(), start


def serialize(d: Deployment, session: Session, umap: dict, versions: dict[int, ModelVersion], models: dict[int, RegisteredModel],
              day_logs: dict[int, list], total_24h: int) -> dict[str, Any]:
    mv = versions.get(d.version_id)
    logs = day_logs.get(d.id, [])
    ok = [l for l in logs if not l[3]]
    now = utcnow()
    hourly = [0] * 24
    for l in logs:
        idx = 23 - int((now - l[1]).total_seconds() // 3600)
        if 0 <= idx < 24:
            hourly[idx] += 1
    runtime = serving.get(d.id)
    return {
        "id": d.id, "slug": d.slug, "name": d.name, "model_id": d.model_id, "model": models[d.model_id].name if d.model_id in models else "",
        "version_id": d.version_id, "version": mv.version if mv else None, "environment": d.environment, "status": d.status,
        "replicas": d.replicas, "ready_replicas": len(runtime.replicas) if runtime else 0,
        "min_replicas": d.min_replicas, "max_replicas": d.max_replicas, "target_cpu": d.target_cpu,
        "rpm_per_replica": d.rpm_per_replica, "autoscaling": d.autoscaling, "health": health_of(session, d, serving),
        "latency_ms": round(float(np.mean([l[2] for l in ok])), 2) if ok else None,
        "p95_ms": round(percentile([l[2] for l in ok], 95), 2) if ok else None,
        "requests_24h": len(logs), "errors_24h": len(logs) - len(ok),
        "traffic_pct": round(len(logs) / total_24h * 100, 1) if total_24h else 0.0,
        "sparkline": hourly, "progress": d.progress, "stage_label": d.stage_label, "last_error": d.last_error,
        "endpoint": f"/serve/{d.slug}/predict", "has_previous": d.previous_version_id is not None,
        "owner": owner_brief(umap, d.owner_id), "created_at": iso(d.created_at), "updated_at": iso(d.updated_at),
    }


def _context(session: Session):
    versions = {v.id: v for v in session.exec(select(ModelVersion)).all()}
    models = {m.id: m for m in session.exec(select(RegisteredModel)).all()}
    logs, _ = _window(session, 24)
    by_dep: dict[int, list] = {}
    for l in logs:
        by_dep.setdefault(l[0], []).append(l)
    return versions, models, by_dep, len(logs)


@router.get("")
def list_deployments(environment: str = "", q: str = "", session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    stmt = select(Deployment)
    if environment:
        stmt = stmt.where(Deployment.environment == environment)
    deps = session.exec(stmt.order_by(Deployment.updated_at.desc())).all()
    versions, models, by_dep, total = _context(session)
    umap = user_map(session)
    out = [serialize(d, session, umap, versions, models, by_dep, total) for d in deps]
    if q:
        ql = q.lower()
        out = [d for d in out if ql in d["name"].lower() or ql in (d["model"] or "").lower() or ql in d["slug"]]
    return out


@router.get("/stats")
def deployment_stats(session: Session = Depends(get_session)) -> dict[str, Any]:
    deps = session.exec(select(Deployment)).all()
    running = [d for d in deps if d.status == "Running"]
    week = utcnow() - timedelta(days=7)
    cur, _ = _window(session, 24)
    prev, _ = _window(session, 24, end_offset_h=24)
    lat_cur = [l[2] for l in cur if not l[3]]
    lat_prev = [l[2] for l in prev if not l[3]]
    avg_cur = float(np.mean(lat_cur)) if lat_cur else None
    avg_prev = float(np.mean(lat_prev)) if lat_prev else None
    return {
        "active": len(running), "delta_active": sum(1 for d in running if d.created_at >= week),
        "production": sum(1 for d in running if d.environment == "Production"),
        "delta_production": sum(1 for d in running if d.environment == "Production" and d.created_at >= week),
        "requests_24h": len(cur), "delta_requests_pct": pct_delta(len(cur), len(prev)),
        "avg_latency_ms": round(avg_cur, 2) if avg_cur is not None else None,
        "delta_latency_pct": pct_delta(avg_cur, avg_prev) if avg_cur is not None and avg_prev else None,
    }


@router.get("/timeseries")
def deployment_timeseries(hours: int = Query(24, ge=1, le=168), deployment_id: Optional[int] = None,
                          session: Session = Depends(get_session)) -> dict[str, Any]:
    logs, start = _window(session, hours, dep_id=deployment_id)
    bucket_min = 30 if hours <= 24 else 180
    n = hours * 60 // bucket_min
    counts = [0] * n
    lats: list[list[float]] = [[] for _ in range(n)]
    for l in logs:
        idx = int((l[1] - start).total_seconds() // (bucket_min * 60))
        if 0 <= idx < n:
            counts[idx] += 1
            if not l[3]:
                lats[idx].append(l[2])
    traffic = [{"ts": iso(start + timedelta(minutes=i * bucket_min)), "rpm": round(counts[i] / bucket_min, 2),
                "latency_ms": round(float(np.mean(lats[i])), 2) if lats[i] else None} for i in range(n)]
    # Health strip: one cell per hour per deployment.
    deps = session.exec(select(Deployment)).all()
    if deployment_id is not None:
        deps = [d for d in deps if d.id == deployment_id]
    hours_n = min(hours, 24)
    strip_start = utcnow() - timedelta(hours=hours_n)
    health = []
    for d in deps:
        cells = []
        dl = [l for l in logs if l[0] == d.id and l[1] >= strip_start]
        for h in range(hours_n * 2):  # 30-minute cells
            lo = strip_start + timedelta(minutes=30 * h)
            hi = lo + timedelta(minutes=30)
            bucket = [l for l in dl if lo <= l[1] < hi]
            if not bucket:
                cells.append("idle")
                continue
            err = sum(1 for l in bucket if l[3]) / len(bucket) * 100
            p95 = percentile([l[2] for l in bucket if not l[3]], 95)
            cells.append("down" if err > 20 else "degraded" if (err > 2 or p95 > 600) else "healthy")
        health.append({"deployment_id": d.id, "name": d.name, "cells": cells})
    sys_rows = session.exec(select(SystemMetric).where(SystemMetric.ts >= utcnow() - timedelta(hours=hours))).all()
    res_n = hours * 60 // bucket_min
    res: list[list[SystemMetric]] = [[] for _ in range(res_n)]
    for r in sys_rows:
        idx = int((r.ts - start).total_seconds() // (bucket_min * 60))
        if 0 <= idx < res_n:
            res[idx].append(r)
    resources = [{"ts": iso(start + timedelta(minutes=i * bucket_min)),
                  "cpu": round(float(np.mean([r.cpu for r in b])), 1) if b else None,
                  "ram": round(float(np.mean([r.ram for r in b])), 1) if b else None,
                  "gpu": round(float(np.mean([r.gpu for r in b])), 1) if b else None} for i, b in enumerate(res)]
    return {"bucket_minutes": bucket_min, "traffic": traffic, "health": health, "resources": resources}


class CreateDeployment(BaseModel):
    model_id: int
    version_id: int
    environment: str = "Staging"
    replicas: int = 1
    name: Optional[str] = None


@router.post("")
def create_deployment(body: CreateDeployment, session: Session = Depends(get_session),
                      actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    try:
        dep = deploy_version(session, body.model_id, body.version_id, body.environment, actor.id if actor else None,
                             name=body.name, replicas=body.replicas)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return get_deployment(dep.id, session)


def _get(session: Session, dep_id: int) -> Deployment:
    dep = session.get(Deployment, dep_id)
    if dep is None:
        raise HTTPException(404, "Deployment not found")
    return dep


@router.get("/{dep_id}")
def get_deployment(dep_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    dep = _get(session, dep_id)
    versions, models, by_dep, total = _context(session)
    out = serialize(dep, session, user_map(session), versions, models, by_dep, total)
    events = session.exec(select(DeploymentEvent).where(DeploymentEvent.deployment_id == dep_id)
                          .order_by(DeploymentEvent.ts.desc()).limit(20)).all()
    out["history"] = [{"id": e.id, "kind": e.kind, "version": e.version_label, "environment": e.environment,
                       "message": e.message, "ts": iso(e.ts)} for e in events]
    mv = versions.get(dep.version_id)
    sample, features, task, classes = None, [], None, []
    if mv and mv.artifact_path:
        try:
            bundle = load_bundle(mv)
            sample = (bundle.get("sample_inputs") or [None])[0]
            features, task, classes = bundle["features"], bundle["task"], bundle.get("classes") or []
        except Exception:  # noqa: BLE001
            pass
    prev = versions.get(dep.previous_version_id) if dep.previous_version_id else None
    sysd = system_monitor.latest
    out.update({
        "sample_input": sample, "features": features, "task": task, "classes": classes,
        "previous_version": prev.version if prev else None,
        "resources": {"process_cpu": sysd.get("process_cpu", 0.0), "process_ram_mb": sysd.get("process_ram_mb", 0.0),
                      "ram_total_gb": sysd.get("ram_total_gb", 0.0), "gpu": sysd.get("gpu", 0.0),
                      "cpu": sysd.get("cpu", 0.0), "ram": sysd.get("ram", 0.0)},
    })
    return out


class PatchDeployment(BaseModel):
    name: Optional[str] = None
    autoscaling: Optional[bool] = None
    min_replicas: Optional[int] = None
    max_replicas: Optional[int] = None
    target_cpu: Optional[int] = None
    rpm_per_replica: Optional[int] = None


@router.patch("/{dep_id}")
def patch_deployment(dep_id: int, body: PatchDeployment, session: Session = Depends(get_session),
                     actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    dep = _get(session, dep_id)
    mn = body.min_replicas if body.min_replicas is not None else dep.min_replicas
    mx = body.max_replicas if body.max_replicas is not None else dep.max_replicas
    if not 1 <= mn <= 16 or not 1 <= mx <= 16:
        raise HTTPException(400, "replica bounds must be between 1 and 16")
    if mn > mx:
        raise HTTPException(400, "min replicas cannot exceed max replicas")
    if body.target_cpu is not None and not 10 <= body.target_cpu <= 95:
        raise HTTPException(400, "target CPU must be between 10% and 95%")
    if body.rpm_per_replica is not None and not 1 <= body.rpm_per_replica <= 100000:
        raise HTTPException(400, "rpm_per_replica must be positive")
    if body.name is not None and body.name.strip():
        dep.name = body.name.strip()
    if body.autoscaling is not None:
        dep.autoscaling = body.autoscaling
    dep.min_replicas, dep.max_replicas = mn, mx
    if body.target_cpu is not None:
        dep.target_cpu = body.target_cpu
    if body.rpm_per_replica is not None:
        dep.rpm_per_replica = body.rpm_per_replica
    clamped = max(mn, min(mx, dep.replicas))
    if clamped != dep.replicas:
        dep.replicas = clamped
        serving.scale(dep.id, clamped)
    dep.updated_at = utcnow()
    session.add(dep)
    add_activity(session, actor.id if actor else None, "deployment", "config",
                 f"Updated autoscaling of {dep.name} ({'on' if dep.autoscaling else 'off'}, {mn}-{mx} replicas, target CPU {dep.target_cpu}%)",
                 f"/deployments?select={dep.id}")
    session.commit()
    return get_deployment(dep_id, session)


@router.delete("/{dep_id}")
def delete_deployment(dep_id: int, session: Session = Depends(get_session), actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    dep = _get(session, dep_id)
    serving.unload(dep_id)
    session.exec(delete(PredictionLog).where(PredictionLog.deployment_id == dep_id))
    session.exec(delete(DeploymentEvent).where(DeploymentEvent.deployment_id == dep_id))
    add_activity(session, actor.id if actor else None, "deployment", "deleted", f"Deleted deployment {dep.name} ({dep.environment})", "/deployments")
    session.delete(dep)
    session.commit()
    return {"deleted": True, "id": dep_id}


@router.post("/{dep_id}/rollback")
def rollback(dep_id: int, session: Session = Depends(get_session), actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    dep = _get(session, dep_id)
    if dep.previous_version_id is None:
        raise HTTPException(409, "No previous version to roll back to")
    if dep.status == "Deploying":
        raise HTTPException(409, "A rollout is already in progress")
    prev = session.get(ModelVersion, dep.previous_version_id)
    cur = session.get(ModelVersion, dep.version_id)
    if prev is None or not prev.artifact_path:
        raise HTTPException(400, "Previous version has no servable artifact")
    dep.previous_version_id, dep.version_id = dep.version_id, prev.id
    dep.status, dep.progress, dep.stage_label = "Deploying", 0, "Queued"
    dep.updated_at = utcnow()
    session.add(dep)
    session.commit()
    serving.rollout(dep.id, prev.id, "rollback", actor.id if actor else None,
                    f"Rolled back {dep.name} from {cur.version if cur else '?'} to {prev.version}")
    return get_deployment(dep_id, session)


@router.post("/{dep_id}/restart")
def restart(dep_id: int, session: Session = Depends(get_session), actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    dep = _get(session, dep_id)
    if dep.status == "Deploying":
        raise HTTPException(409, "A rollout is already in progress")
    serving.unload(dep_id)
    dep.status, dep.progress, dep.stage_label = "Deploying", 0, "Queued"
    dep.updated_at = utcnow()
    session.add(dep)
    session.commit()
    serving.rollout(dep.id, dep.version_id, "restart", actor.id if actor else None, f"Restarted {dep.name}")
    return get_deployment(dep_id, session)


@router.post("/{dep_id}/stop")
def stop(dep_id: int, session: Session = Depends(get_session), actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    dep = _get(session, dep_id)
    serving.unload(dep_id)
    dep.status, dep.progress, dep.stage_label = "Stopped", 0, "Stopped"
    dep.updated_at = utcnow()
    session.add(dep)
    session.add(DeploymentEvent(deployment_id=dep.id, kind="stop", environment=dep.environment, message=f"Stopped {dep.name}"))
    add_activity(session, actor.id if actor else None, "deployment", "stopped", f"Stopped {dep.name} ({dep.environment})",
                 f"/deployments?select={dep.id}")
    session.commit()
    return get_deployment(dep_id, session)


class ScaleBody(BaseModel):
    replicas: int


@router.post("/{dep_id}/scale")
def scale(dep_id: int, body: ScaleBody, session: Session = Depends(get_session), actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    dep = _get(session, dep_id)
    if not 1 <= body.replicas <= 16:
        raise HTTPException(400, "replicas must be between 1 and 16")
    old = dep.replicas
    dep.replicas = body.replicas
    dep.max_replicas = max(dep.max_replicas, body.replicas)
    dep.min_replicas = min(dep.min_replicas, body.replicas)
    dep.updated_at = utcnow()
    session.add(dep)
    session.add(DeploymentEvent(deployment_id=dep.id, kind="scale", environment=dep.environment,
                                message=f"Scaled {old} → {body.replicas} replicas"))
    add_activity(session, actor.id if actor else None, "deployment", "scaled", f"Scaled {dep.name} to {body.replicas} replicas",
                 f"/deployments?select={dep.id}")
    session.commit()
    serving.scale(dep.id, body.replicas)
    return get_deployment(dep_id, session)


@router.post("/{dep_id}/simulate")
def simulate(dep_id: int, n: int = Query(200, ge=1, le=5000), drift: float = Query(0.0, ge=0.0, le=3.0),
             error_rate: float = Query(0.0, ge=0.0, le=0.5), session: Session = Depends(get_session),
             actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    dep = _get(session, dep_id)
    if dep.status != "Running":
        raise HTTPException(409, f"{dep.name} is {dep.status}; start it before sending traffic")
    try:
        serving.simulate(dep_id, n, drift, error_rate)
    except (RuntimeError, FileNotFoundError) as exc:
        raise HTTPException(409, str(exc)) from exc
    desc = f"{n} requests" + (f", drift x{drift:g}" if drift else "") + (f", {error_rate:.0%} malformed" if error_rate else "")
    add_activity(session, actor.id if actor else None, "deployment", "simulate", f"Sent simulated traffic to {dep.name} ({desc})",
                 f"/deployments?select={dep.id}")
    session.commit()
    return {"started": True, "n": n, "drift": drift, "error_rate": error_rate}


@router.get("/{dep_id}/logs")
def logs(dep_id: int, limit: int = Query(100, ge=1, le=500), after_id: int = 0,
         session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    _get(session, dep_id)
    q = select(PredictionLog).where(PredictionLog.deployment_id == dep_id)
    if after_id:
        q = q.where(PredictionLog.id > after_id).order_by(PredictionLog.id.asc()).limit(limit)
        rows = session.exec(q).all()
    else:
        rows = list(reversed(session.exec(q.order_by(PredictionLog.id.desc()).limit(limit)).all()))
    return [{"id": r.id, "ts": iso(r.ts), "latency_ms": r.latency_ms, "input": r.input, "prediction": r.prediction,
             "is_error": r.is_error, "error": r.error, "replica": r.replica, "source": r.source} for r in rows]


# --------------------------------------------------------------------- serving
def _by_slug(session: Session, slug: str) -> Deployment:
    dep = session.exec(select(Deployment).where(Deployment.slug == slug)).first()
    if dep is None:
        raise HTTPException(404, f"No deployment named '{slug}'")
    return dep


@serve_router.get("/{slug}")
def serve_info(slug: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    dep = _by_slug(session, slug)
    mv = session.get(ModelVersion, dep.version_id)
    info: dict[str, Any] = {"deployment": dep.slug, "status": dep.status, "version": mv.version if mv else None}
    if mv and mv.artifact_path:
        bundle = load_bundle(mv)
        info.update({"features": bundle["features"], "task": bundle["task"], "classes": bundle.get("classes"),
                     "example": {"features": (bundle.get("sample_inputs") or [{}])[0]}})
    return info


@serve_router.post("/{slug}/predict")
def predict(slug: str, payload: Any = Body(...), session: Session = Depends(get_session)) -> dict[str, Any]:
    dep = _by_slug(session, slug)
    if dep.status != "Running" or serving.get(dep.id) is None:
        raise HTTPException(503, f"{dep.name} is {dep.status.lower()}; it is not serving requests")
    mv = session.get(ModelVersion, dep.version_id)
    model = session.get(RegisteredModel, dep.model_id)
    try:
        result = serving.predict(dep.id, payload, source="live")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"deployment": dep.slug, "model": model.name if model else dep.name, "version": mv.version if mv else None, **result}

