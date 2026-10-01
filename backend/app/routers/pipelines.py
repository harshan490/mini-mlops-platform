"""Pipelines API: YAML specs, versions, runs, schedules, node control."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import Dataset, Pipeline, PipelineLog, PipelineRun, PipelineVersion, User
from app.services.activity import add_activity, get_actor
from app.services.pipeline_runner import PipelineSpecError, dump_spec, parse_spec, pipeline_runner, validate_cron
from app.services.registry import parse_version
from app.services.users import owner_brief, user_map
from app.utils import iso, utcnow

router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])


def default_yaml(name: str, dataset: str, model_name: str, version: str = "v1.0.0") -> str:
    spec = {
        "name": name,
        "version": version,
        "dataset": dataset,
        "nodes": [
            {"id": "validate", "name": "Data Validation", "type": "validate", "params": {"min_rows": 50, "max_missing_pct": 20}},
            {"id": "preprocess", "name": "Preprocessing", "type": "preprocess", "depends_on": ["validate"],
             "params": {"drop_duplicates": True, "clip_outliers": True}},
            {"id": "features", "name": "Feature Engineering", "type": "features", "depends_on": ["preprocess"],
             "params": {"ratio_features": False}},
            {"id": "train_xgb", "name": "Train (XGBoost)", "type": "train", "depends_on": ["features"],
             "params": {"algorithm": "xgboost", "epochs": 40, "learning_rate": 0.1, "batch_size": 32, "max_depth": 6}},
            {"id": "train_dl", "name": "Train (Deep Learning)", "type": "train", "depends_on": ["features"],
             "params": {"algorithm": "mlp", "epochs": 40, "learning_rate": 0.001, "batch_size": 32, "optimizer": "Adam"}},
            {"id": "evaluate", "name": "Evaluate", "type": "evaluate", "depends_on": ["train_xgb", "train_dl"],
             "params": {"metric": "accuracy", "min_accuracy": 0.6}},
            {"id": "register", "name": "Register", "type": "register", "depends_on": ["evaluate"],
             "params": {"model_name": model_name}},
            {"id": "deploy", "name": "Deploy", "type": "deploy", "depends_on": ["register"], "params": {"environment": "Staging"}},
        ],
    }
    return dump_spec(spec)


def _last_run(session: Session, pipeline_id: int) -> Optional[PipelineRun]:
    return session.exec(select(PipelineRun).where(PipelineRun.pipeline_id == pipeline_id)
                        .order_by(PipelineRun.number.desc())).first()


def serialize_run(r: PipelineRun, umap: dict) -> dict[str, Any]:
    return {"id": r.id, "number": r.number, "version": r.version, "triggered_by": r.triggered_by, "status": r.status,
            "nodes": r.nodes, "started_at": iso(r.started_at), "finished_at": iso(r.finished_at),
            "duration_s": r.duration_s, "owner": owner_brief(umap, r.owner_id), "source": r.source}


def serialize(p: Pipeline, session: Session, umap: dict, detail: bool = False) -> dict[str, Any]:
    last = _last_run(session, p.id)
    try:
        spec = parse_spec(p.yaml)
        spec_error = None
    except PipelineSpecError as exc:
        spec, spec_error = None, str(exc)
    out: dict[str, Any] = {
        "id": p.id, "name": p.name, "description": p.description, "version": p.version, "active": p.active,
        "schedule": p.schedule, "next_run": pipeline_runner.next_run_time(p.id), "owner": owner_brief(umap, p.owner_id),
        "dataset": spec["dataset"] if spec else None, "node_count": len(spec["nodes"]) if spec else 0,
        "last_run": serialize_run(last, umap) if last else None, "updated_at": iso(p.updated_at),
    }
    if detail:
        versions = session.exec(select(PipelineVersion).where(PipelineVersion.pipeline_id == p.id)).all()
        runs = session.exec(select(PipelineRun).where(PipelineRun.pipeline_id == p.id)
                            .order_by(PipelineRun.number.desc()).limit(12)).all()
        out.update({
            "yaml": p.yaml, "spec": spec, "spec_error": spec_error,
            "versions": sorted({v.version for v in versions} | {p.version}, key=parse_version, reverse=True),
            "runs": [serialize_run(r, umap) for r in runs],
        })
    return out


@router.get("")
def list_pipelines(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    umap = user_map(session)
    return [serialize(p, session, umap) for p in session.exec(select(Pipeline).order_by(Pipeline.id)).all()]


class CreatePipeline(BaseModel):
    name: str
    dataset: str
    model_name: Optional[str] = None
    yaml: Optional[str] = None
    description: str = ""


@router.post("")
def create_pipeline(body: CreatePipeline, session: Session = Depends(get_session), actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Name is required")
    if session.exec(select(Pipeline).where(Pipeline.name == name)).first():
        raise HTTPException(409, "A pipeline with that name exists")
    if session.exec(select(Dataset).where(Dataset.name == body.dataset)).first() is None:
        raise HTTPException(404, f"Dataset '{body.dataset}' not found")
    text = body.yaml or default_yaml(name, body.dataset, body.model_name or f"{name} Model")
    try:
        spec = parse_spec(text)
    except PipelineSpecError as exc:
        raise HTTPException(400, str(exc)) from exc
    if spec["name"] != name:
        spec["name"] = name
        text = dump_spec(spec)
    p = Pipeline(name=name, description=body.description, version=spec["version"], yaml=text, active=True,
                 owner_id=actor.id if actor else None)
    session.add(p)
    session.commit()
    session.refresh(p)
    session.add(PipelineVersion(pipeline_id=p.id, version=p.version, yaml=text))
    add_activity(session, p.owner_id, "pipeline", "created", f"Created pipeline {name}", f"/pipelines?select={p.id}")
    session.commit()
    return serialize(p, session, user_map(session), detail=True)


@router.get("/runs/{run_id}")
def get_run(run_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    r = session.get(PipelineRun, run_id)
    if r is None:
        raise HTTPException(404, "Pipeline run not found")
    logs = session.exec(select(PipelineLog).where(PipelineLog.run_id == run_id).order_by(PipelineLog.id)).all()
    out = serialize_run(r, user_map(session))
    out["pipeline_id"] = r.pipeline_id
    out["yaml"] = r.yaml_snapshot
    out["logs"] = [{"id": l.id, "ts": iso(l.ts), "level": l.level, "node": l.node, "message": l.message} for l in logs[-400:]]
    return out


@router.post("/runs/{run_id}/stop")
def stop_run(run_id: int, session: Session = Depends(get_session), actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    r = session.get(PipelineRun, run_id)
    if r is None:
        raise HTTPException(404, "Pipeline run not found")
    if r.status not in ("Queued", "Running") or not pipeline_runner.stop(run_id):
        raise HTTPException(409, f"Run #{r.number} is {r.status}")
    add_activity(session, actor.id if actor else None, "pipeline", "stop", f"Stopped pipeline run #{r.number}", f"/pipelines?run={run_id}")
    session.commit()
    return {"stopping": True}


@router.post("/runs/{run_id}/nodes/{node_id}/stop")
def stop_node(run_id: int, node_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    r = session.get(PipelineRun, run_id)
    if r is None:
        raise HTTPException(404, "Pipeline run not found")
    state = (r.nodes or {}).get(node_id)
    if state is None:
        raise HTTPException(404, "Node not found")
    if state.get("status") != "running" or not pipeline_runner.stop_node(run_id, node_id):
        raise HTTPException(409, f"Node {node_id} is {state.get('status')}; only running nodes can be stopped")
    return {"stopping": True}


def _get(session: Session, pipeline_id: int) -> Pipeline:
    p = session.get(Pipeline, pipeline_id)
    if p is None:
        raise HTTPException(404, "Pipeline not found")
    return p


@router.get("/{pipeline_id}")
def get_pipeline(pipeline_id: int, version: Optional[str] = None, session: Session = Depends(get_session)) -> dict[str, Any]:
    p = _get(session, pipeline_id)
    out = serialize(p, session, user_map(session), detail=True)
    if version and version != p.version:
        pv = session.exec(select(PipelineVersion).where(PipelineVersion.pipeline_id == p.id, PipelineVersion.version == version)).first()
        if pv is None:
            raise HTTPException(404, "Version not found")
        out["yaml"] = pv.yaml
        out["spec"] = parse_spec(pv.yaml)
        out["viewing_version"] = version
    else:
        out["viewing_version"] = p.version
    return out


class YamlBody(BaseModel):
    yaml: str


def _save_yaml(session: Session, p: Pipeline, text: str) -> dict[str, Any]:
    try:
        spec = parse_spec(text)
    except PipelineSpecError as exc:
        raise HTTPException(400, str(exc)) from exc
    if spec["name"] != p.name:
        clash = session.exec(select(Pipeline).where(Pipeline.name == spec["name"], Pipeline.id != p.id)).first()
        if clash:
            raise HTTPException(409, "Another pipeline already uses that name")
        p.name = spec["name"]
    p.yaml = text
    p.version = spec["version"]
    p.updated_at = utcnow()
    session.add(p)
    existing = session.exec(select(PipelineVersion).where(PipelineVersion.pipeline_id == p.id,
                                                          PipelineVersion.version == spec["version"])).first()
    if existing:
        existing.yaml = text
        session.add(existing)
    else:
        session.add(PipelineVersion(pipeline_id=p.id, version=spec["version"], yaml=text))
    return spec


@router.put("/{pipeline_id}")
def put_yaml(pipeline_id: int, body: YamlBody, session: Session = Depends(get_session), actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    p = _get(session, pipeline_id)
    spec = _save_yaml(session, p, body.yaml)
    add_activity(session, actor.id if actor else None, "pipeline", "edited", f"Saved {p.name} {spec['version']} YAML", f"/pipelines?select={p.id}")
    session.commit()
    return serialize(p, session, user_map(session), detail=True)


class PatchPipeline(BaseModel):
    active: Optional[bool] = None
    description: Optional[str] = None
    version: Optional[str] = None


@router.patch("/{pipeline_id}")
def patch_pipeline(pipeline_id: int, body: PatchPipeline, session: Session = Depends(get_session),
                   actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    p = _get(session, pipeline_id)
    if body.active is not None:
        p.active = body.active
        add_activity(session, actor.id if actor else None, "pipeline", "active",
                     f"{'Activated' if body.active else 'Paused'} pipeline {p.name}", f"/pipelines?select={p.id}")
    if body.description is not None:
        p.description = body.description
    if body.version is not None and body.version != p.version:
        pv = session.exec(select(PipelineVersion).where(PipelineVersion.pipeline_id == p.id, PipelineVersion.version == body.version)).first()
        if pv is None:
            raise HTTPException(404, "Version not found")
        p.yaml, p.version = pv.yaml, pv.version
        add_activity(session, actor.id if actor else None, "pipeline", "version", f"Switched {p.name} to {pv.version}", f"/pipelines?select={p.id}")
    p.updated_at = utcnow()
    session.add(p)
    session.commit()
    return serialize(p, session, user_map(session), detail=True)


class NodeParams(BaseModel):
    params: dict[str, Any]


@router.patch("/{pipeline_id}/nodes/{node_id}")
def patch_node(pipeline_id: int, node_id: str, body: NodeParams, session: Session = Depends(get_session),
               actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    p = _get(session, pipeline_id)
    spec = parse_spec(p.yaml)
    node = next((n for n in spec["nodes"] if n["id"] == node_id), None)
    if node is None:
        raise HTTPException(404, "Node not found")
    node["params"] = body.params
    _save_yaml(session, p, dump_spec(spec))
    add_activity(session, actor.id if actor else None, "pipeline", "params", f"Updated {node['name']} parameters in {p.name}",
                 f"/pipelines?select={p.id}")
    session.commit()
    return serialize(p, session, user_map(session), detail=True)


class RunBody(BaseModel):
    version: Optional[str] = None


@router.post("/{pipeline_id}/run")
def run_pipeline(pipeline_id: int, body: RunBody | None = None, session: Session = Depends(get_session),
                 actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    _get(session, pipeline_id)
    try:
        run = pipeline_runner.start(pipeline_id, "manual", actor.id if actor else None, (body.version if body else None))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (PipelineSpecError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return serialize_run(run, user_map(session))


class ScheduleBody(BaseModel):
    cron: Optional[str] = None


@router.post("/{pipeline_id}/schedule")
def schedule(pipeline_id: int, body: ScheduleBody, session: Session = Depends(get_session),
             actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    p = _get(session, pipeline_id)
    cron = (body.cron or "").strip() or None
    if cron:
        try:
            validate_cron(cron)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    p.schedule = cron
    p.updated_at = utcnow()
    session.add(p)
    add_activity(session, actor.id if actor else None, "pipeline", "schedule",
                 f"{'Scheduled' if cron else 'Unscheduled'} {p.name}" + (f" ({cron})" if cron else ""), f"/pipelines?select={p.id}")
    session.commit()
    next_run = pipeline_runner.apply_schedule(p.id, cron)
    return {**serialize(p, session, user_map(session), detail=True), "next_run": next_run}


@router.post("/{pipeline_id}/duplicate")
def duplicate(pipeline_id: int, session: Session = Depends(get_session), actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    p = _get(session, pipeline_id)
    base, i = f"{p.name} (copy)", 2
    name = base
    while session.exec(select(Pipeline).where(Pipeline.name == name)).first():
        name = f"{base} {i}"
        i += 1
    spec = parse_spec(p.yaml)
    spec["name"] = name
    text = dump_spec(spec)
    q = Pipeline(name=name, description=p.description, version=spec["version"], yaml=text, active=False,
                 owner_id=actor.id if actor else None)
    session.add(q)
    session.commit()
    session.refresh(q)
    session.add(PipelineVersion(pipeline_id=q.id, version=q.version, yaml=text))
    add_activity(session, q.owner_id, "pipeline", "created", f"Duplicated {p.name} as {name}", f"/pipelines?select={q.id}")
    session.commit()
    return serialize(q, session, user_map(session), detail=True)


@router.delete("/{pipeline_id}")
def delete_pipeline(pipeline_id: int, session: Session = Depends(get_session), actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    p = _get(session, pipeline_id)
    active = session.exec(select(PipelineRun).where(PipelineRun.pipeline_id == p.id, PipelineRun.status.in_(["Queued", "Running"]))).first()
    if active:
        raise HTTPException(409, "Stop the active run first")
    pipeline_runner.apply_schedule(p.id, None)
    for v in session.exec(select(PipelineVersion).where(PipelineVersion.pipeline_id == p.id)).all():
        session.delete(v)
    for r in session.exec(select(PipelineRun).where(PipelineRun.pipeline_id == p.id)).all():
        for l in session.exec(select(PipelineLog).where(PipelineLog.run_id == r.id)).all():
            session.delete(l)
        session.delete(r)
    add_activity(session, actor.id if actor else None, "pipeline", "deleted", f"Deleted pipeline {p.name}", "/pipelines")
    session.delete(p)
    session.commit()
    return {"deleted": True}


@router.get("/{pipeline_id}/export", response_class=PlainTextResponse)
def export_yaml(pipeline_id: int, session: Session = Depends(get_session)) -> PlainTextResponse:
    p = _get(session, pipeline_id)
    filename = f"{p.name.replace(' ', '_')}_{p.version}.yaml"
    return PlainTextResponse(p.yaml, media_type="application/x-yaml",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/{pipeline_id}/runs")
def list_runs(pipeline_id: int, limit: int = Query(20, le=100), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    _get(session, pipeline_id)
    runs = session.exec(select(PipelineRun).where(PipelineRun.pipeline_id == pipeline_id)
                        .order_by(PipelineRun.number.desc()).limit(limit)).all()
    umap = user_map(session)
    return [serialize_run(r, umap) for r in runs]
