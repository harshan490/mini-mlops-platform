"""Paths, secrets and feature flags.

Secrets (Fernet key for API keys, JWT signing secret) live in ``backend/.env``.
They are generated on first start when missing, so a fresh clone runs without
manual setup and no secret is ever committed.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
ENV_PATH = BASE_DIR / ".env"


def _load_env_file() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _ensure_secret(name: str, factory) -> str:
    value = os.environ.get(name)
    if value:
        return value
    value = factory()
    with ENV_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")
    os.environ[name] = value
    return value


_load_env_file()

FERNET_KEY: str = _ensure_secret("FERNET_KEY", lambda: Fernet.generate_key().decode())
JWT_SECRET: str = _ensure_secret("JWT_SECRET", lambda: secrets.token_urlsafe(48))
JWT_ALGORITHM = "HS256"

DB_PATH = Path(os.environ.get("MLOPS_DB_PATH", BASE_DIR / "mlops.db"))
STORAGE_DIR = Path(os.environ.get("MLOPS_STORAGE_DIR", BASE_DIR / "storage"))
DATASETS_DIR = STORAGE_DIR / "datasets"
MODELS_DIR = STORAGE_DIR / "models"
RUNS_DIR = STORAGE_DIR / "runs"
PIPELINES_DIR = STORAGE_DIR / "pipelines"
UPLOAD_TMP_DIR = STORAGE_DIR / "tmp"

for _d in (DATASETS_DIR, MODELS_DIR, RUNS_DIR, PIPELINES_DIR, UPLOAD_TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

MLFLOW_ENABLED = os.environ.get("MLFLOW_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
MLFLOW_TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")

APP_VERSION = "1.0.0"
MAX_UPLOAD_BYTES = 512 * 1024 * 1024  # 512 MB
