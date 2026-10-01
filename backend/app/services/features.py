"""Tabular feature handling shared by training, serving and drift detection.

Classes defined here end up inside joblib artifacts, so their import path
(``app.services.features``) must stay stable.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype

MAX_CATEGORIES = 30
PSI_EPS = 1e-4


def load_frame(path: str | Path, max_rows: int | None = None) -> pd.DataFrame:
    """Read a tabular dataset file into a DataFrame."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        try:
            df = pd.read_csv(path, nrows=max_rows)
        except UnicodeDecodeError:
            df = pd.read_csv(path, nrows=max_rows, encoding="latin1")
    elif suffix == ".parquet":
        df = pd.read_parquet(path)
        if max_rows:
            df = df.head(max_rows)
    elif suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(path, nrows=max_rows)
    elif suffix == ".zip":
        raise ValueError("ZIP datasets hold files (for example images); tabular training needs CSV, Parquet or Excel.")
    else:
        raise ValueError(f"Unsupported dataset format: {suffix}")
    df.columns = [str(c).strip() for c in df.columns]
    return df


class FeatureEncoder:
    """Numeric passthrough (median-imputed) + one-hot for low-cardinality text."""

    def fit(self, X: pd.DataFrame) -> "FeatureEncoder":
        self.numeric: list[str] = []
        self.categorical: dict[str, list[str]] = {}
        self.medians: dict[str, float] = {}
        self.modes: dict[str, str] = {}
        for col in X.columns:
            series = X[col]
            if is_bool_dtype(series) or is_numeric_dtype(series):
                values = pd.to_numeric(series, errors="coerce")
                if values.notna().sum() == 0:
                    continue
                self.numeric.append(col)
                self.medians[col] = float(values.median())
            else:
                non_null = series.dropna().astype(str)
                uniques = non_null.unique()
                if 0 < len(uniques) <= MAX_CATEGORIES:
                    self.categorical[col] = sorted(uniques.tolist())
                    self.modes[col] = str(non_null.mode().iloc[0])
        self.input_columns: list[str] = self.numeric + list(self.categorical)
        self.feature_names: list[str] = self.numeric + [
            f"{col}={val}" for col, vals in self.categorical.items() for val in vals
        ]
        if not self.feature_names:
            raise ValueError("No usable feature columns (need numeric or low-cardinality text columns).")
        return self

    def transform(self, X: pd.DataFrame) -> np.ndarray:
        n = len(X)
        out = np.zeros((n, len(self.feature_names)), dtype=np.float64)
        for i, col in enumerate(self.numeric):
            if col in X.columns:
                values = pd.to_numeric(X[col], errors="coerce").astype(float)
                out[:, i] = values.fillna(self.medians[col]).to_numpy()
            else:
                out[:, i] = self.medians[col]
        j = len(self.numeric)
        for col, vals in self.categorical.items():
            if col in X.columns:
                series = X[col]
                filled = series.where(series.notna(), self.modes[col]).astype(str)
            else:
                filled = pd.Series([self.modes[col]] * n)
            arr = filled.to_numpy()
            for val in vals:
                out[:, j] = (arr == val).astype(np.float64)
                j += 1
        return out


class BoosterModel:
    """sklearn-like wrapper around a native XGBoost booster."""

    def __init__(self, booster: Any, task: str, n_classes: int) -> None:
        self.booster = booster
        self.task = task
        self.n_classes = n_classes

    def _raw(self, X: np.ndarray) -> np.ndarray:
        import xgboost as xgb

        return self.booster.predict(xgb.DMatrix(X))

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        p = self._raw(X)
        if self.n_classes == 2:
            p = np.asarray(p, dtype=float).reshape(-1)
            return np.column_stack([1.0 - p, p])
        return np.asarray(p, dtype=float).reshape(len(X), self.n_classes)

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.task == "classification":
            return np.argmax(self.predict_proba(X), axis=1)
        return np.asarray(self._raw(X), dtype=float).reshape(-1)


def _numeric_edges(values: np.ndarray, bins: int = 10) -> list[float]:
    values = values[~np.isnan(values)]
    if values.size == 0:
        return []
    edges = np.unique(np.quantile(values, np.linspace(0, 1, bins + 1)))
    return [float(e) for e in edges[1:-1]]  # interior cut points


def _bucketize(values: np.ndarray, cuts: list[float]) -> np.ndarray:
    return np.searchsorted(np.asarray(cuts, dtype=float), values, side="right")


def _proportions(bucket_ids: np.ndarray, n_buckets: int) -> list[float]:
    counts = np.bincount(bucket_ids, minlength=n_buckets).astype(float)
    total = counts.sum()
    if total == 0:
        return [0.0] * n_buckets
    return (counts / total).tolist()


def build_reference(X_raw: pd.DataFrame, encoder: FeatureEncoder, predictions: list[Any], task: str) -> dict[str, Any]:
    """Training-time distributions used later for PSI drift detection."""
    features: dict[str, Any] = {}
    for col in encoder.numeric:
        vals = pd.to_numeric(X_raw[col], errors="coerce").fillna(encoder.medians[col]).to_numpy(float)
        cuts = _numeric_edges(vals)
        expected = _proportions(_bucketize(vals, cuts), len(cuts) + 1)
        features[col] = {"type": "numeric", "cuts": cuts, "expected": expected}
    for col, cats in encoder.categorical.items():
        series = X_raw[col].where(X_raw[col].notna(), encoder.modes[col]).astype(str)
        counts = series.value_counts(normalize=True)
        features[col] = {"type": "categorical", "labels": cats, "expected": [float(counts.get(c, 0.0)) for c in cats]}
    if task == "classification":
        labels = sorted({str(p) for p in predictions})
        counts = pd.Series([str(p) for p in predictions]).value_counts(normalize=True)
        pred_ref = {"type": "categorical", "labels": labels, "expected": [float(counts.get(l, 0.0)) for l in labels]}
    else:
        vals = np.asarray(predictions, dtype=float)
        cuts = _numeric_edges(vals)
        pred_ref = {"type": "numeric", "cuts": cuts, "expected": _proportions(_bucketize(vals, cuts), len(cuts) + 1)}
    return {"features": features, "prediction": pred_ref}


def actual_proportions(ref: dict[str, Any], values: list[Any]) -> list[float]:
    if ref["type"] == "numeric":
        arr = pd.to_numeric(pd.Series(values), errors="coerce").dropna().to_numpy(float)
        if arr.size == 0:
            return [0.0] * len(ref["expected"])
        return _proportions(_bucketize(arr, ref["cuts"]), len(ref["cuts"]) + 1)
    labels = ref["labels"]
    series = pd.Series([str(v) for v in values if v is not None])
    if series.empty:
        return [0.0] * len(labels)
    counts = series.value_counts(normalize=True)
    return [float(counts.get(l, 0.0)) for l in labels]


def psi(expected: list[float], actual: list[float]) -> float:
    """Population Stability Index. >0.25 is conventionally significant drift."""
    e = np.clip(np.asarray(expected, dtype=float), PSI_EPS, None)
    a = np.clip(np.asarray(actual, dtype=float), PSI_EPS, None)
    e = e / e.sum()
    a = a / a.sum()
    return float(np.sum((a - e) * np.log(a / e)))
