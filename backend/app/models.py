"""Database tables (SQLModel).

JSON columns are always *reassigned*, never mutated in place, so SQLAlchemy
notices the change.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import NaiveDatetime
from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel

from app.utils import utcnow


def _json(default_factory=dict):
    return Field(default_factory=default_factory, sa_column=Column(JSON))


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    display_name: str
    email: str = ""
    title: str = ""
    role: str = "Member"
    bio: str = ""
    location: str = ""
    accent: str = "#3B82F6"
    quote: str = ""
    joined_at: NaiveDatetime = Field(default_factory=utcnow)


class Dataset(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str = ""
    dtype: str = "Tabular"  # Image | Tabular | Time Series | Text | Other
    status: str = "Ready"  # Ready | Processing | Failed
    tags: list = _json(list)
    target_column: Optional[str] = None
    is_real: bool = True  # False = metadata-only record (no file on disk)
    current_version: int = 1
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    created_at: NaiveDatetime = Field(default_factory=utcnow)
    updated_at: NaiveDatetime = Field(default_factory=utcnow)


class DatasetVersion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    dataset_id: int = Field(foreign_key="dataset.id", index=True)
    version: int = 1
    file_path: Optional[str] = None
    file_name: str = ""
    file_format: str = ""  # csv | parquet | zip | xlsx
    size_bytes: int = 0
    rows: int = 0
    columns: int = 0
    missing_pct: float = 0.0
    duplicate_pct: float = 0.0
    quality: float = 0.0
    schema_info: list = _json(list)
    note: str = ""
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id")
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class Run(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)  # exp-28, exp-30-t2
    name: str = ""
    algorithm: str = ""  # key, e.g. xgboost
    algorithm_label: str = ""  # e.g. XGBoost
    framework: str = ""
    task: str = "classification"
    kind: str = "train"  # train | autotune | trial | pipeline
    source: str = "live"  # live | seed
    dataset_id: Optional[int] = Field(default=None, foreign_key="dataset.id", index=True)
    dataset_version: Optional[int] = None
    target: Optional[str] = None
    status: str = "Queued"  # Queued | Training | Completed | Failed | Stopped
    params: dict = _json(dict)
    metrics: dict = _json(dict)
    progress: float = 0.0
    epoch: int = 0
    total_epochs: int = 0
    device: str = "CPU"
    gpu_hours: float = 0.0
    checkpoint_path: Optional[str] = None
    artifact_path: Optional[str] = None
    parent_id: Optional[int] = Field(default=None, index=True)
    error: Optional[str] = None
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    created_at: NaiveDatetime = Field(default_factory=utcnow)
    started_at: Optional[NaiveDatetime] = None
    finished_at: Optional[NaiveDatetime] = None
    duration_s: float = 0.0


class RunMetric(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(index=True)
    epoch: int
    train_loss: Optional[float] = None
    val_loss: Optional[float] = None
    train_acc: Optional[float] = None
    val_acc: Optional[float] = None
    f1: Optional[float] = None
    ts: NaiveDatetime = Field(default_factory=utcnow)


class RegisteredModel(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str = ""
    tags: list = _json(list)
    framework: str = ""
    model_type: str = ""
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    created_at: NaiveDatetime = Field(default_factory=utcnow)
    updated_at: NaiveDatetime = Field(default_factory=utcnow)


class ModelVersion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    model_id: int = Field(foreign_key="registeredmodel.id", index=True)
    version: str = "v1.0.0"
    run_id: Optional[int] = Field(default=None, index=True)
    stage: str = "Development"  # Development | Staging | Production | Archived
    accuracy: Optional[float] = None
    size_bytes: int = 0
    artifact_path: Optional[str] = None
    description: str = ""
    metrics: dict = _json(dict)
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id")
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class Deployment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    name: str
    model_id: int = Field(foreign_key="registeredmodel.id", index=True)
    version_id: int = Field(foreign_key="modelversion.id")
    previous_version_id: Optional[int] = None
    environment: str = "Development"  # Production | Staging | Development
    status: str = "Deploying"  # Deploying | Running | Stopped | Failed
    replicas: int = 1
    min_replicas: int = 1
    max_replicas: int = 4
    target_cpu: int = 70
    rpm_per_replica: int = 60
    autoscaling: bool = True
    progress: float = 0.0
    stage_label: str = ""
    last_error: Optional[str] = None
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    created_at: NaiveDatetime = Field(default_factory=utcnow)
    updated_at: NaiveDatetime = Field(default_factory=utcnow)


class DeploymentEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    deployment_id: int = Field(index=True)
    kind: str  # deploy | rollback | restart | scale | autoscale | stop | start | rollout
    version_label: str = ""
    environment: str = ""
    message: str = ""
    ts: NaiveDatetime = Field(default_factory=utcnow)


class PredictionLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    deployment_id: int = Field(index=True)
    version_id: Optional[int] = None
    ts: NaiveDatetime = Field(default_factory=utcnow, index=True)
    latency_ms: float = 0.0
    input: dict = _json(dict)
    prediction: Optional[Any] = Field(default=None, sa_column=Column(JSON))
    is_error: bool = False
    error: Optional[str] = None
    replica: int = 0
    source: str = "live"  # live | simulate | seed


class SystemMetric(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: NaiveDatetime = Field(default_factory=utcnow, index=True)
    cpu: float = 0.0
    ram: float = 0.0
    gpu: float = 0.0
    ram_used_gb: float = 0.0
    ram_total_gb: float = 0.0
    gpu_mem_used_gb: float = 0.0
    gpu_mem_total_gb: float = 0.0
    cpu_count: int = 0


class Pipeline(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str = ""
    version: str = "v1.0.0"
    yaml: str = Field(default="", sa_column=Column(Text))
    active: bool = True
    schedule: Optional[str] = None
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    created_at: NaiveDatetime = Field(default_factory=utcnow)
    updated_at: NaiveDatetime = Field(default_factory=utcnow)


class PipelineVersion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pipeline_id: int = Field(index=True)
    version: str
    yaml: str = Field(default="", sa_column=Column(Text))
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class PipelineRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pipeline_id: int = Field(index=True)
    number: int
    version: str = ""
    yaml_snapshot: str = Field(default="", sa_column=Column(Text))
    triggered_by: str = "manual"  # manual | schedule | api
    status: str = "Queued"  # Queued | Running | Success | Failed | Stopped
    nodes: dict = _json(dict)
    source: str = "live"
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    started_at: NaiveDatetime = Field(default_factory=utcnow)
    finished_at: Optional[NaiveDatetime] = None
    duration_s: float = 0.0


class PipelineLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(index=True)
    ts: NaiveDatetime = Field(default_factory=utcnow)
    level: str = "INFO"
    node: str = ""
    message: str = ""


class Alert(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: NaiveDatetime = Field(default_factory=utcnow, index=True)
    severity: str = "info"  # critical | warning | info | success
    kind: str = ""  # error_rate | latency | drift | recovery | run_completed | run_failed | deployed
    category: str = "monitoring"  # monitoring | experiment | deployment | system
    title: str = ""
    message: str = ""
    deployment_id: Optional[int] = None
    read: bool = False
    resolved: bool = True


class AppSettings(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    data: dict = _json(dict)
    updated_at: NaiveDatetime = Field(default_factory=utcnow)


class ApiKey(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    provider: str
    label: str = ""
    ciphertext: str
    masked: str = ""
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id")
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class Activity(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: NaiveDatetime = Field(default_factory=utcnow, index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    kind: str = ""  # dataset | experiment | model | deployment | pipeline | settings
    action: str = ""
    message: str = ""
    link: str = ""
