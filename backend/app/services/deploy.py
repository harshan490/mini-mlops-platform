"""Create a deployment or roll a new version out to an existing one."""
from __future__ import annotations

from typing import Optional

from sqlmodel import Session, select

from app.models import Deployment, ModelVersion, RegisteredModel
from app.services import registry
from app.services.serving import serving
from app.utils import slugify, utcnow

ENVIRONMENTS = ["Production", "Staging", "Development"]


def unique_slug(session: Session, base: str) -> str:
    slug = slugify(base)
    candidate, i = slug, 2
    while session.exec(select(Deployment).where(Deployment.slug == candidate)).first():
        candidate = f"{slug}-{i}"
        i += 1
    return candidate


def deploy_version(session: Session, model_id: int, version_id: int, environment: str, actor_id: Optional[int],
                   name: Optional[str] = None, replicas: int = 1) -> Deployment:
    if environment not in ENVIRONMENTS:
        raise ValueError(f"environment must be one of {ENVIRONMENTS}")
    model = session.get(RegisteredModel, model_id)
    mv = session.get(ModelVersion, version_id)
    if model is None or mv is None or mv.model_id != model_id:
        raise LookupError("Model version not found")
    if not mv.artifact_path:
        raise ValueError(f"{model.name} {mv.version} is seeded history without a trained artifact, so it cannot be served.")
    if not 1 <= replicas <= 16:
        raise ValueError("replicas must be between 1 and 16")

    # Deploying to an environment promotes the version to the matching stage.
    if environment == "Production" and mv.stage != "Production":
        registry.set_stage(session, model_id, mv.version, "Production", actor_id)
    elif environment == "Staging" and mv.stage == "Development":
        registry.set_stage(session, model_id, mv.version, "Staging", actor_id)

    dep = session.exec(select(Deployment).where(Deployment.model_id == model_id, Deployment.environment == environment)).first()
    if dep is not None:
        if dep.version_id != version_id:
            dep.previous_version_id = dep.version_id
            dep.version_id = version_id
        dep.status = "Deploying"
        dep.progress = 0
        dep.stage_label = "Queued"
        dep.updated_at = utcnow()
        session.add(dep)
        session.commit()
        session.refresh(dep)
        serving.rollout(dep.id, version_id, "rollout", actor_id, f"Rolled out {model.name} {mv.version} to {environment}")
        return dep

    dep = Deployment(slug=unique_slug(session, f"{model.name}-{environment}"), name=name or model.name, model_id=model_id,
                     version_id=version_id, environment=environment, status="Deploying", replicas=replicas,
                     min_replicas=1, max_replicas=max(4, replicas), progress=0, stage_label="Queued", owner_id=actor_id)
    session.add(dep)
    session.commit()
    session.refresh(dep)
    serving.rollout(dep.id, version_id, "deploy", actor_id, f"Deployed {model.name} {mv.version} to {environment}")
    return dep
