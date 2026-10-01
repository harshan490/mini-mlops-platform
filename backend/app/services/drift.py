"""Population Stability Index drift: recent prediction inputs vs. training data."""
from __future__ import annotations

import threading
import time
from bisect import bisect_left
from datetime import datetime, timedelta
from typing import Any, Optional

import numpy as np
from sqlmodel import Session, select

from app.models import Deployment, ModelVersion, PredictionLog, RegisteredModel
from app.services.features import actual_proportions, psi
from app.services.serving import load_bundle
from app.utils import utcnow

THRESHOLD = 0.25
MIN_SAMPLES = 30
_cache: dict[tuple, tuple[float, Any]] = {}
_cache_lock = threading.Lock()
CACHE_S = 15.0


def _cached(key: tuple, fn):
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_S:
            return hit[1]
    value = fn()
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def _reference(session: Session, version_id: int) -> Optional[dict[str, Any]]:
    mv = session.get(ModelVersion, version_id)
    if mv is None:
        return None
    try:
        return load_bundle(mv).get("reference")
    except Exception:  # noqa: BLE001 - version without artifact
        return None


def score_logs(ref: dict[str, Any], logs: list[tuple[dict, Any]]) -> Optional[dict[str, Any]]:
    if len(logs) < MIN_SAMPLES:
        return None
    features = []
    for name, fref in ref["features"].items():
        values = [inp.get(name) for inp, _ in logs if isinstance(inp, dict)]
        values = [v for v in values if v is not None]
        if not values:
            continue
        score = psi(fref["expected"], actual_proportions(fref, values))
        features.append({"name": name, "psi": round(score, 4), "drifted": score > THRESHOLD})
    pred_ref = ref["prediction"]
    pred_score = psi(pred_ref["expected"], actual_proportions(pred_ref, [p for _, p in logs]))
    data_score = float(np.mean([f["psi"] for f in features])) if features else 0.0
    features.sort(key=lambda f: f["psi"], reverse=True)
    return {
        "data_drift": round(data_score, 4),
        "prediction_drift": round(pred_score, 4),
        "features": features,
        "drifted": data_score > THRESHOLD or pred_score > THRESHOLD,
        "sample_size": len(logs),
    }


def _logs(session: Session, dep: Deployment, since: Optional[datetime] = None, limit: Optional[int] = None):
    q = select(PredictionLog.input, PredictionLog.prediction, PredictionLog.ts).where(
        PredictionLog.deployment_id == dep.id, PredictionLog.is_error == False,  # noqa: E712
        PredictionLog.version_id == dep.version_id)
    if since is not None:
        q = q.where(PredictionLog.ts >= since)
    q = q.order_by(PredictionLog.ts.desc())
    if limit:
        q = q.limit(limit)
    return session.exec(q).all()


def deployment_drift(session: Session, dep_id: int, n: int = 500) -> dict[str, Any]:
    def compute() -> dict[str, Any]:
        dep = session.get(Deployment, dep_id)
        if dep is None:
            raise LookupError("Deployment not found")
        model = session.get(RegisteredModel, dep.model_id)
        mv = session.get(ModelVersion, dep.version_id)
        base = {"deployment_id": dep.id, "deployment": dep.name, "model": model.name if model else "",
                "version": mv.version if mv else "", "threshold": THRESHOLD}
        ref = _reference(session, dep.version_id)
        if ref is None:
            return {**base, "available": False, "reason": "No training reference for this version"}
        rows = _logs(session, dep, limit=n)
        result = score_logs(ref, [(r[0], r[1]) for r in rows])
        if result is None:
            return {**base, "available": False, "reason": f"Need at least {MIN_SAMPLES} predictions", "sample_size": len(rows)}
        return {**base, "available": True, **result}

    return _cached(("dep", dep_id, n), compute)


SERIES_WINDOW = 300
SERIES_MIN = 100


def drift_series(session: Session, dep_ids: list[int], hours: int, bucket_hours: int) -> list[dict[str, Any]]:
    """Average drift across deployments, sampled at the end of each bucket.

    Each point scores the last ``SERIES_WINDOW`` predictions made before the
    bucket ends (a rolling window). Scoring only the predictions inside one
    bucket would inflate PSI at night, when a bucket holds a few dozen rows.
    """

    def compute() -> list[dict[str, Any]]:
        now = utcnow()
        start = now - timedelta(hours=hours)
        n_buckets = hours // bucket_hours
        sums: list[list[float]] = [[] for _ in range(n_buckets)]
        psums: list[list[float]] = [[] for _ in range(n_buckets)]
        for dep_id in dep_ids:
            dep = session.get(Deployment, dep_id)
            if dep is None:
                continue
            ref = _reference(session, dep.version_id)
            if ref is None:
                continue
            rows = list(reversed(_logs(session, dep, since=start - timedelta(hours=48))))
            stamps = [r[2] for r in rows]
            for i in range(n_buckets):
                end = start + timedelta(hours=(i + 1) * bucket_hours)
                hi = bisect_left(stamps, end)
                window = rows[max(0, hi - SERIES_WINDOW):hi]
                if len(window) < SERIES_MIN:
                    continue
                res = score_logs(ref, [(r[0], r[1]) for r in window])
                if res:
                    sums[i].append(res["data_drift"])
                    psums[i].append(res["prediction_drift"])
        out = []
        for i in range(n_buckets):
            t = start + timedelta(hours=i * bucket_hours)
            out.append({
                "ts": t.isoformat() + "Z",
                "data_drift": round(float(np.mean(sums[i])), 4) if sums[i] else None,
                "prediction_drift": round(float(np.mean(psums[i])), 4) if psums[i] else None,
            })
        return out

    return _cached(("series", tuple(sorted(dep_ids)), hours, bucket_hours), compute)
