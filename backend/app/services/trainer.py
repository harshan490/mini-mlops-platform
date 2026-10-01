"""Real training jobs with per-epoch progress, cooperative cancel and artifacts.

"Epochs" are real incremental training steps for every algorithm:

* Random Forest     - warm_start: each epoch adds trees
* XGBoost           - each epoch adds boosting rounds to the same booster
* Logistic Regression - SGD (log-loss) with one pass of mini-batches per epoch
* MLP               - ``partial_fit``: one pass over the data per epoch

Metrics are computed on a held-out validation split after every epoch.
"""
from __future__ import annotations

import json
import math
import random
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional

import joblib
import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype
from sklearn.metrics import accuracy_score, f1_score, log_loss, mean_squared_error, precision_score, r2_score, recall_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sqlmodel import Session, select

from app.config import MLFLOW_ENABLED, MLFLOW_TRACKING_URI, RUNS_DIR
from app.db import session_scope
from app.models import Dataset, DatasetVersion, Run, RunMetric
from app.services import storage
from app.services.activity import log_activity, raise_alert
from app.services.features import BoosterModel, FeatureEncoder, build_reference, load_frame
from app.services.hub import hub
from app.services.settings_store import settings_store
from app.utils import iso, to_jsonable, utcnow

ALGORITHMS: dict[str, dict[str, Any]] = {
    "random_forest": {"label": "Random Forest", "framework": "Scikit-learn", "default_lr": None,
                      "description": "Bagged decision trees; each epoch adds trees (warm start)."},
    "xgboost": {"label": "XGBoost", "framework": "XGBoost", "default_lr": 0.1,
                "description": "Gradient-boosted trees; each epoch adds boosting rounds."},
    "logistic_regression": {"label": "Logistic Regression", "framework": "Scikit-learn", "default_lr": 0.01,
                            "description": "Linear classifier trained by SGD on log-loss."},
    "mlp": {"label": "MLP", "framework": "Scikit-learn", "default_lr": 0.001,
            "description": "Two-layer neural network (64-32) trained with partial_fit."},
}
MAX_TRAIN_ROWS = 60_000
EVAL_ROWS = 5_000
BATCH_SIZES = [8, 16, 32, 64, 128]
OPTIMIZERS = ["Adam", "SGD", "AdamW", "RMSprop"]


class Cancelled(Exception):
    pass


def gpu_name() -> Optional[str]:
    try:
        import pynvml

        pynvml.nvmlInit()
        name = pynvml.nvmlDeviceGetName(pynvml.nvmlDeviceGetHandleByIndex(0))
        return name.decode() if isinstance(name, bytes) else str(name)
    except Exception:  # noqa: BLE001
        return None


_GPU_NAME = gpu_name()


def next_run_code(session: Session) -> str:
    highest = 0
    for code in session.exec(select(Run.code)).all():
        m = re.fullmatch(r"exp-(\d+)", code or "")
        if m:
            highest = max(highest, int(m.group(1)))
    return f"exp-{highest + 1}"


def normalise_params(algorithm: str, params: dict[str, Any] | None) -> dict[str, Any]:
    if algorithm not in ALGORITHMS:
        raise ValueError(f"Unknown algorithm '{algorithm}'. Choose one of: {', '.join(ALGORITHMS)}")
    p = dict(params or {})
    info = ALGORITHMS[algorithm]
    out: dict[str, Any] = {}
    epochs = int(p.get("epochs", 100))
    if not 1 <= epochs <= 1000:
        raise ValueError("epochs must be between 1 and 1000")
    out["epochs"] = epochs
    batch = int(p.get("batch_size", 32))
    if batch not in BATCH_SIZES:
        raise ValueError(f"batch_size must be one of {BATCH_SIZES}")
    out["batch_size"] = batch
    lr = p.get("learning_rate", info["default_lr"])
    if info["default_lr"] is not None:
        lr = float(lr)
        if not 1e-6 <= lr <= 1e-1 + 1e-12:
            raise ValueError("learning_rate must be between 1e-6 and 1e-1")
        out["learning_rate"] = lr
    optimizer = str(p.get("optimizer", "Adam"))
    if optimizer not in OPTIMIZERS:
        raise ValueError(f"optimizer must be one of {OPTIMIZERS}")
    out["optimizer"] = optimizer
    if algorithm in {"random_forest", "xgboost"}:
        if p.get("max_depth") not in (None, ""):
            md = int(p["max_depth"])
            if not 1 <= md <= 32:
                raise ValueError("max_depth must be between 1 and 32")
            out["max_depth"] = md
        if p.get("n_estimators") not in (None, ""):
            ne = int(p["n_estimators"])
            if not 1 <= ne <= 2000:
                raise ValueError("n_estimators must be between 1 and 2000")
            out["n_estimators"] = ne
    if p.get("data_path"):
        out["data_path"] = str(p["data_path"])
    return out


