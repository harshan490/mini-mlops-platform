"""Model registry API."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.db import get_session
from app.models import Deployment, ModelVersion, RegisteredModel, Run, RunMetric, User
from app.services import registry, storage
from app.services.activity import add_activity, get_actor
from app.services.registry import STAGES, parse_version
from app.services.users import find_user, owner_brief, user_map
from app.utils import iso, utcnow

router = APIRouter(prefix="/api/models", tags=["models"])
STAGE_RANK = {"Production": 3, "Staging": 2, "Development": 1, "Archived": 0}


def _versions(session: Session, model_id: int) -> list[ModelVersion]:
    vs = session.exec(select(ModelVersion).where(ModelVersion.model_id == model_id)).all()
    return sorted(vs, key=lambda v: parse_version(v.version))


def _headline(versions: list[ModelVersion]) -> Optional[ModelVersion]:
    """The version a row represents: highest stage, then newest."""
    if not versions:
        return None
    return max(versions, key=lambda v: (STAGE_RANK.get(v.stage, 0), parse_version(v.version)))


def serialize_version(v: ModelVersion, run_codes: dict[int, str]) -> dict[str, Any]:
    return {
        "id": v.id, "version": v.version, "stage": v.stage, "accuracy": v.accuracy, "size_bytes": v.size_bytes,
        "run_id": v.run_id, "run_code": run_codes.get(v.run_id or -1), "servable": bool(v.artifact_path),
        "description": v.description, "metrics": v.metrics or {}, "created_at": iso(v.created_at),
    }


def serialize(m: RegisteredModel, versions: list[ModelVersion], umap: dict, run_codes: dict[int, str]) -> dict[str, Any]:
    head = _headline(versions)
    return {
        "id": m.id, "name": m.name, "description": m.description, "tags": m.tags or [], "framework": m.framework,
        "model_type": m.model_type, "version": head.version if head else None, "version_id": head.id if head else None,
        "accuracy": head.accuracy if head else None, "size_bytes": head.size_bytes if head else 0,
        "status": head.stage if head else "Development", "versions": len(versions),
        "servable": any(v.artifact_path for v in versions), "owner": owner_brief(umap, m.owner_id),
        "created_at": iso(m.created_at), "updated_at": iso(m.updated_at),
        "latest_version": versions[-1].version if versions else None,
    }


def _run_codes(session: Session) -> dict[int, str]:
    return {r.id: r.code for r in session.exec(select(Run)).all()}


@router.get("")
def list_models(q: str = "", framework: str = "", status: str = "", owner: str = "",
                session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    models = session.exec(select(RegisteredModel)).all()
    umap, codes = user_map(session), _run_codes(session)
    owner_id = None
    if owner:
        u = find_user(session, owner)
        owner_id = u.id if u else -1
    out = []
    for m in models:
        row = serialize(m, _versions(session, m.id), umap, codes)
        if q and q.lower() not in (m.name + " " + m.description + " " + " ".join(m.tags or [])).lower():
            continue
        if framework and m.framework != framework:
            continue
        if status and row["status"] != status:
            continue
        if owner_id is not None and m.owner_id != owner_id:
            continue
        out.append(row)
    out.sort(key=lambda r: r["updated_at"] or "", reverse=True)
    return out


@router.get("/stats")
def model_stats(session: Session = Depends(get_session)) -> dict[str, Any]:
    models = session.exec(select(RegisteredModel)).all()
    versions = session.exec(select(ModelVersion)).all()
    week = utcnow() - timedelta(days=7)
    prod = [v for v in versions if v.stage == "Production"]
    heads = [h for h in (_headline([v for v in versions if v.model_id == m.id]) for m in models) if h and h.accuracy is not None]
    heads_cls = [h for h in heads if (h.metrics or {}).get("task") != "regression"]
    avg = sum(h.accuracy for h in heads_cls) / len(heads_cls) if heads_cls else None
    old_heads = [h for h in heads_cls if h.created_at < week]
    avg_old = sum(h.accuracy for h in old_heads) / len(old_heads) if old_heads else None
    days = [(utcnow() - timedelta(days=13 - i)).date() for i in range(14)]

    def cumulative(items, date_of) -> list[int]:
        return [sum(1 for it in items if date_of(it) <= d) for d in days]

    return {
        "registered": len(models), "delta_registered": sum(1 for m in models if m.created_at >= week),
        "production": len(prod), "delta_production": sum(1 for v in prod if v.created_at >= week),
        "versions": len(versions), "delta_versions": sum(1 for v in versions if v.created_at >= week),
        "avg_accuracy": round(avg, 4) if avg is not None else None,
        "delta_avg_accuracy": round(avg - avg_old, 4) if avg is not None and avg_old is not None else None,
        "spark_registered": cumulative(models, lambda m: m.created_at.date()),
        "spark_production": cumulative(prod, lambda v: v.created_at.date()),
        "spark_versions": cumulative(versions, lambda v: v.created_at.date()),
    }


@router.get("/performance")
def performance(metric: str = "accuracy", session: Session = Depends(get_session)) -> dict[str, Any]:
    field = {"accuracy": "val_acc", "loss": "val_loss", "f1": "f1"}.get(metric)
    if field is None:
        raise HTTPException(400, "metric must be accuracy, loss or f1")
    series = []
    for m in session.exec(select(RegisteredModel)).all():
        head = _headline(_versions(session, m.id))
        if head is None or head.run_id is None:
            continue
        rows = session.exec(select(RunMetric).where(RunMetric.run_id == head.run_id).order_by(RunMetric.epoch)).all()
        pts = [{"epoch": r.epoch, "value": getattr(r, field)} for r in rows if getattr(r, field) is not None]
        if pts:
            series.append({"label": m.name, "version": head.version, "points": pts})
    series.sort(key=lambda s: -(s["points"][-1]["value"] or 0) if metric != "loss" else (s["points"][-1]["value"] or 0))
    return {"metric": metric, "series": series[:4]}


class RegisterBody(BaseModel):
    run_id: int
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)


@router.post("")
def register(body: RegisterBody, session: Session = Depends(get_session), actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    try:
        mv = registry.register_run(session, body.run_id, body.name, body.description, actor.id if actor else None, body.tags)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return get_model(mv.model_id, session)


@router.get("/{model_id}")
def get_model(model_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    m = session.get(RegisteredModel, model_id)
    if m is None:
        raise HTTPException(404, "Model not found")
    versions = _versions(session, m.id)
    codes = _run_codes(session)
    out = serialize(m, versions, user_map(session), codes)
    out["version_list"] = [serialize_version(v, codes) for v in reversed(versions)]
    deps = session.exec(select(Deployment).where(Deployment.model_id == m.id)).all()
    vmap = {v.id: v.version for v in versions}
    out["deployments"] = [{"id": d.id, "name": d.name, "slug": d.slug, "environment": d.environment, "status": d.status,
                           "version": vmap.get(d.version_id)} for d in deps]
    head = _headline(versions)
    history = []
    if head and head.run_id:
        rows = session.exec(select(RunMetric).where(RunMetric.run_id == head.run_id).order_by(RunMetric.epoch)).all()
        history = [{"epoch": r.epoch, "train_loss": r.train_loss, "val_loss": r.val_loss, "train_acc": r.train_acc,
                    "val_acc": r.val_acc, "f1": r.f1} for r in rows]
    out["history"] = history
    out["task"] = (head.metrics or {}).get("task") if head else None
    return out


class ModelPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None


@router.patch("/{model_id}")
def patch_model(model_id: int, body: ModelPatch, session: Session = Depends(get_session),
                actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    m = session.get(RegisteredModel, model_id)
    if m is None:
        raise HTTPException(404, "Model not found")
    if body.name is not None and body.name.strip() != m.name:
        new = body.name.strip()
        if not new:
            raise HTTPException(400, "Name cannot be empty")
        if session.exec(select(RegisteredModel).where(RegisteredModel.name == new)).first():
            raise HTTPException(409, "Another model already uses that name")
        add_activity(session, actor.id if actor else None, "model", "renamed", f"Renamed model {m.name} to {new}",
                     f"/models?select={m.id}")
        m.name = new
    if body.description is not None:
        m.description = body.description.strip()
    if body.tags is not None:
        m.tags = [t.strip().lower() for t in body.tags if t.strip()][:12]
    m.updated_at = utcnow()
    session.add(m)
    session.commit()
    return get_model(model_id, session)


class StageBody(BaseModel):
    stage: str


@router.post("/{model_id}/versions/{version}/stage")
def change_stage(model_id: int, version: str, body: StageBody, session: Session = Depends(get_session),
                 actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    if body.stage not in STAGES:
        raise HTTPException(400, f"stage must be one of {STAGES}")
    try:
        registry.set_stage(session, model_id, version, body.stage, actor.id if actor else None)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return get_model(model_id, session)


@router.get("/{model_id}/lineage")
def model_lineage(model_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return registry.lineage(session, model_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


def _version_dir(session: Session, model_id: int, version: Optional[str]) -> tuple[ModelVersion, Optional[Path]]:
    versions = _versions(session, model_id)
    if not versions:
        raise HTTPException(404, "Model has no versions")
    mv = next((v for v in versions if v.version == version), None) if version else _headline(versions)
    if mv is None:
        raise HTTPException(404, "Version not found")
    path = storage.resolve(mv.artifact_path)
    return mv, (path.parent if path is not None and path.exists() else None)


@router.get("/{model_id}/artifacts")
def list_artifacts(model_id: int, version: Optional[str] = None, session: Session = Depends(get_session)) -> dict[str, Any]:
    if session.get(RegisteredModel, model_id) is None:
        raise HTTPException(404, "Model not found")
    mv, folder = _version_dir(session, model_id, version)
    files = []
    if folder is not None:
        files = [{"name": f.name, "size_bytes": f.stat().st_size} for f in sorted(folder.iterdir()) if f.is_file()]
    return {"version": mv.version, "path": storage.display(storage.rel(folder)) if folder else None, "files": files,
            "note": None if folder else "Seeded history: no artifact files were produced on this machine."}


@router.get("/{model_id}/artifacts/{filename}")
def download_artifact(model_id: int, filename: str, version: Optional[str] = None,
                      session: Session = Depends(get_session)) -> FileResponse:
    mv, folder = _version_dir(session, model_id, version)
    if folder is None:
        raise HTTPException(404, "No artifacts for this version")
    path = folder / Path(filename).name
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(path, filename=f"{mv.version}_{path.name}")
