from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime

from app.api import deps
from app.models.model import MLModel

router = APIRouter()

class ModelAlgorithmResponse(BaseModel):
    id: str
    name: str
    category: str
    type: str  # Classification or Regression
    description: str
    popular_hyperparameters: List[str]

class TrainedModelResponse(BaseModel):
    id: int
    name: str
    version: str
    accuracy: Optional[float]
    training_date: datetime
    deployment_status: str
    mlflow_model_uri: str
    experiment_id: Optional[int]

    class Config:
        from_attributes = True

AVAILABLE_ALGORITHMS = [
    {
        "id": "random_forest_classifier",
        "name": "Random Forest Classifier",
        "category": "Ensemble",
        "type": "Classification",
        "description": "An ensemble of decision trees using bagging to produce robust multi-class predictions.",
        "popular_hyperparameters": ["n_estimators", "max_depth", "min_samples_split"]
    },
    {
        "id": "xgboost_classifier",
        "name": "XGBoost Classifier",
        "category": "Gradient Boosting",
        "type": "Classification",
        "description": "Optimized gradient boosted decision tree framework known for speed and high performance.",
        "popular_hyperparameters": ["n_estimators", "learning_rate", "max_depth", "subsample"]
    },
    {
        "id": "logistic_regression",
        "name": "Logistic Regression",
        "category": "Linear Models",
        "type": "Classification",
        "description": "Linear classifier suitable for binary or multinomial classification with probabilistic output.",
        "popular_hyperparameters": ["C", "penalty", "solver"]
    },
    {
        "id": "svm_classifier",
        "name": "Support Vector Machine (SVC)",
        "category": "Kernel Methods",
        "type": "Classification",
        "description": "Effective in high dimensional spaces by finding the hyper-plane that maximizes class margins.",
        "popular_hyperparameters": ["C", "kernel", "gamma"]
    },
    {
        "id": "random_forest_regressor",
        "name": "Random Forest Regressor",
        "category": "Ensemble",
        "type": "Regression",
        "description": "Bagging regressor suitable for complex continuous target prediction without severe overfitting.",
        "popular_hyperparameters": ["n_estimators", "max_depth", "min_samples_leaf"]
    },
    {
        "id": "linear_regression",
        "name": "Ridge / Linear Regression",
        "category": "Linear Models",
        "type": "Regression",
        "description": "Baseline regression algorithm predicting numeric target values with L2 regularization support.",
        "popular_hyperparameters": ["alpha", "fit_intercept"]
    }
]

@router.get("/algorithms", response_model=List[ModelAlgorithmResponse])
def get_available_algorithms() -> Any:
    """Get list of predefined ML algorithms available for model training."""
    return AVAILABLE_ALGORITHMS

@router.get("/", response_model=List[TrainedModelResponse])
def get_trained_models(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100
) -> Any:
    """Fetch all trained models from the database."""
    models = db.query(MLModel).order_by(MLModel.training_date.desc()).offset(skip).limit(limit).all()
    return models
