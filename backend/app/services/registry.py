"""Model registry: register runs as versioned models, stage transitions, lineage."""
from __future__ import annotations

import re
import shutil
from typing import Any, Optional

from sqlmodel import Session, select

from app.config import MODELS_DIR
from app.models import Dataset, ModelVersion, RegisteredModel, Run
from app.services import storage
from app.services.activity import add_activity
from app.utils import safe_name, utcnow

STAGES = ["Development", "Staging", "Production", "Archived"]


def parse_version(v: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", v.strip())
    if not m:
        return (0, 0, 0)
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def next_version(session: Session, model_id: int) -> str:
    versions = session.exec(select(ModelVersion.version).where(ModelVersion.model_id == model_id)).all()
    if not versions:
        return "v1.0.0"
    major, minor, _ = max(parse_version(v) for v in versions)
    return f"v{major}.{minor + 1}.0"


def model_type_for(task: str) -> str:
    return "Regression" if task == "regression" else "Classification"


def register_run(session: Session, run_id: int, name: str, description: str = "", owner_id: Optional[int] = None,
                 tags: Optional[list[str]] = None) -> ModelVersion:
    run = session.get(Run, run_id)
    if run is None:
        raise LookupError("Run not found")
    if run.status != "Completed" or not run.artifact_path:
        raise ValueError(f"Run {run.code} has no trained artifact (status {run.status}); only completed live runs can be registered.")
    src = storage.resolve(run.artifact_path)
    if src is None or not src.exists():
        raise ValueError("Artifact file is missing on disk")
    name = name.strip()
    if not name:
        raise ValueError("Model name is required")

    model = session.exec(select(RegisteredModel).where(RegisteredModel.name == name)).first()
    if model is None:
        model = RegisteredModel(name=name, description=description or f"{run.algorithm_label} model trained in {run.code}.",
                                framework=run.framework, model_type=model_type_for(run.task), owner_id=owner_id,
                                tags=tags or [])
        session.add(model)
        session.commit()
        session.refresh(model)
    version = next_version(session, model.id)
    dest_dir = MODELS_DIR / safe_name(name) / version
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest_dir / "model.joblib")
    for extra in ("metadata.json", "holdout.parquet"):
        extra_src = src.parent / extra
        if extra_src.exists():
            shutil.copy2(extra_src, dest_dir / extra)
    size = sum(f.stat().st_size for f in dest_dir.iterdir() if f.is_file())
    mv = ModelVersion(model_id=model.id, version=version, run_id=run.id, stage="Development",
                      accuracy=(run.metrics or {}).get("accuracy"), size_bytes=size,
                      artifact_path=storage.rel(dest_dir / "model.joblib"),
                      description=description or f"Registered from {run.code}", metrics=dict(run.metrics or {}),
                      owner_id=owner_id, created_at=utcnow())
    session.add(mv)
    model.updated_at = utcnow()
    session.add(model)
    add_activity(session, owner_id, "model", "registered", f"Registered {name} {version} from {run.code}",
                 f"/models?select={model.id}")
    session.commit()
    session.refresh(mv)
    return mv


def set_stage(session: Session, model_id: int, version: str, stage: str, actor_id: Optional[int] = None) -> ModelVersion:
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}")
    mv = session.exec(select(ModelVersion).where(ModelVersion.model_id == model_id, ModelVersion.version == version)).first()
    if mv is None:
        raise LookupError("Model version not found")
    model = session.get(RegisteredModel, model_id)
    demoted: list[str] = []
    if stage == "Production":
        others = session.exec(select(ModelVersion).where(ModelVersion.model_id == model_id, ModelVersion.stage == "Production",
                                                         ModelVersion.id != mv.id)).all()
        for other in others:
            other.stage = "Staging"
            session.add(other)
            demoted.append(other.version)
    mv.stage = stage
    session.add(mv)
    model.updated_at = utcnow()
    session.add(model)
    msg = f"Moved {model.name} {version} to {stage}"
    if demoted:
        msg += f" (demoted {', '.join(demoted)} to Staging)"
    add_activity(session, actor_id, "model", "stage", msg, f"/models?select={model_id}")
    session.commit()
    session.refresh(mv)
    return mv


def lineage(session: Session, model_id: int) -> dict[str, Any]:
    model = session.get(RegisteredModel, model_id)
    if model is None:
        raise LookupError("Model not found")
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()
    versions = session.exec(select(ModelVersion).where(ModelVersion.model_id == model_id).order_by(ModelVersion.created_at)).all()
    for mv in versions:
        mv_id = f"mv-{mv.id}"
        nodes.append({"id": mv_id, "type": "model", "label": f"{model.name} {mv.version}", "sub": mv.stage})
        run = session.get(Run, mv.run_id) if mv.run_id else None
        if run is None:
            continue
        run_node = f"run-{run.id}"
        if run_node not in seen:
            seen.add(run_node)
            acc = (run.metrics or {}).get("accuracy")
            nodes.append({"id": run_node, "type": "run", "label": run.code,
                          "sub": f"{run.algorithm_label}" + (f" · {acc:.3f}" if isinstance(acc, (int, float)) else "")})
        edges.append({"id": f"{run_node}->{mv_id}", "source": run_node, "target": mv_id})
        if run.dataset_id:
            ds = session.get(Dataset, run.dataset_id)
            if ds:
                ds_node = f"ds-{ds.id}-v{run.dataset_version or ds.current_version}"
                if ds_node not in seen:
                    seen.add(ds_node)
                    nodes.append({"id": ds_node, "type": "dataset", "label": ds.name,
                                  "sub": f"v{run.dataset_version or ds.current_version}"})
                edge_id = f"{ds_node}->{run_node}"
                if edge_id not in seen:
                    seen.add(edge_id)
                    edges.append({"id": edge_id, "source": ds_node, "target": run_node})
    return {"nodes": nodes, "edges": edges}
