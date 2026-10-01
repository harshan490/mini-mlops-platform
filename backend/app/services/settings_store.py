"""Workspace settings: one JSON document, cached in memory, persisted in SQLite."""
from __future__ import annotations

import copy
import hashlib
import hmac
import os
import threading
from typing import Any

from sqlmodel import Session, select

from app.config import STORAGE_DIR
from app.db import session_scope
from app.models import AppSettings
from app.utils import utcnow

ACCENTS = ["#3B82F6", "#8B5CF6", "#EC4899", "#22D3EE", "#10B981", "#F59E0B"]
BACKGROUNDS = ["cosmic", "violet", "aurora", "eclipse", "nebula"]
THEMES = ["dark", "light", "auto"]
COMPUTE_TARGETS = ["local", "docker", "aws", "gcp"]
SESSION_TIMEOUTS = {"1h": 1, "8h": 8, "24h": 24, "7d": 168}


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()
    return f"pbkdf2${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, _digest = stored.split("$", 2)
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


def default_settings() -> dict[str, Any]:
    return {
        "workspace": {
            "name": "Harshan's MLOps",
            "description": "My personal MLOps workspace for experiments, models and deployments.",
            "default_project": "",
            "storage_path": str(STORAGE_DIR),
        },
        "appearance": {"theme": "dark", "accent": "#3B82F6", "background": "cosmic"},
        "compute": {"target": "local", "cpu_limit": 8, "ram_limit": 16, "gpu_limit": 1, "autoscaling": True},
        "notifications": {
            "experiment_completion": True,
            "job_failures": True,
            "system_alerts": True,
            "email": False,
            "browser": True,
        },
        "security": {
            "auth_method": "local",
            "session_timeout": "24h",
            "require_auth": False,
            "two_factor": False,
            "team_access": False,
        },
        "integrations": {
            "mlflow": {"url": "http://localhost:5000"},
            "postgres": {"url": "postgresql://localhost:5432"},
            "prometheus": {"url": "http://localhost:9090"},
        },
        "training": {"pace_ms": 120},
    }


def _deep_merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class SettingsStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, Any] | None = None

    def _load(self, session: Session) -> AppSettings:
        row = session.exec(select(AppSettings).where(AppSettings.id == 1)).first()
        if row is None:
            row = AppSettings(id=1, data=default_settings())
            session.add(row)
            session.commit()
            session.refresh(row)
        return row

    def get(self) -> dict[str, Any]:
        with self._lock:
            if self._cache is None:
                with session_scope() as s:
                    row = self._load(s)
                    # Fill keys added after the row was created.
                    self._cache = _deep_merge(default_settings(), row.data or {})
            return copy.deepcopy(self._cache)

    def public(self) -> dict[str, Any]:
        data = self.get()
        data.get("security", {}).pop("admin_password_hash", None)
        data.get("security", {}).pop("admin_username", None)
        return data

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        validated = validate_patch(patch)
        with self._lock:
            with session_scope() as s:
                row = self._load(s)
                merged = _deep_merge(_deep_merge(default_settings(), row.data or {}), validated)
                row.data = merged
                row.updated_at = utcnow()
                s.add(row)
                s.commit()
                self._cache = copy.deepcopy(merged)
        return self.public()

    def reset(self) -> dict[str, Any]:
        with self._lock:
            with session_scope() as s:
                row = self._load(s)
                keep = {k: v for k, v in (row.data or {}).get("security", {}).items() if k.startswith("admin_")}
                data = default_settings()
                data["security"].update(keep)
                row.data = data
                row.updated_at = utcnow()
                s.add(row)
                s.commit()
                self._cache = copy.deepcopy(data)
        return self.public()

    def invalidate(self) -> None:
        with self._lock:
            self._cache = None

    # Admin credential (the single local account used when auth is required)
    def admin_credentials(self) -> tuple[str, str]:
        sec = self.get().get("security", {})
        username = sec.get("admin_username") or "admin"
        pw_hash = sec.get("admin_password_hash") or ""
        return username, pw_hash

    def set_admin_password(self, username: str, password: str) -> None:
        with self._lock:
            with session_scope() as s:
                row = self._load(s)
                data = _deep_merge(default_settings(), row.data or {})
                data["security"]["admin_username"] = username
                data["security"]["admin_password_hash"] = hash_password(password)
                row.data = data
                row.updated_at = utcnow()
                s.add(row)
                s.commit()
                self._cache = copy.deepcopy(data)


def _clamp_int(value: Any, lo: int, hi: int, name: str) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not lo <= number <= hi:
        raise ValueError(f"{name} must be between {lo} and {hi}")
    return number


def validate_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """Validate the editable parts; unknown sections are rejected."""
    allowed = set(default_settings())
    out: dict[str, Any] = {}
    for section, values in (patch or {}).items():
        if section not in allowed:
            raise ValueError(f"Unknown settings section: {section}")
        if not isinstance(values, dict):
            raise ValueError(f"Section {section} must be an object")
        values = dict(values)
        if section == "security":
            values = {k: v for k, v in values.items() if not k.startswith("admin_")}
            if "session_timeout" in values and values["session_timeout"] not in SESSION_TIMEOUTS:
                raise ValueError("session_timeout must be one of 1h, 8h, 24h, 7d")
        if section == "appearance":
            if "theme" in values and values["theme"] not in THEMES:
                raise ValueError("theme must be dark, light or auto")
            if "background" in values and values["background"] not in BACKGROUNDS:
                raise ValueError("unknown background preset")
            if "accent" in values and not (isinstance(values["accent"], str) and values["accent"].startswith("#") and len(values["accent"]) == 7):
                raise ValueError("accent must be a #RRGGBB colour")
        if section == "compute":
            if "target" in values and values["target"] not in COMPUTE_TARGETS:
                raise ValueError("unknown compute target")
            cpu_max = os.cpu_count() or 64
            if "cpu_limit" in values:
                values["cpu_limit"] = _clamp_int(values["cpu_limit"], 1, cpu_max, "CPU limit")
            if "ram_limit" in values:
                values["ram_limit"] = _clamp_int(values["ram_limit"], 1, 1024, "RAM limit")
            if "gpu_limit" in values:
                values["gpu_limit"] = _clamp_int(values["gpu_limit"], 0, 8, "GPU limit")
        if section == "training" and "pace_ms" in values:
            values["pace_ms"] = _clamp_int(values["pace_ms"], 0, 2000, "Training pace")
        if section == "workspace":
            for key in ("name", "description", "default_project", "storage_path"):
                if key in values and not isinstance(values[key], str):
                    raise ValueError(f"workspace.{key} must be text")
            if "name" in values and not values["name"].strip():
                raise ValueError("Workspace name cannot be empty")
        out[section] = values
    return out


settings_store = SettingsStore()
