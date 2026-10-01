import random
from typing import Any, List, Optional, Dict
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime

from app.api import deps
from app.models.deployment import Deployment
from app.models.model import MLModel
from app.models.user import User

router = APIRouter()

class DeployRequest(BaseModel):
    model_id: int
    environment: str = "Production" # Staging or Production

class DeploymentResponse(BaseModel):
    id: int
    model_id: int
    model_name: str
    endpoint_url: str
    status: str
    environment: str
    deployed_at: datetime

class PredictRequest(BaseModel):
    features: Dict[str, Any]

class PredictResponse(BaseModel):
    deployment_id: int
    prediction: Any
    probability: Optional[float]
    latency_ms: float

@router.get("/", response_model=List[DeploymentResponse])
def get_deployments(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100
) -> Any:
    """Fetch all model deployments."""
    deployments = db.query(Deployment).order_by(Deployment.deployed_at.desc()).offset(skip).limit(limit).all()
    
    results = []
    for dep in deployments:
        model_name = dep.model.name if dep.model else f"Model #{dep.model_id}"
        results.append({
            "id": dep.id,
            "model_id": dep.model_id,
            "model_name": model_name,
            "endpoint_url": dep.endpoint_url,
            "status": dep.status,
            "environment": "Production",
            "deployed_at": dep.deployed_at
        })
    return results

@router.post("/deploy", response_model=DeploymentResponse)
def deploy_model(
    *,
    db: Session = Depends(deps.get_db),
    request: DeployRequest,
    current_user: User = Depends(deps.get_current_user_optional)
) -> Any:
    """Deploy a trained model into service."""
    model = db.query(MLModel).filter(MLModel.id == request.model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    endpoint_url = f"/api/deployments/predict/{model.id}"
    
    deployment = Deployment(
        model_id=model.id,
        endpoint_url=endpoint_url,
        status="Active",
        user_id=current_user.id
    )
    
    # Update model deployment status
    model.deployment_status = request.environment
    
    db.add(deployment)
    db.commit()
    db.refresh(deployment)
    db.refresh(model)

    return {
        "id": deployment.id,
        "model_id": model.id,
        "model_name": model.name,
        "endpoint_url": deployment.endpoint_url,
        "status": deployment.status,
        "environment": request.environment,
        "deployed_at": deployment.deployed_at
    }

@router.post("/predict/{deployment_id}", response_model=PredictResponse)
def predict(
    deployment_id: int,
    request: PredictRequest,
    db: Session = Depends(deps.get_db)
) -> Any:
    """Execute prediction inference against a deployed endpoint."""
    deployment = db.query(Deployment).filter(Deployment.id == deployment_id).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment endpoint not found")

    # Perform mock inference or feature scoring based on input payload
    prob = round(random.uniform(0.72, 0.98), 4)
    pred_val = 1 if prob >= 0.5 else 0

    return {
        "deployment_id": deployment.id,
        "prediction": pred_val,
        "probability": prob,
        "latency_ms": round(random.uniform(12.5, 45.0), 2)
    }
