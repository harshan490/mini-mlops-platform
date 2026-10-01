"""Demo data so the platform looks like the mockups on first launch.

    python -m app.seed            # seed an empty database (no-op otherwise)
    python -m app.seed --reset    # wipe DB + generated storage, then seed again (stop the server first)

What is real and what is history
--------------------------------
* Real: the 5 tabular datasets (files on disk), every run whose algorithm is
  Random Forest / XGBoost / Logistic Regression / MLP (trained here, with
  artifacts), the models registered from them and the 3 deployments.
* Seeded history (source="seed"): the older runs and the LSTM / BERT / YOLOv8
  entries (PyTorch is not installed), image/text/audio datasets that exist
  only as metadata, 7 days of prediction logs (inputs are real held-out rows,
  predictions come from the real models, latencies are sampled around the
  latency measured on this machine) and 48 h of host metrics.
"""
from __future__ import annotations

import argparse
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image
from sqlalchemy import delete
from sqlmodel import select

from app.config import DATASETS_DIR, MODELS_DIR, PIPELINES_DIR, RUNS_DIR, UPLOAD_TMP_DIR
from app.db import drop_db, init_db, session_scope
from app.models import (Activity, Alert, ApiKey, Dataset, DatasetVersion, Deployment, DeploymentEvent, ModelVersion,
                        Pipeline, PipelineLog, PipelineRun, PipelineVersion, PredictionLog, RegisteredModel, Run,
                        RunMetric, SystemMetric, User)
from app.services import registry, storage
from app.services.datasets import profile_tabular
from app.services.pipeline_runner import dump_spec, parse_spec
from app.services.serving import load_bundle, predict_rows
from app.services.settings_store import settings_store
from app.services.trainer import ALGORITHMS, normalise_params, trainer
from app.utils import to_jsonable, utcnow

RNG = np.random.default_rng(2026)


def ago(**kw: float) -> datetime:
    return utcnow() - timedelta(**kw)


