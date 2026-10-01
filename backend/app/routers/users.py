"""Team members (Harshan, Abishek): profiles, contribution stats, activity."""
from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import Activity, Dataset, DatasetVersion, Deployment, ModelVersion, PipelineRun, RegisteredModel, Run, User
from app.utils import iso, utcnow

router = APIRouter(prefix="/api/users", tags=["users"])
KINDS = ["experiment", "dataset", "model", "deployment", "pipeline", "settings"]


def _brief(u: User) -> dict[str, Any]:
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "title": u.title, "role": u.role,
            "email": u.email, "bio": u.bio, "location": u.location, "accent": u.accent, "quote": u.quote,
            "joined_at": iso(u.joined_at)}


def _counts(session: Session, u: User) -> dict[str, Any]:
    runs = session.exec(select(Run).where(Run.owner_id == u.id, Run.kind != "trial")).all()
    completed = [r for r in runs if r.status == "Completed"]
    finished = [r for r in runs if r.status in ("Completed", "Failed", "Stopped")]
    cls_acc = [float(r.metrics["accuracy"]) for r in completed
               if r.task == "classification" and isinstance((r.metrics or {}).get("accuracy"), (int, float))]
    deps = session.exec(select(Deployment).where(Deployment.owner_id == u.id)).all()
    return {
        "datasets": len(session.exec(select(Dataset.id).where(Dataset.owner_id == u.id)).all()),
        "dataset_versions": len(session.exec(select(DatasetVersion.id).where(DatasetVersion.owner_id == u.id)).all()),
        "experiments": len(runs),
        "completed_runs": len(completed),
        "success_rate": round(len(completed) / len(finished) * 100, 1) if finished else None,
        "best_accuracy": round(max(cls_acc), 4) if cls_acc else None,
        "avg_accuracy": round(float(np.mean(cls_acc)), 4) if cls_acc else None,
        "models": len(session.exec(select(RegisteredModel.id).where(RegisteredModel.owner_id == u.id)).all()),
        "model_versions": len(session.exec(select(ModelVersion.id).where(ModelVersion.owner_id == u.id)).all()),
        "deployments": len(deps),
        "running_deployments": sum(1 for d in deps if d.status == "Running"),
        "pipeline_runs": len(session.exec(select(PipelineRun.id).where(PipelineRun.owner_id == u.id)).all()),
        "gpu_hours": round(sum(r.gpu_hours or 0 for r in session.exec(select(Run).where(Run.owner_id == u.id)).all()
                               if r.kind != "autotune"), 2),
        "training_hours": round(sum(r.duration_s or 0 for r in runs if r.kind != "autotune") / 3600, 2),
    }


def _get(session: Session, username: str) -> User:
    u = session.exec(select(User).where(User.username == username.strip().lower())).first()
    if u is None:
        raise HTTPException(404, f"No team member '{username}'")
    return u


