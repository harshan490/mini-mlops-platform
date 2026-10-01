"""Small shared helpers: time, JSON-safe conversion, slugs."""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from typing import Any

import numpy as np


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite stores naive datetimes)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(microsecond=0).isoformat() + "Z"


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "item"


def safe_name(text: str) -> str:
    """Filesystem-safe folder name that keeps readable casing."""
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "", text).strip().replace(" ", "_")
    return cleaned or "item"


def to_jsonable(value: Any) -> Any:
    """Convert numpy / pandas scalars and containers into plain JSON types."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return [to_jsonable(v) for v in value.tolist()]
    if hasattr(value, "item"):
        try:
            return to_jsonable(value.item())
        except Exception:  # noqa: BLE001
            pass
    return str(value)


def pct_delta(current: float, previous: float) -> float | None:
    if previous in (0, None):
        return None
    return round((current - previous) / previous * 100.0, 1)


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=float), q))
