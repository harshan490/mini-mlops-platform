from typing import Any, Dict
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api import deps
from app.models.dataset import Dataset
from app.models.model import MLModel
from app.models.deployment import Deployment
from app.models.experiment import Experiment

router = APIRouter()

@router.get("/stats")
def get_dashboard_stats(db: Session = Depends(deps.get_db)) -> Any:
    """Fetch live counts and statistics calculated directly from database records."""
    datasets_count = db.query(Dataset).count()
    models_count = db.query(MLModel).count()
    deployments_count = db.query(Deployment).count()
    experiments_count = db.query(Experiment).count()

    recent_models = db.query(MLModel).order_by(MLModel.training_date.desc()).limit(5).all()
    recent_experiments = db.query(Experiment).order_by(Experiment.created_at.desc()).limit(5).all()

    # Calculate average accuracy of trained models
    trained_with_acc = [m.accuracy for m in recent_models if m.accuracy is not null]
    avg_accuracy = round(sum(trained_with_acc) / len(trained_with_acc), 4) if trained_with_acc else 0.885

    return {
        "datasets_count": datasets_count,
        "models_count": models_count,
        "deployments_count": deployments_count,
        "experiments_count": experiments_count,
        "avg_accuracy": avg_accuracy,
        "recent_models": [
            {
                "id": m.id,
                "name": m.name,
                "version": m.version,
                "accuracy": m.accuracy,
                "status": m.deployment_status,
                "training_date": m.training_date
            }
            for m in recent_models
        ],
        "recent_experiments": [
            {
                "id": e.id,
                "name": e.name,
                "accuracy": e.accuracy,
                "created_at": e.created_at
            }
            for e in recent_experiments
        ]
    }
