"""In-process model serving.

A deployment is a model version loaded into memory; "replicas" are N
independent copies of the loaded model used round-robin. Every prediction is
logged (latency, input, output) to ``PredictionLog``.
"""
from __future__ import annotations

import copy
import itertools
import threading
import time
from datetime import timedelta
from typing import Any, Optional

import joblib
import numpy as np
import pandas as pd
from sqlmodel import Session, select

from app.db import session_scope
from app.models import Deployment, DeploymentEvent, ModelVersion, PredictionLog, RegisteredModel
from app.services import storage
from app.services.activity import log_activity, raise_alert
from app.services.hub import hub
from app.services.trainer import _full_proba
from app.utils import percentile, to_jsonable, utcnow

MAX_BATCH = 1000
STAGE_MIN_S = 0.35
_bundle_cache: dict[int, dict[str, Any]] = {}
_bundle_lock = threading.Lock()


def load_bundle(version: ModelVersion) -> dict[str, Any]:
    """Load (and cache) the artifact bundle of a model version."""
    with _bundle_lock:
        if version.id in _bundle_cache:
            return _bundle_cache[version.id]
    path = storage.resolve(version.artifact_path)
    if path is None or not path.exists():
        raise FileNotFoundError(f"{version.version} has no servable artifact on disk")
    bundle = joblib.load(path)
    with _bundle_lock:
        _bundle_cache[version.id] = bundle
    return bundle