def _full_proba(model: Any, X: np.ndarray, k: int) -> np.ndarray:
    proba = model.predict_proba(X)
    classes = getattr(model, "classes_", None)
    if classes is None or len(classes) == k:
        return proba
    out = np.zeros((len(X), k))
    for j, c in enumerate(classes):
        out[:, int(c)] = proba[:, j]
    return out


class Trainer:
    def __init__(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="trainer")
        self._cancel: dict[int, threading.Event] = {}
        self._lock = threading.Lock()
        self.active: set[int] = set()

    # ------------------------------------------------------------------ control
    def _flag(self, run_id: int) -> threading.Event:
        with self._lock:
            return self._cancel.setdefault(run_id, threading.Event())

    def submit(self, run_id: int) -> None:
        self._flag(run_id)
        self.executor.submit(self._safe_execute, run_id)

    def submit_autotune(self, parent_id: int) -> None:
        self._flag(parent_id)
        self.executor.submit(self._safe_autotune, parent_id)

    def stop(self, run_id: int) -> bool:
        """Cooperative cancel. Returns True if a stop was requested."""
        with session_scope() as s:
            run = s.get(Run, run_id)
            if run is None or run.status not in {"Queued", "Training"}:
                return False
            children = s.exec(select(Run).where(Run.parent_id == run_id, Run.status.in_(["Queued", "Training"]))).all()
            ids = [run_id] + [c.id for c in children]
        for rid in ids:
            self._flag(rid).set()
        return True

    def recover_interrupted(self) -> int:
        """Runs left 'Training' by a previous process can never finish."""
        with session_scope() as s:
            stale = s.exec(select(Run).where(Run.status.in_(["Queued", "Training"]))).all()
            for run in stale:
                run.status = "Failed"
                run.error = "Interrupted: the server restarted while this run was active."
                run.finished_at = run.finished_at or utcnow()
                s.add(run)
            s.commit()
            return len(stale)

    def _safe_execute(self, run_id: int) -> None:
        try:
            self.execute(run_id)
        except Exception:  # noqa: BLE001 - execute already records failures
            pass

    def _safe_autotune(self, parent_id: int) -> None:
        try:
            self.execute_autotune(parent_id)
        except Exception:  # noqa: BLE001
            pass

    # --------------------------------------------------------------------- data
    @staticmethod
    def _resolve_data(s: Session, run: Run) -> tuple[Path, str]:
        if run.params.get("data_path"):
            path = storage.resolve(run.params["data_path"])
            if path is None or not path.exists():
                raise ValueError("Pipeline feature file is missing")
            ds = s.get(Dataset, run.dataset_id) if run.dataset_id else None
            target = run.target or (ds.target_column if ds else None)
            if not target:
                raise ValueError("No target column configured")
            return path, target
        ds = s.get(Dataset, run.dataset_id) if run.dataset_id else None
        if ds is None:
            raise ValueError("Dataset not found")
        version = run.dataset_version or ds.current_version
        dv = s.exec(select(DatasetVersion).where(DatasetVersion.dataset_id == ds.id, DatasetVersion.version == version)).first()
        path = storage.resolve(dv.file_path) if dv else None
        if dv is None or path is None or not path.exists():
            raise ValueError(f"Dataset '{ds.name}' v{version} has no data file on disk (metadata-only dataset).")
        target = run.target or ds.target_column
        if not target:
            raise ValueError(f"Dataset '{ds.name}' has no target column; set one on the dataset first.")
        return path, target

    @staticmethod
    def prepare(df: pd.DataFrame, target: str, algorithm: str) -> dict[str, Any]:
        if target not in df.columns:
            raise ValueError(f"Target column '{target}' not found. Columns: {', '.join(map(str, df.columns[:20]))}")
        df = df.dropna(subset=[target])
        if len(df) > MAX_TRAIN_ROWS:
            df = df.sample(MAX_TRAIN_ROWS, random_state=42)
        if len(df) < 20:
            raise ValueError("Need at least 20 labelled rows to train")
        y_raw = df[target]
        X_raw = df.drop(columns=[target])
        task = "classification" if (not is_numeric_dtype(y_raw) or y_raw.nunique() <= 15) else "regression"
        if task == "regression" and algorithm == "logistic_regression":
            raise ValueError("Logistic Regression needs a categorical target; use Random Forest, XGBoost or MLP for a numeric target.")

        classes: list[Any] = []
        if task == "classification":
            classes = sorted(pd.unique(y_raw).tolist(), key=lambda v: (str(type(v)), v) if not isinstance(v, str) else ("str", v))
            if len(classes) < 2:
                raise ValueError("Target has a single class; nothing to learn")
            index = {c: i for i, c in enumerate(classes)}
            y = y_raw.map(index).to_numpy(dtype=int)
            counts = np.bincount(y)
            stratify = y if counts.min() >= 2 else None
        else:
            y = y_raw.to_numpy(dtype=float)
            stratify = None

        Xtr_raw, Xva_raw, ytr, yva = train_test_split(X_raw, y, test_size=0.2, random_state=42, stratify=stratify)
        encoder = FeatureEncoder().fit(Xtr_raw)
        scaler = StandardScaler()
        Xtr = scaler.fit_transform(encoder.transform(Xtr_raw))
        Xva = scaler.transform(encoder.transform(Xva_raw))
        y_stats = None
        if task == "regression":
            mean, std = float(np.mean(ytr)), float(np.std(ytr) or 1.0)
            y_stats = (mean, std)
            ytr = (ytr - mean) / std
            yva = (yva - mean) / std
        holdout = Xva_raw.copy()
        holdout[target] = y_raw.loc[Xva_raw.index]
        return {
            "task": task, "classes": classes, "encoder": encoder, "scaler": scaler, "y_stats": y_stats,
            "Xtr": Xtr, "Xva": Xva, "ytr": ytr, "yva": yva, "Xtr_raw": Xtr_raw, "Xva_raw": Xva_raw,
            "holdout": holdout, "target": target,
        }

    # ----------------------------------------------------------------- training
    def _fit_loop(self, run: Run, data: dict[str, Any], pace_s: float, cancel: threading.Event,
                  emit: Callable[[int, dict[str, Any], float, float], None]) -> tuple[Any, dict[str, Any], str]:
        algo = run.algorithm
        p = run.params
        epochs = int(p["epochs"])
        task = data["task"]
        k = len(data["classes"])
        Xtr, Xva, ytr, yva = data["Xtr"], data["Xva"], data["ytr"], data["yva"]
        rng = np.random.default_rng(42)
        eval_idx = rng.choice(len(Xtr), size=min(EVAL_ROWS, len(Xtr)), replace=False)
        Xtr_eval, ytr_eval = Xtr[eval_idx], ytr[eval_idx]
        compute = settings_store.get()["compute"]
        n_jobs = max(1, int(compute.get("cpu_limit", 4)))
        device = "CPU"

        model: Any
        step: Callable[[int], None]

        if algo == "random_forest":
            from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

            per_epoch = max(1, int(round(p.get("n_estimators", 2 * epochs) / epochs)))
            cls = RandomForestClassifier if task == "classification" else RandomForestRegressor
            model = cls(n_estimators=per_epoch, warm_start=True, n_jobs=n_jobs, random_state=42, max_depth=p.get("max_depth"))

            def step(e: int) -> None:
                model.set_params(n_estimators=per_epoch * e)
                model.fit(Xtr, ytr)

        elif algo == "xgboost":
            import xgboost as xgb

            use_gpu = int(compute.get("gpu_limit", 0)) >= 1 and _GPU_NAME is not None
            device = f"GPU ({_GPU_NAME})" if use_gpu else "CPU"
            xparams: dict[str, Any] = {
                "eta": float(p.get("learning_rate", 0.1)),
                "max_depth": int(p.get("max_depth", 6)),
                "nthread": n_jobs,
                "tree_method": "hist",
                "device": "cuda" if use_gpu else "cpu",
                "seed": 42,
                "verbosity": 0,
            }
            if task == "classification":
                if k == 2:
                    xparams.update(objective="binary:logistic", eval_metric="logloss")
                else:
                    xparams.update(objective="multi:softprob", num_class=k, eval_metric="mlogloss")
            else:
                xparams.update(objective="reg:squarederror")
            dtrain = xgb.DMatrix(Xtr, label=ytr)
            rounds = max(1, int(round(p.get("n_estimators", epochs) / epochs)))
            holder = {"booster": None}
            model = BoosterModel(None, task, k)

            def step(e: int) -> None:
                try:
                    holder["booster"] = xgb.train(xparams, dtrain, num_boost_round=rounds, xgb_model=holder["booster"])
                except Exception:  # noqa: BLE001 - GPU unavailable mid-run: continue on CPU
                    if xparams["device"] != "cpu":
                        xparams["device"] = "cpu"
                        holder["booster"] = xgb.train(xparams, dtrain, num_boost_round=rounds, xgb_model=holder["booster"])
                    else:
                        raise
                model.booster = holder["booster"]

        elif algo == "logistic_regression":
            from sklearn.linear_model import SGDClassifier

            model = SGDClassifier(loss="log_loss", learning_rate="constant", eta0=float(p["learning_rate"]), alpha=1e-4, random_state=42)
            batch = int(p["batch_size"])
            classes_idx = np.arange(k)

            def step(e: int) -> None:
                order = rng.permutation(len(Xtr))
                for start in range(0, len(order), batch):
                    if cancel.is_set():
                        raise Cancelled()
                    idx = order[start:start + batch]
                    model.partial_fit(Xtr[idx], ytr[idx], classes=classes_idx)

        elif algo == "mlp":
            from sklearn.neural_network import MLPClassifier, MLPRegressor

            solver = "sgd" if p.get("optimizer") == "SGD" else "adam"
            kwargs = dict(hidden_layer_sizes=(64, 32), solver=solver, learning_rate_init=float(p["learning_rate"]),
                          batch_size=min(int(p["batch_size"]), len(Xtr)), random_state=42)
            if task == "classification":
                model = MLPClassifier(**kwargs)
                classes_idx = np.arange(k)

                def step(e: int) -> None:
                    model.partial_fit(Xtr, ytr, classes=classes_idx)
            else:
                model = MLPRegressor(**kwargs)

                def step(e: int) -> None:
                    model.partial_fit(Xtr, ytr)
        else:
            raise ValueError(f"Unknown algorithm {algo}")

        def evaluate() -> dict[str, Any]:
            if task == "classification":
                ptr = _full_proba(model, Xtr_eval, k)
                pva = _full_proba(model, Xva, k)
                pred_va = np.argmax(pva, axis=1)
                return {
                    "train_loss": float(log_loss(ytr_eval, ptr, labels=list(range(k)))),
                    "val_loss": float(log_loss(yva, pva, labels=list(range(k)))),
                    "train_acc": float(accuracy_score(ytr_eval, np.argmax(ptr, axis=1))),
                    "val_acc": float(accuracy_score(yva, pred_va)),
                    "f1": float(f1_score(yva, pred_va, average="macro", zero_division=0)),
                }
            pred_tr = model.predict(Xtr_eval)
            pred_va = model.predict(Xva)
            return {
                "train_loss": float(mean_squared_error(ytr_eval, pred_tr)),
                "val_loss": float(mean_squared_error(yva, pred_va)),
                "train_acc": float(max(0.0, r2_score(ytr_eval, pred_tr))),
                "val_acc": float(max(0.0, r2_score(yva, pred_va))),
                "f1": None,
            }

        started = time.perf_counter()
        last: dict[str, Any] = {}
        ckpt_every = max(10, epochs // 5)
        ckpt_dir = RUNS_DIR / run.code / "checkpoints"
        for epoch in range(1, epochs + 1):
            if cancel.is_set():
                raise Cancelled()
            t0 = time.perf_counter()
            step(epoch)
            last = evaluate()
            for key in ("train_loss", "val_loss"):
                if last[key] is not None and (math.isnan(last[key]) or math.isinf(last[key])):
                    raise ValueError("Training diverged (loss is NaN/inf); lower the learning rate.")
            spent = time.perf_counter() - t0
            if pace_s > spent:
                if cancel.wait(pace_s - spent):
                    raise Cancelled()
            elapsed = time.perf_counter() - started
            eta = elapsed / epoch * (epochs - epoch)
            if epoch % ckpt_every == 0 or epoch == epochs:
                ckpt_dir.mkdir(parents=True, exist_ok=True)
                joblib.dump(model, ckpt_dir / "checkpoint.joblib")
            emit(epoch, last, elapsed, eta)
        # Serving is single-row and latency-bound: predict on CPU without a thread pool.
        if algo == "xgboost" and holder["booster"] is not None:
            holder["booster"].set_param({"device": "cpu", "nthread": 1})
        elif algo == "random_forest":
            model.set_params(n_jobs=1)
        return model, last, device

    # ------------------------------------------------------------------ execute
    def execute(self, run_id: int, pace_s: Optional[float] = None,
                on_epoch: Optional[Callable[[Run, int, dict[str, Any]], None]] = None) -> str:
        cancel = self._flag(run_id)
        with session_scope() as s:
            run = s.get(Run, run_id)
            if run is None:
                return "Missing"
            if run.status != "Queued":
                return run.status
            if cancel.is_set():
                run.status = "Stopped"
                run.finished_at = utcnow()
                s.add(run)
                s.commit()
                hub.publish(f"run:{run_id}", {"type": "status", "run_id": run_id, "status": "Stopped"})
                return "Stopped"
            run.status = "Training"
            run.started_at = utcnow()
            s.add(run)
            s.commit()
            s.refresh(run)
            run_snapshot = Run.model_validate(run.model_dump())
        self.active.add(run_id)
        hub.publish(f"run:{run_id}", {"type": "status", "run_id": run_id, "status": "Training"})
        hub.publish("runs", {"type": "status", "run_id": run_id, "status": "Training", "code": run_snapshot.code})
        if pace_s is None:
            pace_s = settings_store.get()["training"].get("pace_ms", 120) / 1000.0

        status, error, final_metrics, device = "Completed", None, {}, run_snapshot.device
        artifact_rel, ckpt_rel = None, None
        t_start = time.perf_counter()
        try:
            with session_scope() as s:
                path, target = self._resolve_data(s, run_snapshot)
            df = load_frame(path)
            data = self.prepare(df, target, run_snapshot.algorithm)
            with session_scope() as s:
                run = s.get(Run, run_id)
                run.task = data["task"]
                run.target = target
                s.add(run)
                s.commit()

            def emit(epoch: int, m: dict[str, Any], elapsed: float, eta: float) -> None:
                total = int(run_snapshot.params["epochs"])
                progress = round(epoch / total * 100.0, 2)
                with session_scope() as s2:
                    s2.add(RunMetric(run_id=run_id, epoch=epoch, train_loss=m["train_loss"], val_loss=m["val_loss"],
                                     train_acc=m["train_acc"], val_acc=m["val_acc"], f1=m["f1"], ts=utcnow()))
                    r = s2.get(Run, run_id)
                    r.epoch = epoch
                    r.progress = progress
                    r.duration_s = round(elapsed, 2)
                    r.metrics = {"accuracy": m["val_acc"], "loss": m["train_loss"], "val_loss": m["val_loss"],
                                 "train_acc": m["train_acc"], "f1": m["f1"], "eta_s": round(eta, 1)}
                    s2.add(r)
                    s2.commit()
                msg = {"type": "epoch", "run_id": run_id, "code": run_snapshot.code, "epoch": epoch, "total_epochs": total,
                       "progress": progress, "elapsed_s": round(elapsed, 2), "eta_s": round(eta, 1), **m}
                hub.publish(f"run:{run_id}", msg)
                hub.publish("runs", msg)
                if on_epoch:
                    on_epoch(run_snapshot, epoch, m)

            model, last, device = self._fit_loop(run_snapshot, data, pace_s, cancel, emit)
            final_metrics = self._final_metrics(model, data, last)
            artifact_rel, ckpt_rel = self._save_artifact(run_snapshot, model, data, final_metrics)
            self._log_mlflow(run_snapshot, final_metrics)
        except Cancelled:
            status = "Stopped"
        except Exception as exc:  # noqa: BLE001
            status, error = "Failed", str(exc)[:500]
        finally:
            self.active.discard(run_id)

        duration = round(time.perf_counter() - t_start, 2)
        with session_scope() as s:
            run = s.get(Run, run_id)
            run.status = status
            run.error = error
            run.finished_at = utcnow()
            run.duration_s = duration
            run.device = device
            if device.startswith("GPU"):
                run.gpu_hours = round(duration / 3600.0, 4)
            if status == "Completed":
                run.metrics = final_metrics
                run.progress = 100.0
                run.artifact_path = artifact_rel
                run.checkpoint_path = ckpt_rel
            else:
                ckpt = RUNS_DIR / run.code / "checkpoints"
                run.checkpoint_path = storage.rel(ckpt) if ckpt.exists() else None
            s.add(run)
            s.commit()
            s.refresh(run)
            owner_id, code, label, kind = run.owner_id, run.code, run.algorithm_label, run.kind
        hub.publish(f"run:{run_id}", {"type": "status", "run_id": run_id, "status": status, "error": error, "metrics": final_metrics})
        hub.publish("runs", {"type": "status", "run_id": run_id, "status": status, "code": code})
        if kind != "trial":
            if status == "Completed":
                acc = final_metrics.get("accuracy")
                raise_alert("success", "run_completed", "experiment", f"{code} completed",
                            f"{label} finished with accuracy {acc:.3f}" if acc is not None else f"{label} finished")
                log_activity(owner_id, "experiment", "completed", f"Run {code} ({label}) completed", f"/experiments?select={run_id}")
            elif status == "Failed":
                raise_alert("critical", "run_failed", "experiment", f"{code} failed", error or "Training failed")
                log_activity(owner_id, "experiment", "failed", f"Run {code} ({label}) failed: {error}", f"/experiments?select={run_id}")
            elif status == "Stopped":
                log_activity(owner_id, "experiment", "stopped", f"Run {code} ({label}) was stopped", f"/experiments?select={run_id}")
        return status

    @staticmethod
    def _final_metrics(model: Any, data: dict[str, Any], last: dict[str, Any]) -> dict[str, Any]:
        task = data["task"]
        metrics: dict[str, Any] = {
            "accuracy": round(last["val_acc"], 4),
            "loss": round(last["train_loss"], 4),
            "val_loss": round(last["val_loss"], 4),
            "train_acc": round(last["train_acc"], 4),
            "task": task,
            "n_train": int(len(data["Xtr"])),
            "n_val": int(len(data["Xva"])),
            "n_features": int(data["Xtr"].shape[1]),
        }
        if task == "classification":
            k = len(data["classes"])
            pred = np.argmax(_full_proba(model, data["Xva"], k), axis=1)
            metrics["f1"] = round(float(f1_score(data["yva"], pred, average="macro", zero_division=0)), 4)
            metrics["precision"] = round(float(precision_score(data["yva"], pred, average="macro", zero_division=0)), 4)
            metrics["recall"] = round(float(recall_score(data["yva"], pred, average="macro", zero_division=0)), 4)
        else:
            metrics["r2"] = metrics["accuracy"]
            metrics["f1"] = None
        return metrics

    @staticmethod
    def _save_artifact(run: Run, model: Any, data: dict[str, Any], metrics: dict[str, Any]) -> tuple[str, str]:
        out_dir = RUNS_DIR / run.code
        out_dir.mkdir(parents=True, exist_ok=True)
        task = data["task"]
        enc: FeatureEncoder = data["encoder"]
        Xva_s = data["Xva"]
        if task == "classification":
            idx = np.argmax(_full_proba(model, Xva_s, len(data["classes"])), axis=1)
            decoded = [data["classes"][i] for i in idx]
        else:
            mean, std = data["y_stats"]
            decoded = (np.asarray(model.predict(Xva_s), dtype=float) * std + mean).tolist()
        reference = build_reference(data["Xva_raw"], enc, decoded, task)
        sample_inputs = [to_jsonable(r) for r in data["Xva_raw"][enc.input_columns].head(3).to_dict(orient="records")]
        bundle = {
            "model": model, "encoder": enc, "scaler": data["scaler"], "y_stats": data["y_stats"], "task": task,
            "classes": to_jsonable(data["classes"]), "target": data["target"], "algorithm": run.algorithm,
            "algorithm_label": run.algorithm_label, "features": enc.input_columns, "feature_names": enc.feature_names,
            "reference": reference, "sample_inputs": sample_inputs, "metrics": metrics, "run_code": run.code,
            "created_at": iso(utcnow()),
        }
        model_path = out_dir / "model.joblib"
        joblib.dump(bundle, model_path)
        data["holdout"].head(2000).to_parquet(out_dir / "holdout.parquet", index=False)
        meta = {k: bundle[k] for k in ("task", "classes", "target", "algorithm", "features", "metrics", "run_code", "created_at")}
        meta["params"] = run.params
        (out_dir / "metadata.json").write_text(json.dumps(to_jsonable(meta), indent=2), encoding="utf-8")
        return storage.rel(model_path), storage.rel(out_dir / "checkpoints")

    @staticmethod
    def _log_mlflow(run: Run, metrics: dict[str, Any]) -> None:
        if not MLFLOW_ENABLED:
            return
        try:
            import mlflow

            mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
            mlflow.set_experiment("mini-mlops")
            with mlflow.start_run(run_name=run.code):
                mlflow.log_params({k: v for k, v in run.params.items() if k != "data_path"})
                mlflow.log_metrics({k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))})
        except Exception:  # noqa: BLE001 - MLflow is optional
            pass

    # ---------------------------------------------------------------- autotune
    @staticmethod
    def sample_params(algorithm: str, rng: random.Random, epochs: int) -> dict[str, Any]:
        p: dict[str, Any] = {"epochs": epochs, "batch_size": rng.choice([16, 32, 64, 128]), "optimizer": "Adam"}
        if algorithm == "xgboost":
            p["learning_rate"] = round(10 ** rng.uniform(-2, -0.53), 5)  # 0.01 .. 0.3
            p["max_depth"] = rng.randint(3, 10)
        elif algorithm == "random_forest":
            p["max_depth"] = rng.choice([None, 4, 6, 8, 12, 16])
            p["n_estimators"] = rng.choice([50, 100, 150, 200, 300])
            if p["max_depth"] is None:
                p.pop("max_depth")
        elif algorithm == "logistic_regression":
            p["learning_rate"] = round(10 ** rng.uniform(-3, -1), 6)
        elif algorithm == "mlp":
            p["learning_rate"] = round(10 ** rng.uniform(-4, -2), 6)
            p["optimizer"] = rng.choice(["Adam", "SGD"])
        return p

    def execute_autotune(self, parent_id: int) -> str:
        cancel = self._flag(parent_id)
        with session_scope() as s:
            parent = s.get(Run, parent_id)
            if parent is None or parent.status != "Queued":
                return parent.status if parent else "Missing"
            parent.status = "Training"
            parent.started_at = utcnow()
            s.add(parent)
            s.commit()
            s.refresh(parent)
            snap = Run.model_validate(parent.model_dump())
        self.active.add(parent_id)
        hub.publish(f"run:{parent_id}", {"type": "status", "run_id": parent_id, "status": "Training"})
        trials = int(snap.params.get("trials", 6))
        epochs = int(snap.params.get("trial_epochs", 20))
        rng = random.Random(parent_id)
        pace = settings_store.get()["training"].get("pace_ms", 120) / 2000.0
        t_start = time.perf_counter()
        results: list[tuple[float, int]] = []
        status = "Completed"
        try:
            for i in range(1, trials + 1):
                if cancel.is_set():
                    raise Cancelled()
                params = normalise_params(snap.algorithm, self.sample_params(snap.algorithm, rng, epochs))
                with session_scope() as s:
                    child = Run(code=f"{snap.code}-t{i}", name=f"{snap.name} · trial {i}", algorithm=snap.algorithm,
                                algorithm_label=snap.algorithm_label, framework=snap.framework, kind="trial",
                                dataset_id=snap.dataset_id, dataset_version=snap.dataset_version, target=snap.target,
                                params=params, total_epochs=params["epochs"], parent_id=parent_id,
                                owner_id=snap.owner_id, device=snap.device)
                    s.add(child)
                    s.commit()
                    s.refresh(child)
                    child_id = child.id

                def on_epoch(_r: Run, epoch: int, m: dict[str, Any], i: int = i) -> None:
                    progress = round(((i - 1) + epoch / epochs) / trials * 100.0, 2)
                    hub.publish(f"run:{parent_id}", {"type": "progress", "run_id": parent_id, "trial": i, "trials": trials,
                                                     "trial_epoch": epoch, "progress": progress, "child_id": child_id})

                child_status = self.execute(child_id, pace_s=pace, on_epoch=on_epoch)
                with session_scope() as s:
                    child = s.get(Run, child_id)
                    m = child.metrics or {}
                    if child_status == "Completed":
                        results.append((float(m.get("accuracy", 0.0)), child_id))
                        s.add(RunMetric(run_id=parent_id, epoch=i, train_loss=m.get("loss"), val_loss=m.get("val_loss"),
                                        train_acc=m.get("train_acc"), val_acc=m.get("accuracy"), f1=m.get("f1"), ts=utcnow()))
                    p = s.get(Run, parent_id)
                    p.epoch = i
                    p.progress = round(i / trials * 100.0, 2)
                    p.duration_s = round(time.perf_counter() - t_start, 2)
                    best = max(results) if results else None
                    if best:
                        best_child = s.get(Run, best[1])
                        p.metrics = {**(best_child.metrics or {}), "best_trial": best_child.code, "best_params": best_child.params}
                    s.add(p)
                    s.commit()
                hub.publish(f"run:{parent_id}", {"type": "epoch", "run_id": parent_id, "epoch": i, "total_epochs": trials,
                                                 "progress": round(i / trials * 100.0, 2), "train_loss": m.get("loss"),
                                                 "val_loss": m.get("val_loss"), "train_acc": m.get("train_acc"),
                                                 "val_acc": m.get("accuracy"), "f1": m.get("f1"),
                                                 "elapsed_s": round(time.perf_counter() - t_start, 2), "eta_s": None})
                if child_status == "Stopped":
                    raise Cancelled()
            if not results:
                raise ValueError("No trial completed successfully")
        except Cancelled:
            status = "Stopped"
        except Exception as exc:  # noqa: BLE001
            status = "Failed"
            with session_scope() as s:
                p = s.get(Run, parent_id)
                p.error = str(exc)[:500]
                s.add(p)
                s.commit()
        finally:
            self.active.discard(parent_id)
        with session_scope() as s:
            p = s.get(Run, parent_id)
            p.status = status if (status != "Stopped" or not results) else "Stopped"
            p.finished_at = utcnow()
            p.duration_s = round(time.perf_counter() - t_start, 2)
            if results:
                best_child = s.get(Run, max(results)[1])
                p.artifact_path = best_child.artifact_path
                p.checkpoint_path = best_child.checkpoint_path
                p.task = best_child.task
                p.device = best_child.device
                p.gpu_hours = round(sum((s.get(Run, cid).gpu_hours or 0.0) for _, cid in results), 4)
            s.add(p)
            s.commit()
            owner_id, code, final_status, metrics = p.owner_id, p.code, p.status, p.metrics
        hub.publish(f"run:{parent_id}", {"type": "status", "run_id": parent_id, "status": final_status, "metrics": metrics})
        hub.publish("runs", {"type": "status", "run_id": parent_id, "status": final_status, "code": code})
        if final_status == "Completed":
            raise_alert("success", "run_completed", "experiment", f"{code} auto-tune finished",
                        f"Best trial {metrics.get('best_trial')} reached accuracy {metrics.get('accuracy', 0):.3f}")
            log_activity(owner_id, "experiment", "autotune", f"Auto-tune {code} finished (best {metrics.get('best_trial')})",
                         f"/experiments?select={parent_id}")
        elif final_status == "Failed":
            raise_alert("critical", "run_failed", "experiment", f"{code} auto-tune failed", "No trial completed")
        return final_status

    # ---------------------------------------------------------------- deletion
    @staticmethod
    def delete_files(code: str) -> None:
        path = RUNS_DIR / code
        if path.exists() and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


trainer = Trainer()