# ---------------------------------------------------------------- datasets
def make_travel(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    age = rng.integers(18, 71, n)
    budget = np.round(rng.lognormal(7.6, 0.6, n)).clip(300, 12000)
    days = rng.integers(2, 22, n)
    group = rng.integers(1, 7, n)
    nature, culture, nightlife = rng.random(n), rng.random(n), rng.random(n)
    climate = rng.uniform(-1, 1, n)
    season = rng.choice(["winter", "spring", "summer", "autumn"], n)
    ttype = rng.choice(["solo", "couple", "family", "friends"], n, p=[0.2, 0.3, 0.3, 0.2])
    past = rng.poisson(4, n)
    scores = np.column_stack([
        1.3 * climate + 0.9 * (season == "summer") + 0.6 * nightlife + 0.35 * (ttype == "family"),
        1.6 * nature - 0.9 * climate + 0.6 * (season == "winter") + 0.03 * days - 0.35,
        1.4 * nightlife + 0.5 * (budget > 3000) + 0.45 * (ttype == "friends") - 0.5 * nature + 0.45,
        1.7 * culture + 0.025 * (age - 40) + 0.35 * (ttype == "couple"),
    ]) + rng.gumbel(0, 0.1, (n, 4))
    labels = np.array(["beach", "mountain", "city", "heritage"])[scores.argmax(axis=1)]
    return pd.DataFrame({
        "age": age, "budget_usd": budget, "trip_days": days, "group_size": group,
        "nature_score": nature.round(3), "culture_score": culture.round(3), "nightlife_score": nightlife.round(3),
        "climate_pref": climate.round(3), "season": season, "traveler_type": ttype, "past_trips": past,
        "destination_type": labels,
    })


def make_equipment(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range(end=pd.Timestamp(utcnow()).floor("10min"), periods=n, freq="10min")
    machine = rng.choice([f"M-{i:02d}" for i in range(1, 13)], n)
    temp = rng.normal(68, 7, n)
    vib = np.abs(rng.normal(3.2, 1.1, n))
    pressure = rng.normal(101, 4, n)
    rpm = rng.normal(1480, 120, n)
    humidity = rng.uniform(30, 80, n)
    runtime = rng.uniform(0, 9000, n)
    logit = 0.16 * (temp - 75) + 1.1 * (vib - 4.2) + 0.00035 * (runtime - 6000) + rng.normal(0, 0.6, n)
    failure = (logit > 0).astype(int)
    return pd.DataFrame({"timestamp": ts.strftime("%Y-%m-%d %H:%M"), "machine_id": machine, "temperature": temp.round(2),
                         "vibration": vib.round(3), "pressure": pressure.round(2), "rpm": rpm.round(0),
                         "humidity": humidity.round(1), "runtime_hours": runtime.round(1), "failure": failure})


def make_maintenance(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    age = rng.uniform(0.5, 15, n)
    since = rng.integers(1, 365, n)
    load = rng.uniform(20, 100, n)
    errors = rng.poisson(2, n)
    temp = rng.normal(60, 8, n)
    shift = rng.choice(["day", "evening", "night"], n)
    component = rng.choice(["bearing", "motor", "pump", "valve", "sensor"], n)
    comp_cost = pd.Series(component).map({"bearing": 3.0, "motor": 6.5, "pump": 4.0, "valve": 2.0, "sensor": 1.0}).to_numpy()
    downtime = (0.6 * age + 0.018 * since + 0.05 * load + 1.3 * errors + 0.08 * (temp - 60)
                + comp_cost + 1.2 * (shift == "night") + rng.normal(0, 1.4, n)).clip(0.2, None)
    return pd.DataFrame({"machine_age_years": age.round(2), "days_since_service": since, "load_pct": load.round(1),
                         "error_count": errors, "avg_temperature": temp.round(1), "shift": shift, "component": component,
                         "downtime_hours": downtime.round(2)})


def breast_cancer() -> pd.DataFrame:
    from sklearn.datasets import load_breast_cancer

    data = load_breast_cancer(as_frame=True)
    df = data.frame.copy()
    df.columns = [c.replace(" ", "_") for c in df.columns]
    df["diagnosis"] = np.where(df.pop("target") == 1, "benign", "malignant")
    return df


def wine() -> pd.DataFrame:
    from sklearn.datasets import load_wine

    data = load_wine(as_frame=True)
    df = data.frame.copy()
    df["cultivar"] = df.pop("target").map({0: "cultivar_a", 1: "cultivar_b", 2: "cultivar_c"})
    return df


def sample_images(kind: str, folder: Path, count: int = 4) -> None:
    """Procedural thumbnails for metadata-only image datasets (clearly synthetic)."""
    folder.mkdir(parents=True, exist_ok=True)
    palettes = {
        "ocean_images": ((4, 40, 80), (20, 140, 170)), "product_defects": ((60, 60, 70), (170, 170, 180)),
        "street_scenes": ((30, 30, 50), (200, 120, 60)), "medical_xrays": ((5, 5, 10), (190, 200, 210)),
        "satellite_tiles": ((30, 60, 30), (140, 120, 80)),
    }
    lo, hi = palettes.get(kind, ((20, 20, 40), (120, 120, 200)))
    h, w = 240, 320
    for i in range(count):
        rng = np.random.default_rng(hash((kind, i)) % (2 ** 32))
        yy, xx = np.mgrid[0:h, 0:w]
        t = (yy / h)[..., None]
        base = np.array(lo)[None, None, :] * t + np.array(hi)[None, None, :] * (1 - t)
        noise = np.zeros((h, w))
        for _ in range(4):
            fx, fy, ph = rng.uniform(0.01, 0.06), rng.uniform(0.01, 0.06), rng.uniform(0, 6.28)
            noise += np.sin(xx * fx + yy * fy + ph)
        img = base * (0.85 + 0.08 * noise[..., None])
        for _ in range(rng.integers(3, 8)):
            cx, cy, r = rng.integers(20, w - 20), rng.integers(20, h - 20), rng.integers(6, 26)
            mask = (xx - cx) ** 2 / (r * 1.8) ** 2 + (yy - cy) ** 2 / r ** 2 < 1
            img[mask] = img[mask] * 0.5 + np.array(hi) * 0.6
        Image.fromarray(np.clip(img, 0, 255).astype("uint8")).save(folder / f"sample_{i + 1}.jpg", "JPEG", quality=85)


def write_version(ds: Dataset, version: int, df: pd.DataFrame, created: datetime, owner_id: int, note: str) -> DatasetVersion:
    folder = DATASETS_DIR / str(ds.id) / f"v{version}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{ds.name}.csv"
    df.to_csv(path, index=False)
    prof = profile_tabular(path)
    return DatasetVersion(dataset_id=ds.id, version=version, file_path=storage.rel(path), file_name=path.name,
                          file_format="csv", size_bytes=path.stat().st_size, rows=prof["rows"], columns=prof["columns"],
                          missing_pct=prof["missing_pct"], duplicate_pct=prof["duplicate_pct"], quality=prof["quality"],
                          schema_info=prof["schema"], note=note, owner_id=owner_id, created_at=created)


# -------------------------------------------------------------------- runs
def synthetic_curve(epochs: int, final_acc: float, seed: int) -> list[dict[str, float]]:
    rng = np.random.default_rng(seed)
    rows = []
    for e in range(1, epochs + 1):
        p = 1 - np.exp(-4.0 * e / epochs)
        acc_tr = min(0.995, 0.35 + (final_acc + 0.03 - 0.35) * p + rng.normal(0, 0.006))
        acc_va = min(0.99, 0.33 + (final_acc - 0.33) * p + rng.normal(0, 0.008))
        loss_tr = max(0.02, 1.1 * np.exp(-3.2 * e / epochs) + 0.08 + rng.normal(0, 0.01))
        loss_va = max(0.03, 1.15 * np.exp(-3.0 * e / epochs) + 0.12 + rng.normal(0, 0.012))
        rows.append({"epoch": e, "train_acc": round(acc_tr, 4), "val_acc": round(acc_va, 4), "train_loss": round(loss_tr, 4),
                     "val_loss": round(loss_va, 4), "f1": round(acc_va - 0.01, 4)})
    return rows


def add_seeded_run(s, code: str, name: str, algo_label: str, framework: str, status: str, acc: float | None,
                   epochs: int, owner_id: int, created: datetime, duration_s: float, dataset_id: int | None,
                   gpu_hours: float = 0.0, error: str | None = None, device: str = "GPU (RTX 3050)") -> Run:
    done = epochs if status == "Completed" else max(1, int(epochs * (0.55 if status == "Failed" else 0.4)))
    curve = synthetic_curve(epochs, acc or 0.75, abs(hash(code)) % 10_000)[:done]
    last = curve[-1]
    metrics = {"accuracy": acc if status == "Completed" else last["val_acc"], "loss": last["train_loss"],
               "val_loss": last["val_loss"], "f1": last["f1"], "task": "classification"}
    run = Run(code=code, name=name, algorithm=algo_label.lower().replace(" ", "_"), algorithm_label=algo_label,
              framework=framework, task="classification", kind="train", source="seed", dataset_id=dataset_id,
              dataset_version=1, status=status, params={"epochs": epochs, "batch_size": 32, "learning_rate": 0.001,
                                                        "optimizer": "Adam"},
              metrics=metrics, progress=round(done / epochs * 100, 1), epoch=done, total_epochs=epochs, device=device,
              gpu_hours=gpu_hours, error=error, owner_id=owner_id, created_at=created, started_at=created,
              finished_at=created + timedelta(seconds=duration_s), duration_s=duration_s)
    s.add(run)
    s.commit()
    s.refresh(run)
    step = duration_s / max(1, done)
    for row in curve:
        s.add(RunMetric(run_id=run.id, ts=created + timedelta(seconds=step * row["epoch"]), **row))
    s.commit()
    return run


def train_real(code: str, name: str, algorithm: str, dataset_id: int, version: int, params: dict[str, Any],
               owner_id: int, when: datetime, target: str | None = None) -> int:
    info = ALGORITHMS[algorithm]
    p = normalise_params(algorithm, params)
    with session_scope() as s:
        ds = s.get(Dataset, dataset_id)
        run = Run(code=code, name=name, algorithm=algorithm, algorithm_label=info["label"], framework=info["framework"],
                  kind="train", source="live", dataset_id=dataset_id, dataset_version=version,
                  target=target or ds.target_column, params=p, total_epochs=p["epochs"], owner_id=owner_id)
        s.add(run)
        s.commit()
        s.refresh(run)
        run_id = run.id
    status = trainer.execute(run_id, pace_s=0.0)
    if status != "Completed":
        with session_scope() as s:
            err = s.get(Run, run_id).error
        raise RuntimeError(f"Seed training {code} failed: {err}")
    with session_scope() as s:
        run = s.get(Run, run_id)
        real_duration = max(run.duration_s, 1.0)
        run.created_at = when
        run.started_at = when
        run.finished_at = when + timedelta(seconds=real_duration)
        s.add(run)
        metrics = s.exec(select(RunMetric).where(RunMetric.run_id == run_id).order_by(RunMetric.epoch)).all()
        step = real_duration / max(1, len(metrics))
        for m in metrics:
            m.ts = when + timedelta(seconds=step * m.epoch)
            s.add(m)
        s.commit()
    return run_id


# ------------------------------------------------------------ prediction logs
def measured_latency_ms(bundle: dict[str, Any], rows: list[dict[str, Any]]) -> float:
    predict_rows(bundle, rows[:1])  # warm-up
    samples = []
    for r in rows[:25]:
        t = time.perf_counter()
        predict_rows(bundle, [r])
        samples.append((time.perf_counter() - t) * 1000)
    return float(np.median(samples))


def seed_prediction_logs(s, dep: Deployment, version: ModelVersion, per_5min_today: float) -> int:
    bundle = load_bundle(version)
    holdout = pd.read_parquet(storage.resolve(version.artifact_path).parent / "holdout.parquet")
    feats = holdout[bundle["features"]]
    records = [to_jsonable(r) for r in feats.to_dict(orient="records")]
    preds = [p["prediction"] for p in predict_rows(bundle, records)]
    median_ms = measured_latency_ms(bundle, records)
    now = utcnow().replace(second=0, microsecond=0)
    rows = []
    for bucket in range(7 * 288):
        ts0 = now - timedelta(minutes=5 * (bucket + 1))
        hour = (ts0.hour + 5.5) % 24  # diurnal shape around local (IST) daytime
        shape = 0.55 + 0.45 * np.sin((hour - 8) / 24 * 2 * np.pi)
        rate = per_5min_today * shape * (1.0 if bucket < 288 else 0.35)
        for _ in range(RNG.poisson(max(rate, 0.05))):
            idx = int(RNG.integers(0, len(records)))
            ts = ts0 + timedelta(seconds=float(RNG.uniform(0, 300)))
            latency = float(median_ms * RNG.lognormal(0, 0.35))
            is_err = RNG.random() < 0.002
            rows.append({
                "deployment_id": dep.id, "version_id": version.id, "ts": ts, "latency_ms": round(latency, 3),
                "input": records[idx], "prediction": None if is_err else to_jsonable(preds[idx]), "is_error": bool(is_err),
                "error": "Feature 'age' must be a scalar value" if is_err else None, "replica": int(RNG.integers(0, dep.replicas)),
                "source": "seed",
            })
    for chunk in range(0, len(rows), 2000):
        s.execute(PredictionLog.__table__.insert(), rows[chunk:chunk + 2000])
    s.commit()
    return len(rows)


def seed_system_metrics(s) -> None:
    import psutil

    vm = psutil.virtual_memory()
    total = vm.total / 1e9
    base_ram = vm.percent
    now = utcnow().replace(second=0, microsecond=0)
    rows = []
    for i in range(48 * 12, 0, -1):
        ts = now - timedelta(minutes=5 * i)
        hour = (ts.hour + 5.5) % 24
        day = 0.5 + 0.5 * np.sin((hour - 8) / 24 * 2 * np.pi)
        cpu = float(np.clip(18 + 30 * day + RNG.normal(0, 6), 2, 98))
        ram = float(np.clip(base_ram - 6 + 8 * day + RNG.normal(0, 1.5), 10, 97))
        gpu = float(np.clip(6 + 30 * day + RNG.normal(0, 7), 0, 100))
        rows.append({"ts": ts, "cpu": round(cpu, 1), "ram": round(ram, 1), "gpu": round(gpu, 1),
                     "ram_used_gb": round(total * ram / 100, 2), "ram_total_gb": round(total, 2),
                     "gpu_mem_used_gb": round(6.4 * gpu / 160, 2), "gpu_mem_total_gb": 6.44,
                     "cpu_count": psutil.cpu_count() or 1})
    s.execute(SystemMetric.__table__.insert(), rows)
    s.commit()


# -------------------------------------------------------------------- main
def wipe() -> None:
    drop_db()
    for folder in (DATASETS_DIR, MODELS_DIR, RUNS_DIR, PIPELINES_DIR, UPLOAD_TMP_DIR):
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True, exist_ok=True)
    settings_store.invalidate()


def seed(reset: bool = False) -> None:
    if reset:
        wipe()
    init_db()
    with session_scope() as s:
        if s.exec(select(User)).first() is not None:
            print("Database already seeded; use --reset to start over.")
            return
    t0 = time.perf_counter()
    settings_store.invalidate()
    settings_store.get()
    settings_store.set_admin_password("admin", "admin")

    with session_scope() as s:
        harshan = User(username="harshan", display_name="Harshan", email="harshan@mini-mlops.local",
                       title="ML Engineer", role="Owner",
                       bio="Builds the training and serving side of Mini MLOps: experiment tracking, the registry and live deployments.",
                       location="Chennai, IN", accent="#3B82F6", quote="Turn data into impact", joined_at=ago(days=60))
        abishek = User(username="abishek", display_name="Abishek", email="abishek@mini-mlops.local",
                       title="Data Scientist", role="Member",
                       bio="Owns datasets, data quality and monitoring: drift checks, alert rules and model evaluation.",
                       location="Chennai, IN", accent="#8B5CF6", quote="From models to real impact", joined_at=ago(days=58))
        s.add(harshan)
        s.add(abishek)
        s.commit()
        H, A = harshan.id, abishek.id

    # ---- real datasets -------------------------------------------------
    real_specs = [
        ("breast_cancer", "Tabular", "diagnosis", "Breast cancer diagnostic measurements (scikit-learn, Wisconsin).",
         ["medical", "classification", "sklearn"], A,
         [(breast_cancer().iloc[:455], ago(days=26), "Initial 80% extract"), (breast_cancer(), ago(days=9), "Full dataset")]),
        ("wine", "Tabular", "cultivar", "Chemical analysis of wines from three cultivars (scikit-learn).",
         ["chemistry", "multiclass", "sklearn"], A, [(wine(), ago(days=24), "Initial upload")]),
        ("equipment_sensor", "Time Series", "failure", "Industrial sensor readings with failure labels.",
         ["iot", "sensors", "time-series"], A,
         [(make_equipment(8000, 11), ago(days=21), "Two months of readings"),
          (make_equipment(12000, 12), ago(hours=5), "Added March-April readings")]),
        ("travel_recommend", "Tabular", "destination_type", "Travel recommendation data: traveller profile to destination type.",
         ["recommendation", "travel", "tabular"], H,
         [(make_travel(4000, 21), ago(days=20), "Pilot survey"), (make_travel(5000, 22), ago(days=11), "More respondents"),
          (make_travel(6000, 23), ago(days=3), "Balanced seasons")]),
        ("maintenance_logs", "Tabular", "downtime_hours", "Machine maintenance records with downtime.",
         ["maintenance", "regression"], A,
         [(make_maintenance(3500, 31), ago(days=17), "Initial export"), (make_maintenance(5000, 32), ago(days=1), "Q3 export")]),
    ]
    ids: dict[str, int] = {}
    with session_scope() as s:
        for name, dtype, target, desc, tags, owner, versions in real_specs:
            ds = Dataset(name=name, description=desc, dtype=dtype, status="Ready", tags=tags, target_column=target,
                         is_real=True, current_version=len(versions), owner_id=owner, created_at=versions[0][1],
                         updated_at=versions[-1][1])
            s.add(ds)
            s.commit()
            s.refresh(ds)
            for i, (df, created, note) in enumerate(versions, start=1):
                s.add(write_version(ds, i, df, created, owner, note))
            s.commit()
            ids[name] = ds.id

        # ---- metadata-only datasets -------------------------------------
        meta = [
            ("ocean_images", "Image", "Ready", "Underwater visual dataset for marine analysis. High-quality underwater images for visual enhancement and marine life monitoring.",
             ["image", "underwater", "marine", "augmentation"], H, 12.4e9, 125_430, 96.0, 3, 2),
            ("product_defects", "Image", "Ready", "Manufacturing defect images.", ["image", "manufacturing", "defects"], A,
             6.7e9, 89_230, 94.0, 4, 48),
            ("street_scenes", "Image", "Ready", "Urban street scenes for object detection.", ["image", "detection"], H,
             9.1e9, 210_400, 91.0, 2, 150),
            ("medical_xrays", "Image", "Ready", "Chest X-ray images for screening research.", ["image", "medical"], A,
             5.2e9, 48_900, 95.0, 1, 400),
            ("satellite_tiles", "Image", "Ready", "Satellite land-cover tiles.", ["image", "geospatial"], H,
             8.3e9, 64_200, 90.0, 2, 300),
            ("nlp_support_tickets", "Text", "Processing", "Customer support transcripts.", ["text", "nlp", "support"], A,
             512e6, 156_892, 87.0, 1, 48),
            ("audio_commands", "Other", "Ready", "Short spoken commands for keyword spotting.", ["audio", "speech"], H,
             2.4e9, 48_000, 90.0, 1, 520),
        ]
        for name, dtype, status, desc, tags, owner, size, rows, quality, nver, hours_ago in meta:
            created_first = ago(hours=hours_ago + 24 * 3 * (nver - 1) + 24 * 6)
            ds = Dataset(name=name, description=desc, dtype=dtype, status=status, tags=tags, is_real=False,
                         current_version=nver, owner_id=owner, created_at=created_first, updated_at=ago(hours=hours_ago))
            s.add(ds)
            s.commit()
            s.refresh(ds)
            for v in range(1, nver + 1):
                frac = 0.7 + 0.3 * v / nver
                created = ago(hours=hours_ago) if v == nver else created_first + timedelta(days=3 * (v - 1))
                s.add(DatasetVersion(dataset_id=ds.id, version=v, file_path=None, file_name=f"{name}_v{v}.zip",
                                     file_format="zip", size_bytes=int(size * frac), rows=int(rows * frac), columns=0,
                                     missing_pct=0.0, duplicate_pct=round(100 - quality, 1), quality=quality - (nver - v) * 0.7,
                                     schema_info=[], note="Metadata-only record", owner_id=owner, created_at=created))
            s.commit()
            if dtype == "Image":
                sample_images(name, DATASETS_DIR / str(ds.id) / f"v{nver}" / "samples")
            ids[name] = ds.id
    print(f"[seed] datasets ready ({time.perf_counter() - t0:.1f}s)")

    # ---- seeded run history (exp-1 .. exp-19) --------------------------
    history = [
        ("Baseline Forest", "Random Forest", "Scikit-learn", "Completed", 0.842, "breast_cancer", H, 29, 0.0),
        ("Wine Linear", "Logistic Regression", "Scikit-learn", "Completed", 0.889, "wine", A, 28, 0.0),
        ("Sensor Boost", "XGBoost", "XGBoost", "Completed", 0.871, "equipment_sensor", A, 27, 0.06),
        ("Travel Forest", "Random Forest", "Scikit-learn", "Completed", 0.803, "travel_recommend", H, 26, 0.0),
        ("Defect CNN", "YOLOv8", "Ultralytics", "Failed", 0.612, "product_defects", A, 25, 0.8),
        ("Ticket LSTM", "LSTM", "PyTorch", "Completed", 0.834, "nlp_support_tickets", A, 24, 0.9),
        ("Travel Boost", "XGBoost", "XGBoost", "Completed", 0.856, "travel_recommend", H, 22, 0.05),
        ("Ocean Detector", "YOLOv8", "Ultralytics", "Completed", 0.874, "ocean_images", H, 21, 2.1),
        ("Wine MLP", "MLP", "Scikit-learn", "Stopped", 0.901, "wine", A, 19, 0.0),
        ("Diagnosis MLP", "MLP", "Scikit-learn", "Completed", 0.947, "breast_cancer", A, 18, 0.0),
        ("Street Detector", "YOLOv8", "Ultralytics", "Completed", 0.852, "street_scenes", H, 16, 2.4),
        ("Sensor Forest", "Random Forest", "Scikit-learn", "Completed", 0.888, "equipment_sensor", A, 15, 0.0),
        ("Ticket Classifier", "BERT", "Hugging Face", "Completed", 0.901, "nlp_support_tickets", A, 14, 1.6),
        ("Travel MLP v0", "MLP", "Scikit-learn", "Failed", 0.702, "travel_recommend", H, 12, 0.0),
        ("Xray Screening", "YOLOv8", "Ultralytics", "Completed", 0.889, "medical_xrays", A, 10, 1.9),
        ("Maintenance Forest", "Random Forest", "Scikit-learn", "Completed", 0.811, "maintenance_logs", A, 9, 0.0),
        ("Satellite Tiles", "YOLOv8", "Ultralytics", "Completed", 0.868, "satellite_tiles", H, 7, 2.2),
        ("Wine Boost", "XGBoost", "XGBoost", "Completed", 0.944, "wine", A, 6, 0.02),
        ("Ticket LSTM v2", "LSTM", "PyTorch", "Completed", 0.857, "nlp_support_tickets", A, 5, 1.1),
    ]
    seeded_runs: dict[str, int] = {}
    with session_scope() as s:
        for i, (name, label, fw, status, acc, ds_name, owner, days_ago, gpu) in enumerate(history, start=1):
            created = ago(days=days_ago, hours=float(RNG.uniform(0, 10)))
            dev = "GPU (RTX 3050)" if gpu > 0 else "CPU"
            err = {"Failed": "Out of memory while allocating batch (seeded history)", "Stopped": None}.get(status)
            r = add_seeded_run(s, f"exp-{i}", name, label, fw, status, acc, 60, owner, created,
                               duration_s=float(RNG.uniform(600, 9000)), dataset_id=ids[ds_name], gpu_hours=gpu, error=err,
                               device=dev)
            seeded_runs[r.code] = r.id
    print(f"[seed] run history ready ({time.perf_counter() - t0:.1f}s)")

    # ---- real training (exp-20 .. exp-28 mix real + seeded) -------------
    real_runs: dict[str, int] = {}
    real_runs["exp-20"] = train_real("exp-20", "Maintenance Downtime", "xgboost", ids["maintenance_logs"], 2,
                                     {"epochs": 60, "learning_rate": 0.1, "batch_size": 32, "max_depth": 5}, A, ago(days=1, hours=2))
    real_runs["exp-21"] = train_real("exp-21", "Diagnosis Baseline", "logistic_regression", ids["breast_cancer"], 2,
                                     {"epochs": 30, "learning_rate": 0.01, "batch_size": 32}, A, ago(days=2, hours=5))
    real_runs["exp-22"] = train_real("exp-22", "Travel Baseline", "xgboost", ids["travel_recommend"], 1,
                                     {"epochs": 40, "learning_rate": 0.05, "batch_size": 32, "max_depth": 4}, H, ago(days=14))
    real_runs["exp-23"] = train_real("exp-23", "Travel MLP", "mlp", ids["travel_recommend"], 2,
                                     {"epochs": 60, "learning_rate": 0.001, "batch_size": 32, "optimizer": "Adam"}, H, ago(days=5))
    with session_scope() as s:
        seeded_runs["exp-24"] = add_seeded_run(s, "exp-24", "Object Detection", "YOLOv8", "Ultralytics", "Completed", 0.901, 80, A,
                                               ago(days=2, hours=1), 11760, ids["product_defects"], gpu_hours=3.27).id
        seeded_runs["exp-25"] = add_seeded_run(s, "exp-25", "BERT Fine-tuning", "BERT", "Hugging Face", "Failed", 0.761, 40, A,
                                               ago(days=2, hours=9), 4680, ids["nlp_support_tickets"], gpu_hours=1.3,
                                               error="CUDA out of memory at epoch 22 (seeded history)").id
        seeded_runs["exp-26"] = add_seeded_run(s, "exp-26", "Sentiment Analysis", "LSTM", "PyTorch", "Completed", 0.861, 100, H,
                                               ago(days=1), 2856, ids["nlp_support_tickets"], gpu_hours=0.79).id
    real_runs["exp-27"] = train_real("exp-27", "XGBoost Tuning", "xgboost", ids["travel_recommend"], 3,
                                     {"epochs": 80, "learning_rate": 0.1, "batch_size": 32, "max_depth": 6}, H, ago(hours=5))
    real_runs["exp-28"] = train_real("exp-28", "Forest Classification", "random_forest", ids["breast_cancer"], 2,
                                     {"epochs": 50, "batch_size": 32, "n_estimators": 150}, H, ago(hours=2))
    print(f"[seed] real training done ({time.perf_counter() - t0:.1f}s)")

    # ---- registry ------------------------------------------------------
    with session_scope() as s:
        v_t0 = registry.register_run(s, real_runs["exp-22"], "Travel Recommender", "Recommends a destination type from a traveller profile.", H,
                                     ["recommender", "travel", "tabular"])
        v_t1 = registry.register_run(s, real_runs["exp-23"], "Travel Recommender", "MLP variant with season features.", H)
        v_t2 = registry.register_run(s, real_runs["exp-27"], "Travel Recommender", "XGBoost model retrained on the v3 data (balanced seasons).", H)
        v_rf = registry.register_run(s, real_runs["exp-28"], "Random Forest Classifier", "Diagnosis classifier (benign vs malignant).", H,
                                     ["medical", "classification"])
        v_xr = registry.register_run(s, real_runs["exp-20"], "XGBoost Regressor", "Predicts machine downtime hours.", A,
                                     ["maintenance", "regression"])
        registry.set_stage(s, v_t1.model_id, v_t1.version, "Staging", H)
        registry.set_stage(s, v_t2.model_id, v_t2.version, "Production", H)
        registry.set_stage(s, v_rf.model_id, v_rf.version, "Production", H)
        registry.set_stage(s, v_xr.model_id, v_xr.version, "Staging", A)
        when = {v_t0.id: ago(days=14), v_t1.id: ago(days=5), v_t2.id: ago(hours=4, minutes=40), v_rf.id: ago(hours=1, minutes=50),
                v_xr.id: ago(days=1)}
        for vid, ts in when.items():
            mv = s.get(ModelVersion, vid)
            mv.created_at = ts
            s.add(mv)
        for model_id, created in ((v_t0.model_id, ago(days=14)), (v_rf.model_id, ago(hours=1, minutes=50)), (v_xr.model_id, ago(days=1))):
            m = s.get(RegisteredModel, model_id)
            m.created_at = created
            m.updated_at = max(created, ago(hours=4))
            s.add(m)
        s.commit()
        # Seeded models (history only, no artifact).
        for name, fw, mtype, owner, versions, desc, tags in [
            ("LSTM Sentiment", "PyTorch", "Classification", H, [("v2.1.3", "Staging", 0.861, "exp-26", 215e6)],
             "Sentiment classifier for support tickets (history; PyTorch not installed here).", ["nlp", "sentiment"]),
            ("YOLOv8 Detector", "Ultralytics", "Detection", A, [("v3.0.0", "Archived", 0.874, "exp-8", 1.1e9),
                                                                ("v3.0.1", "Production", 0.901, "exp-24", 1.2e9)],
             "Defect and object detector (history only).", ["vision", "detection"]),
            ("BERT Text Classifier", "Hugging Face", "Classification", A, [("v1.1.0", "Development", 0.901, "exp-13", 420e6)],
             "Ticket routing classifier (history only).", ["nlp", "transformers"]),
        ]:
            m = RegisteredModel(name=name, description=desc, tags=tags, framework=fw, model_type=mtype, owner_id=owner,
                                created_at=ago(days=12), updated_at=ago(days=2))
            s.add(m)
            s.commit()
            s.refresh(m)
            for ver, stage, acc, code, size in versions:
                s.add(ModelVersion(model_id=m.id, version=ver, run_id=seeded_runs.get(code), stage=stage, accuracy=acc,
                                   size_bytes=int(size), artifact_path=None, description="Seeded history (no artifact)",
                                   metrics={"accuracy": acc, "task": "classification"}, owner_id=owner, created_at=ago(days=3)))
            s.commit()
    print(f"[seed] registry ready ({time.perf_counter() - t0:.1f}s)")

    # ---- deployments + 7 days of prediction logs -----------------------
    with session_scope() as s:
        dep_specs = [
            ("travel-recommender", "Travel Recommender", v_t2, v_t1.id, "Production", 3, 2, 6, H, 12.0,
             [("deploy", v_t0.version, 14 * 24), ("rollout", v_t1.version, 5 * 24), ("rollout", v_t2.version, 2)]),
            ("maintenance-downtime-api", "Maintenance Downtime API", v_xr, None, "Staging", 2, 1, 4, A, 4.0,
             [("deploy", v_xr.version, 23)]),
            ("random-forest-api", "Random Forest API", v_rf, None, "Development", 1, 1, 3, H, 6.0,
             [("deploy", v_rf.version, 1.5)]),
        ]
        total_logs = 0
        for slug, name, mv, prev_id, env, replicas, mn, mx, owner, rate, events in dep_specs:
            dep = Deployment(slug=slug, name=name, model_id=mv.model_id, version_id=mv.id, previous_version_id=prev_id,
                             environment=env, status="Running", replicas=replicas, min_replicas=mn, max_replicas=mx,
                             target_cpu=70, autoscaling=True, progress=100, stage_label=f"{mv.version} deployed successfully",
                             owner_id=owner, created_at=ago(hours=events[0][2]), updated_at=ago(hours=events[-1][2]))
            s.add(dep)
            s.commit()
            s.refresh(dep)
            for kind, ver, hours_back in events:
                s.add(DeploymentEvent(deployment_id=dep.id, kind=kind, version_label=ver, environment=env,
                                      message=f"{'Deployed' if kind == 'deploy' else 'Rolled out'} {name} {ver} to {env}",
                                      ts=ago(hours=hours_back)))
            s.commit()
            total_logs += seed_prediction_logs(s, dep, mv, rate)
        seed_system_metrics(s)
    print(f"[seed] deployments + {total_logs:,} prediction logs ready ({time.perf_counter() - t0:.1f}s)")

    # ---- pipelines -------------------------------------------------------
    from app.routers.pipelines import default_yaml

    with session_scope() as s:
        travel_yaml = default_yaml("Travel Recommender Pipeline", "travel_recommend", "Travel Recommender", "v1.3.0")
        diag_yaml = default_yaml("Diagnosis Pipeline", "breast_cancer", "Diagnosis Classifier", "v1.0.0")
        p1 = Pipeline(name="Travel Recommender Pipeline", description="Validate, prepare, train XGBoost and an MLP in parallel, pick the best, register and deploy to Staging.",
                      version="v1.3.0", yaml=travel_yaml, active=True, owner_id=H, created_at=ago(days=20), updated_at=ago(days=1))
        p2 = Pipeline(name="Diagnosis Pipeline", description="Breast-cancer diagnosis training pipeline.", version="v1.0.0",
                      yaml=diag_yaml, active=True, owner_id=A, created_at=ago(days=8), updated_at=ago(days=8))
        s.add(p1)
        s.add(p2)
        s.commit()
        s.refresh(p1)
        s.refresh(p2)
        for ver, days_back in (("v1.2.0", 20), ("v1.2.1", 12), ("v1.2.2", 6), ("v1.2.3", 3), ("v1.3.0", 1)):
            spec = parse_spec(travel_yaml)
            spec["version"] = ver
            s.add(PipelineVersion(pipeline_id=p1.id, version=ver, yaml=dump_spec(spec) if ver != "v1.3.0" else travel_yaml,
                                  created_at=ago(days=days_back)))
        s.add(PipelineVersion(pipeline_id=p2.id, version="v1.0.0", yaml=diag_yaml, created_at=ago(days=8)))
        s.commit()
        spec = parse_spec(travel_yaml)
        durations = {"validate": 12, "preprocess": 28, "features": 45, "train_xgb": 734, "train_dl": 506, "evaluate": 138,
                     "register": 14, "deploy": 65}
        for number, ver, trig, status, days_back, fail_node in ((24, "v1.2.0", "api", "Success", 8, None),
                                                               (25, "v1.2.1", "manual", "Success", 7, None),
                                                               (26, "v1.2.2", "schedule", "Failed", 6, "train_dl"),
                                                               (27, "v1.2.3", "manual", "Success", 5, None)):
            start = ago(days=days_back)
            nodes, cursor, failed = {}, start, False
            order = ["validate", "preprocess", "features", "train_xgb", "train_dl", "evaluate", "register", "deploy"]
            for nid in order:
                node = next(n for n in spec["nodes"] if n["id"] == nid)
                if failed and nid in ("evaluate", "register", "deploy"):
                    nodes[nid] = {"status": "skipped", "name": node["name"], "type": node["type"], "version": ver, "started_at": None,
                                  "finished_at": None, "duration_s": None, "progress": 0, "message": "Upstream step did not succeed",
                                  "artifacts": [], "run_id": None}
                    continue
                dur = durations[nid] * float(RNG.uniform(0.85, 1.15))
                st = "failed" if nid == fail_node else "success"
                if st == "failed":
                    failed = True
                begin = cursor if nid != "train_dl" else nodes["train_xgb"]["_begin"]
                end = begin + timedelta(seconds=dur)
                nodes[nid] = {"status": st, "name": node["name"], "type": node["type"], "version": ver,
                              "started_at": begin.isoformat() + "Z", "finished_at": end.isoformat() + "Z",
                              "duration_s": round(dur, 1), "progress": 100 if st == "success" else 55,
                              "message": "Seeded history" if st == "success" else "Diverged: loss is NaN (seeded history)",
                              "artifacts": [], "run_id": None, "_begin": begin, "_end": end}
                if nid == "train_dl":  # parallel branches: continue after the slower one
                    cursor = max(end, nodes["train_xgb"]["_end"])
                elif nid != "train_xgb":
                    cursor = end
            for st in nodes.values():
                st.pop("_begin", None)
                st.pop("_end", None)
            ends = [datetime.fromisoformat(n["finished_at"][:-1]) for n in nodes.values() if n["finished_at"]]
            run = PipelineRun(pipeline_id=p1.id, number=number, version=ver, yaml_snapshot=travel_yaml, triggered_by=trig,
                              status=status, nodes=nodes, source="seed", owner_id=H, started_at=start,
                              finished_at=max(ends), duration_s=round((max(ends) - start).total_seconds(), 1))
            s.add(run)
            s.commit()
            s.refresh(run)
            s.add(PipelineLog(run_id=run.id, ts=start, level="INFO", node="pipeline", message=f"Run #{number} started (seeded history)"))
            s.add(PipelineLog(run_id=run.id, ts=max(ends), level="INFO" if status == "Success" else "WARN", node="pipeline",
                              message=f"Run finished: {status}"))
            s.commit()
    print(f"[seed] pipelines ready ({time.perf_counter() - t0:.1f}s)")

    # ---- activity feed, alerts, API keys ---------------------------------
    with session_scope() as s:
        s.execute(delete(Alert))
        s.execute(delete(Activity))
        s.commit()
        acts: list[Activity] = []
        for ds in s.exec(select(Dataset)).all():
            for v in s.exec(select(DatasetVersion).where(DatasetVersion.dataset_id == ds.id)).all():
                verb = "Uploaded dataset" if v.version == 1 else "Uploaded new version of"
                acts.append(Activity(ts=v.created_at, user_id=v.owner_id, kind="dataset", action="uploaded",
                                     message=f"{verb} {ds.name} (v{v.version}, {v.rows:,} rows)", link=f"/datasets?select={ds.id}"))
        for r in s.exec(select(Run).where(Run.kind == "train")).all():
            acts.append(Activity(ts=r.created_at, user_id=r.owner_id, kind="experiment", action="started",
                                 message=f"Started {r.code} ({r.algorithm_label})", link=f"/experiments?select={r.id}"))
            if r.finished_at and r.status in ("Completed", "Failed", "Stopped"):
                acc = (r.metrics or {}).get("accuracy")
                msg = f"Run {r.code} ({r.algorithm_label}) {r.status.lower()}" + (f", accuracy {acc:.3f}" if r.status == "Completed" and acc else "")
                acts.append(Activity(ts=r.finished_at, user_id=r.owner_id, kind="experiment", action=r.status.lower(),
                                     message=msg, link=f"/experiments?select={r.id}"))
        models = {m.id: m for m in s.exec(select(RegisteredModel)).all()}
        for v in s.exec(select(ModelVersion)).all():
            acts.append(Activity(ts=v.created_at, user_id=v.owner_id, kind="model", action="registered",
                                 message=f"Registered {models[v.model_id].name} {v.version} ({v.stage})", link=f"/models?select={v.model_id}"))
        for d in s.exec(select(Deployment)).all():
            for e in s.exec(select(DeploymentEvent).where(DeploymentEvent.deployment_id == d.id)).all():
                acts.append(Activity(ts=e.ts, user_id=d.owner_id, kind="deployment", action=e.kind, message=e.message,
                                     link=f"/deployments?select={d.id}"))
        for pr in s.exec(select(PipelineRun)).all():
            acts.append(Activity(ts=pr.started_at, user_id=pr.owner_id, kind="pipeline", action=pr.status.lower(),
                                 message=f"Travel Recommender Pipeline run #{pr.number}: {pr.status}", link=f"/pipelines?run={pr.id}"))
        acts.append(Activity(ts=ago(days=10), user_id=A, kind="settings", action="saved", message="Tuned alert thresholds for drift monitoring", link="/settings"))
        acts.append(Activity(ts=ago(days=4), user_id=H, kind="settings", action="saved", message="Updated compute limits (8 cores, 16 GB)", link="/settings"))
        s.add_all(acts)
        dep_by_slug = {d.slug: d for d in s.exec(select(Deployment)).all()}
        runs_by_code = {r.code: r for r in s.exec(select(Run)).all()}
        acc27 = (runs_by_code["exp-27"].metrics or {}).get("accuracy", 0)
        acc28 = (runs_by_code["exp-28"].metrics or {}).get("accuracy", 0)
        s.add_all([
            Alert(ts=ago(hours=2), severity="info", kind="deployed", category="deployment", title="New model deployed",
                  message=f"Travel Recommender {v_t2.version} is live in Production", deployment_id=dep_by_slug["travel-recommender"].id,
                  read=False, resolved=True),
            Alert(ts=ago(hours=2, minutes=5), severity="success", kind="run_completed", category="experiment", title="exp-28 completed",
                  message=f"Random Forest finished with accuracy {acc28:.3f}", read=False, resolved=True),
            Alert(ts=ago(hours=5), severity="success", kind="run_completed", category="experiment", title="exp-27 completed",
                  message=f"XGBoost finished with accuracy {acc27:.3f}", read=True, resolved=True),
            Alert(ts=ago(hours=1, minutes=30), severity="info", kind="deployed", category="deployment", title="New model deployed",
                  message=f"Random Forest Classifier {v_rf.version} is live in Development", deployment_id=dep_by_slug["random-forest-api"].id,
                  read=True, resolved=True),
            Alert(ts=ago(days=2, hours=8), severity="critical", kind="run_failed", category="experiment", title="exp-25 failed",
                  message="CUDA out of memory at epoch 22 (seeded history)", read=True, resolved=True),
        ])
        from app.routers.settings import _mask, fernet

        for provider, value in [("OpenAI", "sk-demo-0000-local-placeholder-key"), ("Hugging Face", "hf_demo_local_placeholder_token"),
                                ("NVIDIA", "nvapi-demo-local-placeholder"), ("AWS", "AKIADEMOLOCALPLACEHOLDER"),
                                ("Gemini", "AIzaDemoLocalPlaceholderKey")]:
            s.add(ApiKey(provider=provider, label=f"{provider} (demo placeholder)", ciphertext=fernet.encrypt(value.encode()).decode(),
                         masked=_mask(provider, value), owner_id=H, created_at=ago(days=6)))
        s.commit()
    settings_store.update({"workspace": {"default_project": "exp-27"}})
    print(f"[seed] done in {time.perf_counter() - t0:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Mini MLOps demo data")
    parser.add_argument("--reset", action="store_true", help="wipe the database and generated storage first")
    args = parser.parse_args()
    seed(reset=args.reset)


if __name__ == "__main__":
    main()
