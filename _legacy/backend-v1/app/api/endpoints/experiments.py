from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime

from app.api import deps
from app.models.experiment import Experiment
from app.models.dataset import Dataset

router = APIRouter()

class ExperimentResponse(BaseModel):
    id: int
    name: str
    mlflow_run_id: Optional[str]
    dataset_id: Optional[int]
    dataset_name: Optional[str] = "N/A"
    accuracy: Optional[float]
    created_at: datetime

    class Config:
        from_attributes = True

@router.get("/", response_model=List[ExperimentResponse])
def get_experiments(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100
) -> Any:
    """Fetch all recorded ML experiments."""
    experiments = db.query(Experiment).order_by(Experiment.created_at.desc()).offset(skip).limit(limit).all()
    
    results = []
    for exp in experiments:
        ds_name = exp.dataset.name if exp.dataset else "N/A"
        results.append({
            "id": exp.id,
            "name": exp.name,
            "mlflow_run_id": exp.mlflow_run_id,
            "dataset_id": exp.dataset_id,
            "dataset_name": ds_name,
            "accuracy": exp.accuracy,
            "created_at": exp.created_at
        })
        
    return results
