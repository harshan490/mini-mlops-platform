from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base

class MLModel(Base):
    __tablename__ = "models"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    version = Column(String, nullable=False, default="v1.0")
    accuracy = Column(Float, nullable=True)
    training_date = Column(DateTime(timezone=True), server_default=func.now())
    deployment_status = Column(String, default="Not Deployed") # Not Deployed, Staging, Production
    mlflow_model_uri = Column(String, nullable=False)
    
    experiment_id = Column(Integer, ForeignKey("experiments.id"))
    user_id = Column(Integer, ForeignKey("users.id"))

    experiment = relationship("Experiment")
    owner = relationship("User")