@router.get("")
def list_users(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [{**_brief(u), "stats": _counts(session, u)} for u in session.exec(select(User).order_by(User.id)).all()]


@router.get("/{username}")
def get_user(username: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    u = _get(session, username)
    now = utcnow()
    start = (now - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
    acts = session.exec(select(Activity).where(Activity.user_id == u.id).order_by(Activity.ts.desc())).all()
    days = [(start + timedelta(days=i)).date() for i in range(30)]
    series = {d: {k: 0 for k in KINDS} for d in days}
    for a in acts:
        d = a.ts.date()
        if d in series and a.kind in series[d]:
            series[d][a.kind] += 1
    mix = {k: 0 for k in KINDS}
    for a in acts:
        if a.kind in mix:
            mix[a.kind] += 1

    runs = session.exec(select(Run).where(Run.owner_id == u.id, Run.kind != "trial").order_by(Run.created_at.desc())).all()
    ds_names = {d.id: d.name for d in session.exec(select(Dataset)).all()}
    algo: dict[str, int] = {}
    for r in runs:
        algo[r.algorithm_label] = algo.get(r.algorithm_label, 0) + 1
    models = session.exec(select(RegisteredModel).where(RegisteredModel.owner_id == u.id)).all()
    all_versions = session.exec(select(ModelVersion)).all()
    rank = {"Production": 3, "Staging": 2, "Development": 1, "Archived": 0}
    model_rows = []
    for m in models:
        vs = [v for v in all_versions if v.model_id == m.id]
        if vs:
            head = max(vs, key=lambda v: (rank.get(v.stage, 0), tuple(int(x) for x in re.findall(r"\d+", v.version))))
            model_rows.append({"id": m.id, "name": m.name, "version": head.version, "stage": head.stage,
                               "accuracy": head.accuracy, "framework": m.framework, "versions": len(vs)})
    vmap = {v.id: v.version for v in all_versions}
    deps = session.exec(select(Deployment).where(Deployment.owner_id == u.id)).all()
    datasets = session.exec(select(Dataset).where(Dataset.owner_id == u.id).order_by(Dataset.updated_at.desc())).all()
    dv_all = session.exec(select(DatasetVersion)).all()
    team = []
    for other in session.exec(select(User).order_by(User.id)).all():
        c = _counts(session, other)
        team.append({"username": other.username, "display_name": other.display_name, "accent": other.accent,
                     "experiments": c["experiments"], "models": c["models"], "datasets": c["datasets"],
                     "deployments": c["deployments"], "avg_accuracy": c["avg_accuracy"]})
    return {
        **_brief(u),
        "stats": _counts(session, u),
        "activity_series": [{"date": d.isoformat(), **series[d], "total": sum(series[d].values())} for d in days],
        "contribution": [{"kind": k, "count": v} for k, v in mix.items() if v],
        "algorithms": [{"algorithm": k, "runs": v} for k, v in sorted(algo.items(), key=lambda kv: -kv[1])],
        "recent_runs": [{"id": r.id, "code": r.code, "name": r.name, "algorithm": r.algorithm_label, "status": r.status,
                         "accuracy": (r.metrics or {}).get("accuracy"), "task": r.task, "dataset": ds_names.get(r.dataset_id or -1),
                         "created_at": iso(r.created_at)} for r in runs[:8]],
        "models": model_rows,
        "deployments": [{"id": d.id, "name": d.name, "environment": d.environment, "status": d.status,
                         "version": vmap.get(d.version_id), "slug": d.slug} for d in deps],
        "datasets": [{"id": d.id, "name": d.name, "type": d.dtype, "status": d.status,
                      "size_bytes": next((v.size_bytes for v in dv_all if v.dataset_id == d.id and v.version == d.current_version), 0),
                      "updated_at": iso(d.updated_at)} for d in datasets[:8]],
        "feed": [{"id": a.id, "ts": iso(a.ts), "kind": a.kind, "action": a.action, "message": a.message, "link": a.link}
                 for a in acts[:25]],
        "team": team,
        "last_active": iso(acts[0].ts) if acts else None,
    }


class UserPatch(BaseModel):
    display_name: Optional[str] = None
    title: Optional[str] = None
    email: Optional[str] = None
    bio: Optional[str] = None
    location: Optional[str] = None
    quote: Optional[str] = None
    accent: Optional[str] = None


@router.patch("/{username}")
def patch_user(username: str, body: UserPatch, session: Session = Depends(get_session)) -> dict[str, Any]:
    u = _get(session, username)
    if body.display_name is not None:
        if not body.display_name.strip():
            raise HTTPException(400, "Display name cannot be empty")
        u.display_name = body.display_name.strip()[:40]
    if body.email is not None:
        email = body.email.strip()
        if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise HTTPException(400, "Email address looks invalid")
        u.email = email
    if body.accent is not None:
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", body.accent):
            raise HTTPException(400, "accent must be #RRGGBB")
        u.accent = body.accent
    for field in ("title", "bio", "location", "quote"):
        value = getattr(body, field)
        if value is not None:
            setattr(u, field, value.strip()[:280])
    session.add(u)
    session.add(Activity(user_id=u.id, kind="settings", action="profile", message=f"{u.display_name} updated their profile",
                         link=f"/users/{u.username}", ts=utcnow()))
    session.commit()
    return get_user(u.username, session)
