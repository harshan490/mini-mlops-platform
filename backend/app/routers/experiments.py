"""Experiments: start real training runs, auto-tune, stop, compare, delete."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.db import get_session
from app.models import Dataset, DatasetVersion, ModelVersion, RegisteredModel, Run, RunMetric, User
from app.services import storage
from app.services.activity import add_activity, get_actor
from app.services.settings_store import settings_store
from app.services.trainer import ALGORITHMS, BATCH_SIZES, OPTIMIZERS, _GPU_NAME, next_run_code, normalise_params, trainer
from app.services.users import find_user, owner_brief, user_map
from app.utils import iso, utcnow

router = APIRouter(prefix="/api/experiments", tags=["experiments"])

try:  # torch is optional; LSTM training is only offered when it is installed
    import importlib.util as _ilu

    TORCH_AVAILABLE = _ilu.find_spec("torch") is not None
except Exception:  # noqa: BLE001
    TORCH_AVAILABLE = False


def serialize(run: Run, umap: dict, ds_names: dict[int, str], detail: bool = False) -> dict[str, Any]:
    m = run.metrics or {}
    out = {
        "id": run.id, "code": run.code, "name": run.name, "algorithm": run.algorithm, "algorithm_label": run.algorithm_label,
        "framework": run.framework, "task": run.task, "kind": run.kind, "source": run.source, "status": run.status,
        "dataset_id": run.dataset_id, "dataset": ds_names.get(run.dataset_id or -1), "dataset_version": run.dataset_version,
        "target": run.target, "accuracy": m.get("accuracy"), "loss": m.get("loss"), "val_loss": m.get("val_loss"),
        "f1": m.get("f1"), "progress": run.progress, "epoch": run.epoch, "total_epochs": run.total_epochs,
        "eta_s": m.get("eta_s") if run.status == "Training" else None, "device": run.device, "gpu_hours": run.gpu_hours,
        "duration_s": run.duration_s, "parent_id": run.parent_id, "error": run.error,
        "has_artifact": bool(run.artifact_path), "owner": owner_brief(umap, run.owner_id),
        "created_at": iso(run.created_at), "started_at": iso(run.started_at), "finished_at": iso(run.finished_at),
    }
    if detail:
        out.update({
            "params": run.params, "metrics": m, "checkpoint_path": storage.display(run.checkpoint_path),
            "artifact_path": storage.display(run.artifact_path),
        })
    return out


def _ds_names(session: Session) -> dict[int, str]:
    return {d.id: d.name for d in session.exec(select(Dataset)).all()}


@router.get("")
def list_runs(q: str = "", status: str = "", algorithm: str = "", dataset_id: Optional[int] = None, owner: str = "",
              include_trials: bool = False, limit: int = Query(200, le=1000),
              session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    stmt = select(Run)
    if not include_trials:
        stmt = stmt.where(Run.kind != "trial")
    if status:
        stmt = stmt.where(Run.status == status)
    if algorithm:
        stmt = stmt.where((Run.algorithm == algorithm) | (Run.algorithm_label == algorithm))
    if dataset_id:
        stmt = stmt.where(Run.dataset_id == dataset_id)
    if owner:
        user = find_user(session, owner)
        stmt = stmt.where(Run.owner_id == (user.id if user else -1))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(Run.code.ilike(like) | Run.name.ilike(like) | Run.algorithm_label.ilike(like))
    runs = session.exec(stmt.order_by(Run.created_at.desc(), Run.id.desc()).limit(limit)).all()
    umap, names = user_map(session), _ds_names(session)
    return [serialize(r, umap, names) for r in runs]


@router.get("/algorithms")
def algorithms() -> dict[str, Any]:
    return {
        "algorithms": [{"key": k, **v} for k, v in ALGORITHMS.items()],
        "batch_sizes": BATCH_SIZES, "optimizers": OPTIMIZERS, "torch_available": TORCH_AVAILABLE,
        "gpu": _GPU_NAME,
        "note": None if TORCH_AVAILABLE else "PyTorch is not installed, so LSTM runs exist only as seeded history.",
    }


@router.get("/stats")
def stats(session: Session = Depends(get_session)) -> dict[str, Any]:
    runs = session.exec(select(Run).where(Run.kind != "trial")).all()
    now = utcnow()
    week = now - timedelta(days=7)
    done = [r for r in runs if r.status == "Completed" and (r.metrics or {}).get("accuracy") is not None
            and r.task != "regression"]
    best = max((r.metrics["accuracy"] for r in done), default=None)
    best_before = max((r.metrics["accuracy"] for r in done if r.created_at < week), default=None)
    gpu_total = sum(r.gpu_hours or 0 for r in session.exec(select(Run)).all() if r.kind != "autotune")
    gpu_recent = sum(r.gpu_hours or 0 for r in session.exec(select(Run)).all() if r.created_at >= week and r.kind != "autotune")
    working = [r for r in runs if r.status in ("Training", "Queued")]
    days = [(now - timedelta(days=13 - i)).date() for i in range(14)]
    per_day = {d: 0 for d in days}
    gpu_day = {d: 0.0 for d in days}
    for r in runs:
        d = r.created_at.date()
        if d in per_day:
            per_day[d] += 1
            gpu_day[d] += r.gpu_hours or 0
    best_curve, running_best = [], 0.0
    for d in days:
        vals = [r.metrics["accuracy"] for r in done if r.created_at.date() <= d]
        running_best = max(vals) if vals else running_best
        best_curve.append(round(running_best, 4))
    by_algo: dict[str, float] = {}
    for r in done:
        label = r.algorithm_label
        by_algo[label] = max(by_algo.get(label, 0.0), float(r.metrics["accuracy"]))
    return {
        "total": len(runs), "delta_total": sum(1 for r in runs if r.created_at >= week),
        "working": len(working), "delta_working": len(working),
        "best_accuracy": best, "delta_best": (round(best - best_before, 4) if best is not None and best_before is not None else None),
        "gpu_hours": round(gpu_total, 2),
        "delta_gpu_pct": (round(gpu_recent / (gpu_total - gpu_recent) * 100, 1) if gpu_total - gpu_recent > 0 else None),
        "spark_total": [per_day[d] for d in days],
        "spark_best": best_curve,
        "spark_gpu": [round(gpu_day[d], 3) for d in days],
        "model_metrics": [{"algorithm": k, "accuracy": round(v, 4)} for k, v in sorted(by_algo.items(), key=lambda kv: -kv[1])][:6],
    }


@router.get("/active")
def active_run(session: Session = Depends(get_session)) -> Optional[dict[str, Any]]:
    run = session.exec(select(Run).where(Run.status.in_(["Training", "Queued"]), Run.kind != "trial")
                       .order_by(Run.started_at.desc())).first()
    if run is None:
        return None
    return serialize(run, user_map(session), _ds_names(session), detail=True)


@router.get("/performance")
def performance(metric: str = "accuracy", session: Session = Depends(get_session)) -> dict[str, Any]:
    """Per-epoch curves of the most recent completed run of each algorithm (dashboard chart)."""
    field = {"accuracy": "val_acc", "loss": "val_loss", "f1": "f1"}.get(metric)
    if field is None:
        raise HTTPException(400, "metric must be accuracy, loss or f1")
    runs = session.exec(select(Run).where(Run.status == "Completed", Run.kind.in_(["train", "pipeline"]), Run.task == "classification")
                        .order_by(Run.finished_at.desc())).all()
    chosen: dict[str, Run] = {}
    for r in runs:
        if r.algorithm_label not in chosen:
            chosen[r.algorithm_label] = r
        if len(chosen) == 4:
            break
    series = []
    for label, r in chosen.items():
        rows = session.exec(select(RunMetric).where(RunMetric.run_id == r.id).order_by(RunMetric.epoch)).all()
        points = [{"epoch": m.epoch, "value": getattr(m, field)} for m in rows if getattr(m, field) is not None]
        if points:
            series.append({"label": label, "run": r.code, "points": points})
    return {"metric": metric, "series": series}


@router.get("/compare")
def compare(ids: str, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    try:
        run_ids = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError as exc:
        raise HTTPException(400, "ids must be comma-separated integers") from exc
    if len(run_ids) < 2:
        raise HTTPException(400, "Select at least two runs to compare")
    umap, names = user_map(session), _ds_names(session)
    out = []
    for rid in run_ids[:6]:
        run = session.get(Run, rid)
        if run is None:
            raise HTTPException(404, f"Run {rid} not found")
        metrics = session.exec(select(RunMetric).where(RunMetric.run_id == rid).order_by(RunMetric.epoch)).all()
        out.append({**serialize(run, umap, names, detail=True),
                    "history": [{"epoch": m.epoch, "train_loss": m.train_loss, "val_loss": m.val_loss,
                                 "train_acc": m.train_acc, "val_acc": m.val_acc, "f1": m.f1} for m in metrics]})
    return out


class StartRun(BaseModel):
    dataset_id: int
    algorithm: str
    name: str = ""
    dataset_version: Optional[int] = None
    target: Optional[str] = None
    params: dict[str, Any] = Field(default_factory=dict)


def _check_dataset(session: Session, dataset_id: int, version: Optional[int]) -> tuple[Dataset, int]:
    ds = session.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(404, "Dataset not found")
    number = version or ds.current_version
    dv = session.exec(select(DatasetVersion).where(DatasetVersion.dataset_id == ds.id, DatasetVersion.version == number)).first()
    if dv is None or not dv.file_path or dv.file_format not in {"csv", "parquet", "xlsx", "xls"}:
        raise HTTPException(400, f"{ds.name} v{number} has no tabular file on disk, so it cannot be trained on. "
                                 "Pick a dataset marked trainable or upload a CSV/Parquet file.")
    return ds, number


@router.post("")
def start_run(body: StartRun, session: Session = Depends(get_session), actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    ds, version = _check_dataset(session, body.dataset_id, body.dataset_version)
    try:
        params = normalise_params(body.algorithm, body.params)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    params.pop("data_path", None)
    info = ALGORITHMS[body.algorithm]
    use_gpu = body.algorithm == "xgboost" and int(settings_store.get()["compute"].get("gpu_limit", 0)) >= 1 and _GPU_NAME
    run = Run(code=next_run_code(session), name=body.name.strip() or f"{info['label']} on {ds.name}", algorithm=body.algorithm,
              algorithm_label=info["label"], framework=info["framework"], kind="train", dataset_id=ds.id,
              dataset_version=version, target=body.target or ds.target_column, params=params, total_epochs=params["epochs"],
              device=f"GPU ({_GPU_NAME})" if use_gpu else "CPU", owner_id=actor.id if actor else None, created_at=utcnow())
    session.add(run)
    session.commit()
    session.refresh(run)
    add_activity(session, run.owner_id, "experiment", "started", f"Started {run.code} ({info['label']} on {ds.name})",
                 f"/experiments?select={run.id}")
    session.commit()
    trainer.submit(run.id)
    return serialize(run, user_map(session), _ds_names(session), detail=True)


class AutoTune(BaseModel):
    dataset_id: int
    algorithm: str
    trials: int = 6
    trial_epochs: int = 20
    dataset_version: Optional[int] = None


@router.post("/autotune")
def autotune(body: AutoTune, session: Session = Depends(get_session), actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    ds, version = _check_dataset(session, body.dataset_id, body.dataset_version)
    if body.algorithm not in ALGORITHMS:
        raise HTTPException(400, f"Unknown algorithm {body.algorithm}")
    if not 2 <= body.trials <= 12:
        raise HTTPException(400, "trials must be between 2 and 12")
    if not 5 <= body.trial_epochs <= 100:
        raise HTTPException(400, "trial_epochs must be between 5 and 100")
    info = ALGORITHMS[body.algorithm]
    run = Run(code=next_run_code(session), name=f"Auto Tune · {info['label']} on {ds.name}", algorithm=body.algorithm,
              algorithm_label=info["label"], framework=info["framework"], kind="autotune", dataset_id=ds.id,
              dataset_version=version, target=ds.target_column,
              params={"trials": body.trials, "trial_epochs": body.trial_epochs, "search": "random"},
              total_epochs=body.trials, owner_id=actor.id if actor else None, created_at=utcnow())
    session.add(run)
    session.commit()
    session.refresh(run)
    add_activity(session, run.owner_id, "experiment", "autotune", f"Started auto-tune {run.code} ({body.trials} trials, {info['label']})",
                 f"/experiments?select={run.id}")
    session.commit()
    trainer.submit_autotune(run.id)
    return serialize(run, user_map(session), _ds_names(session), detail=True)


@router.get("/{run_id}")
def get_run(run_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    umap, names = user_map(session), _ds_names(session)
    out = serialize(run, umap, names, detail=True)
    if run.kind == "autotune":
        children = session.exec(select(Run).where(Run.parent_id == run.id).order_by(Run.id)).all()
        out["trials"] = [serialize(c, umap, names, detail=True) for c in children]
    versions = session.exec(select(ModelVersion).where(ModelVersion.run_id == run.id)).all()
    models = {m.id: m.name for m in session.exec(select(RegisteredModel)).all()}
    out["registered_as"] = [{"model_id": v.model_id, "model": models.get(v.model_id), "version": v.version, "stage": v.stage}
                            for v in versions]
    return out


@router.get("/{run_id}/metrics")
def run_metrics(run_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    rows = session.exec(select(RunMetric).where(RunMetric.run_id == run_id).order_by(RunMetric.epoch)).all()
    return {"run_id": run_id, "x_label": "trial" if run.kind == "autotune" else "epoch",
            "history": [{"epoch": m.epoch, "train_loss": m.train_loss, "val_loss": m.val_loss, "train_acc": m.train_acc,
                         "val_acc": m.val_acc, "f1": m.f1} for m in rows]}


@router.post("/{run_id}/stop")
def stop_run(run_id: int, session: Session = Depends(get_session), actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    if not trainer.stop(run_id):
        raise HTTPException(409, f"{run.code} is {run.status}; only queued or training runs can be stopped")
    add_activity(session, actor.id if actor else None, "experiment", "stop", f"Requested stop of {run.code}",
                 f"/experiments?select={run.id}")
    session.commit()
    return {"stopping": True, "id": run_id}


@router.delete("/{run_id}")
def delete_run(run_id: int, session: Session = Depends(get_session), actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    if run.status in ("Training", "Queued"):
        raise HTTPException(409, "Stop the run before deleting it")
    ids = [run.id] + [c.id for c in session.exec(select(Run).where(Run.parent_id == run.id)).all()]
    registered = session.exec(select(ModelVersion).where(ModelVersion.run_id.in_(ids))).all()
    if registered:
        models = {m.id: m.name for m in session.exec(select(RegisteredModel)).all()}
        names = ", ".join(f"{models.get(v.model_id)} {v.version}" for v in registered[:3])
        raise HTTPException(409, f"{run.code} backs registered model versions ({names}); it is kept for lineage.")
    codes = []
    for rid in ids:
        r = session.get(Run, rid)
        codes.append(r.code)
        for m in session.exec(select(RunMetric).where(RunMetric.run_id == rid)).all():
            session.delete(m)
        session.delete(r)
    add_activity(session, actor.id if actor else None, "experiment", "deleted", f"Deleted run {run.code}", "/experiments")
    session.commit()
    for code in codes:
        trainer.delete_files(code)
    return {"deleted": True, "id": run_id}