def predict_rows(bundle: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enc = bundle["encoder"]
    frame = pd.DataFrame(rows)
    X = bundle["scaler"].transform(enc.transform(frame))
    model = bundle["model"]
    out: list[dict[str, Any]] = []
    if bundle["task"] == "classification":
        classes = bundle["classes"]
        proba = _full_proba(model, X, len(classes))
        for row in proba:
            idx = int(np.argmax(row))
            out.append({"prediction": classes[idx],
                        "probabilities": {str(c): round(float(p), 4) for c, p in zip(classes, row)},
                        "confidence": round(float(row[idx]), 4)})
    else:
        mean, std = bundle["y_stats"]
        preds = np.asarray(model.predict(X), dtype=float) * std + mean
        out = [{"prediction": round(float(p), 4)} for p in preds]
    return out


def parse_payload(payload: Any) -> tuple[list[dict[str, Any]], bool]:
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object")
    if "instances" in payload:
        rows = payload["instances"]
        if not isinstance(rows, list) or not rows:
            raise ValueError("'instances' must be a non-empty list of objects")
        if len(rows) > MAX_BATCH:
            raise ValueError(f"At most {MAX_BATCH} instances per request")
        batch = True
    else:
        row = payload.get("features", payload.get("inputs", payload))
        rows, batch = [row], False
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each instance must be an object of feature -> value")
        for key, value in row.items():
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValueError(f"Feature '{key}' must be a scalar value")
    return rows, batch


class Runtime:
    def __init__(self, deployment_id: int, version_id: int, bundle: dict[str, Any], replicas: int) -> None:
        self.deployment_id = deployment_id
        self.version_id = version_id
        self.template = bundle
        self.replicas: list[dict[str, Any]] = [bundle] + [copy.deepcopy(bundle) for _ in range(max(0, replicas - 1))]
        self._rr = itertools.count()
        self.lock = threading.Lock()
        self.loaded_at = time.time()

    def scale(self, n: int) -> None:
        n = max(1, n)
        with self.lock:
            while len(self.replicas) < n:
                self.replicas.append(copy.deepcopy(self.template))
            del self.replicas[n:]

    def next_replica(self) -> tuple[int, dict[str, Any]]:
        with self.lock:
            idx = next(self._rr) % len(self.replicas)
            return idx, self.replicas[idx]


class ServingManager:
    def __init__(self) -> None:
        self.runtimes: dict[int, Runtime] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # ---------------------------------------------------------------- lifecycle
    def get(self, deployment_id: int) -> Optional[Runtime]:
        return self.runtimes.get(deployment_id)

    def unload(self, deployment_id: int) -> None:
        with self._lock:
            self.runtimes.pop(deployment_id, None)

    def load_now(self, deployment_id: int) -> None:
        """Synchronous load used at startup for deployments already Running."""
        with session_scope() as s:
            dep = s.get(Deployment, deployment_id)
            mv = s.get(ModelVersion, dep.version_id) if dep else None
            if dep is None or mv is None:
                return
            try:
                bundle = load_bundle(mv)
                with self._lock:
                    self.runtimes[dep.id] = Runtime(dep.id, mv.id, bundle, dep.replicas)
            except Exception as exc:  # noqa: BLE001
                dep.status = "Failed"
                dep.last_error = str(exc)[:300]
                s.add(dep)
                s.commit()

    def rollout(self, deployment_id: int, version_id: int, kind: str, actor_id: Optional[int], message: str) -> None:
        """Load a version with visible stages in a background thread."""
        threading.Thread(target=self._rollout, args=(deployment_id, version_id, kind, actor_id, message),
                         name=f"rollout-{deployment_id}", daemon=True).start()

    def _set_stage(self, deployment_id: int, label: str, progress: float, status: str = "Deploying") -> None:
        with session_scope() as s:
            dep = s.get(Deployment, deployment_id)
            if dep is None:
                return
            dep.stage_label = label
            dep.progress = progress
            dep.status = status
            dep.updated_at = utcnow()
            s.add(dep)
            s.commit()
        hub.publish("deployments", {"type": "progress", "deployment_id": deployment_id, "stage": label, "progress": progress, "status": status})

    def _rollout(self, deployment_id: int, version_id: int, kind: str, actor_id: Optional[int], message: str) -> None:
        def paced(start: float) -> None:
            left = STAGE_MIN_S - (time.perf_counter() - start)
            if left > 0:
                time.sleep(left)

        try:
            t = time.perf_counter()
            self._set_stage(deployment_id, "Pulling artifact", 10)
            with session_scope() as s:
                dep = s.get(Deployment, deployment_id)
                mv = s.get(ModelVersion, version_id)
                model = s.get(RegisteredModel, dep.model_id) if dep else None
                if dep is None or mv is None:
                    raise LookupError("Deployment or model version disappeared")
                path = storage.resolve(mv.artifact_path)
                if path is None or not path.exists():
                    raise FileNotFoundError(f"{model.name if model else 'model'} {mv.version} has no servable artifact")
                replicas, env, version_label = dep.replicas, dep.environment, mv.version
                model_name = model.name if model else dep.name
            paced(t)
            t = time.perf_counter()
            self._set_stage(deployment_id, "Loading model", 40)
            bundle = load_bundle(mv)
            paced(t)
            t = time.perf_counter()
            self._set_stage(deployment_id, "Starting replicas", 70)
            runtime = Runtime(deployment_id, version_id, bundle, replicas)
            paced(t)
            t = time.perf_counter()
            self._set_stage(deployment_id, "Health check", 90)
            sample = (bundle.get("sample_inputs") or [{}])[0]
            predict_rows(bundle, [sample])
            paced(t)
            with self._lock:
                self.runtimes[deployment_id] = runtime
            with session_scope() as s:
                dep = s.get(Deployment, deployment_id)
                dep.status = "Running"
                dep.progress = 100
                dep.stage_label = f"{version_label} deployed successfully"
                dep.last_error = None
                dep.updated_at = utcnow()
                s.add(dep)
                s.add(DeploymentEvent(deployment_id=deployment_id, kind=kind, version_label=version_label,
                                      environment=env, message=message, ts=utcnow()))
                s.commit()
            hub.publish("deployments", {"type": "status", "deployment_id": deployment_id, "status": "Running"})
            if kind in {"deploy", "rollout", "rollback"}:
                raise_alert("info", "deployed", "deployment", "New model deployed" if kind != "rollback" else "Deployment rolled back",
                            f"{model_name} {version_label} is live in {env}", deployment_id=deployment_id)
            log_activity(actor_id, "deployment", kind, message, f"/deployments?select={deployment_id}")
        except Exception as exc:  # noqa: BLE001
            with session_scope() as s:
                dep = s.get(Deployment, deployment_id)
                if dep:
                    dep.status = "Failed"
                    dep.last_error = str(exc)[:300]
                    dep.stage_label = "Deployment failed"
                    dep.updated_at = utcnow()
                    s.add(dep)
                    s.commit()
            hub.publish("deployments", {"type": "status", "deployment_id": deployment_id, "status": "Failed"})
            raise_alert("critical", "deploy_failed", "deployment", "Deployment failed", str(exc)[:300], deployment_id=deployment_id)

    # --------------------------------------------------------------- inference
    def predict(self, deployment_id: int, payload: Any, source: str = "live") -> dict[str, Any]:
        runtime = self.get(deployment_id)
        if runtime is None:
            raise RuntimeError("Deployment is not running")
        started = time.perf_counter()
        replica_idx, bundle = runtime.next_replica()
        rows: list[dict[str, Any]] = []
        try:
            rows, batch = parse_payload(payload)
            results = predict_rows(bundle, rows)
        except Exception as exc:  # noqa: BLE001
            latency = (time.perf_counter() - started) * 1000.0
            with session_scope() as s:
                s.add(PredictionLog(deployment_id=deployment_id, version_id=runtime.version_id, ts=utcnow(),
                                    latency_ms=round(latency, 3), input=to_jsonable(payload) if isinstance(payload, dict) else {"raw": str(payload)[:200]},
                                    prediction=None, is_error=True, error=str(exc)[:300], replica=replica_idx, source=source))
                s.commit()
            raise ValueError(str(exc)) from exc
        latency = (time.perf_counter() - started) * 1000.0
        features = set(bundle["features"])
        provided = set().union(*(r.keys() for r in rows))
        per_row = latency / len(rows)
        with session_scope() as s:
            for row, res in zip(rows, results):
                s.add(PredictionLog(deployment_id=deployment_id, version_id=runtime.version_id, ts=utcnow(),
                                    latency_ms=round(per_row, 3), input=to_jsonable(row), prediction=to_jsonable(res["prediction"]),
                                    is_error=False, replica=replica_idx, source=source))
            s.commit()
        response: dict[str, Any] = {
            "latency_ms": round(latency, 3),
            "replica": replica_idx,
            "imputed_fields": sorted(features - provided),
            "ignored_fields": sorted(provided - features),
        }
        if batch:
            response["predictions"] = to_jsonable(results)
        else:
            response.update(to_jsonable(results[0]))
        return response

    # ------------------------------------------------------------------ scaling
    def scale(self, deployment_id: int, replicas: int) -> None:
        runtime = self.get(deployment_id)
        if runtime:
            runtime.scale(replicas)

    def autoscale_tick(self) -> None:
        from app.services.system import system_monitor

        cpu = float(system_monitor.latest.get("cpu", 0.0))
        now = utcnow()
        with session_scope() as s:
            deps = s.exec(select(Deployment).where(Deployment.status == "Running", Deployment.autoscaling == True)).all()  # noqa: E712
            for dep in deps:
                rpm = len(s.exec(select(PredictionLog.id).where(PredictionLog.deployment_id == dep.id,
                                                                PredictionLog.ts >= now - timedelta(seconds=60),
                                                                PredictionLog.source != "seed")).all())
                desired = dep.replicas
                reason = ""
                if (cpu > dep.target_cpu or rpm > dep.replicas * dep.rpm_per_replica) and dep.replicas < dep.max_replicas:
                    desired = dep.replicas + 1
                    reason = f"CPU {cpu:.0f}% / {rpm} req/min above target"
                elif (cpu < dep.target_cpu * 0.5 and rpm < (dep.replicas - 1) * dep.rpm_per_replica * 0.7
                      and dep.replicas > dep.min_replicas):
                    desired = dep.replicas - 1
                    reason = f"CPU {cpu:.0f}% / {rpm} req/min below target"
                desired = max(dep.min_replicas, min(dep.max_replicas, desired))
                if desired != dep.replicas:
                    old = dep.replicas
                    dep.replicas = desired
                    dep.updated_at = now
                    s.add(dep)
                    s.add(DeploymentEvent(deployment_id=dep.id, kind="autoscale", environment=dep.environment,
                                          message=f"Autoscaled {old} → {desired} replicas ({reason})", ts=now))
                    self.scale(dep.id, desired)
            s.commit()

    def start_autoscaler(self) -> None:
        def loop() -> None:
            while not self._stop.wait(15):
                try:
                    self.autoscale_tick()
                except Exception:  # noqa: BLE001
                    pass

        threading.Thread(target=loop, name="autoscaler", daemon=True).start()

    # ---------------------------------------------------------------- simulate
    def simulate(self, deployment_id: int, n: int, drift: float, error_rate: float) -> None:
        runtime = self.get(deployment_id)
        if runtime is None:
            raise RuntimeError("Deployment is not running")
        with session_scope() as s:
            mv = s.get(ModelVersion, runtime.version_id)
            path = storage.resolve(mv.artifact_path) if mv else None
        holdout_path = path.parent / "holdout.parquet" if path else None
        if holdout_path is None or not holdout_path.exists():
            raise FileNotFoundError("This model version has no held-out rows to replay")
        bundle = runtime.template
        frame = pd.read_parquet(holdout_path)
        frame = frame.drop(columns=[bundle["target"]], errors="ignore")
        cols = [c for c in bundle["features"] if c in frame.columns]
        rng = np.random.default_rng()
        sample = frame[cols].sample(n=n, replace=True, random_state=int(rng.integers(0, 1_000_000))).reset_index(drop=True)
        if drift > 0:
            enc = bundle["encoder"]
            for col in enc.numeric:
                if col in sample.columns:
                    values = pd.to_numeric(sample[col], errors="coerce")
                    std = float(values.std() or 1.0)
                    sample[col] = values + drift * 2.0 * std + rng.normal(0, 0.25 * std * drift, len(values))
            for col, cats in enc.categorical.items():
                if col in sample.columns and cats:
                    mask = rng.random(len(sample)) < min(0.9, drift * 0.6)
                    sample.loc[mask, col] = cats[-1]
        records = [to_jsonable(r) for r in sample.to_dict(orient="records")]

        def worker() -> None:
            ok = errors = 0
            for rec in records:
                payload: Any = {"features": rec}
                if error_rate > 0 and rng.random() < error_rate:
                    payload = {"features": {k: [v] for k, v in list(rec.items())[:1]}}  # malformed: non-scalar value
                try:
                    self.predict(deployment_id, payload, source="simulate")
                    ok += 1
                except Exception:  # noqa: BLE001
                    errors += 1
                time.sleep(0.012)
            hub.publish("deployments", {"type": "simulate_done", "deployment_id": deployment_id, "ok": ok, "errors": errors})

        threading.Thread(target=worker, name=f"simulate-{deployment_id}", daemon=True).start()


def deployment_window_stats(session: Session, deployment_id: int, minutes: int = 15) -> dict[str, Any]:
    since = utcnow() - timedelta(minutes=minutes)
    rows = session.exec(select(PredictionLog.latency_ms, PredictionLog.is_error)
                        .where(PredictionLog.deployment_id == deployment_id, PredictionLog.ts >= since)).all()
    total = len(rows)
    errors = sum(1 for r in rows if r[1])
    lat = [r[0] for r in rows if not r[1]]
    return {
        "requests": total,
        "errors": errors,
        "error_rate": (errors / total * 100.0) if total else 0.0,
        "p95_ms": percentile(lat, 95),
        "avg_ms": float(np.mean(lat)) if lat else 0.0,
    }


def health_of(session: Session, dep: Deployment, manager: "ServingManager") -> str:
    if dep.status == "Stopped":
        return "Stopped"
    if dep.status == "Deploying":
        return "Deploying"
    if dep.status == "Failed" or manager.get(dep.id) is None:
        return "Down"
    stats = deployment_window_stats(session, dep.id)
    if stats["requests"] >= 20 and (stats["error_rate"] > 2.0 or stats["p95_ms"] > 600):
        return "Degraded"
    return "Healthy"


serving = ServingManager()
