"""Dataset file handling: profiling, quality score, previews, image samples."""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from pandas.api.types import is_numeric_dtype

from app.services.features import load_frame
from app.utils import to_jsonable

TABULAR_EXT = {".csv", ".parquet", ".xlsx", ".xls"}
ALLOWED_EXT = TABULAR_EXT | {".zip"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
TARGET_HINTS = ["target", "label", "class", "y", "outcome", "destination_type", "failure", "churn", "species"]
TIME_HINTS = re.compile(r"(time|date|timestamp|datetime)", re.I)
MAX_SAMPLES = 8


def detect_format(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise ValueError("Unsupported file type. Upload CSV, Parquet, Excel or ZIP.")
    return ext.lstrip(".")


def guess_target(df: pd.DataFrame) -> Optional[str]:
    lowered = {str(c).lower(): c for c in df.columns}
    for hint in TARGET_HINTS:
        if hint in lowered:
            return lowered[hint]
    return df.columns[-1] if len(df.columns) else None


def infer_type(df: pd.DataFrame) -> str:
    for col in df.columns:
        if TIME_HINTS.search(str(col)):
            try:
                parsed = pd.to_datetime(df[col].head(200), errors="coerce")
                if parsed.notna().mean() > 0.9:
                    return "Time Series"
            except Exception:  # noqa: BLE001
                pass
    text_cols = [c for c in df.columns if df[c].dtype == object]
    if text_cols:
        avg_len = max(df[c].dropna().astype(str).str.len().mean() or 0 for c in text_cols)
        if avg_len > 40:
            return "Text"
    return "Tabular"


def profile_tabular(path: Path) -> dict[str, Any]:
    df = load_frame(path)
    rows, cols = df.shape
    missing = float(df.isna().mean().mean() * 100) if rows and cols else 0.0
    dups = float(df.duplicated().mean() * 100) if rows else 0.0
    schema = []
    for col in list(df.columns)[:60]:
        s = df[col]
        schema.append({
            "name": str(col),
            "dtype": "numeric" if is_numeric_dtype(s) else "text",
            "missing_pct": round(float(s.isna().mean() * 100), 2),
            "unique": int(s.nunique()),
        })
    return {
        "rows": int(rows), "columns": int(cols), "missing_pct": round(missing, 2), "duplicate_pct": round(dups, 2),
        "quality": round(max(0.0, 100.0 - missing - dups), 1), "schema": schema,
        "dtype": infer_type(df), "target": guess_target(df),
    }


def profile_zip(path: Path, samples_dir: Path) -> dict[str, Any]:
    from PIL import Image

    with zipfile.ZipFile(path) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        images = [m for m in members if Path(m.filename).suffix.lower() in IMAGE_EXT]
        hashes: dict[str, int] = {}
        for m in members:
            if m.file_size > 50 * 1024 * 1024:
                continue
            digest = hashlib.md5(zf.read(m)).hexdigest()
            hashes[digest] = hashes.get(digest, 0) + 1
        dup_count = sum(c - 1 for c in hashes.values() if c > 1)
        samples_dir.mkdir(parents=True, exist_ok=True)
        saved = 0
        for m in images:
            if saved >= MAX_SAMPLES:
                break
            try:
                img = Image.open(io.BytesIO(zf.read(m))).convert("RGB")
                img.thumbnail((320, 240))
                img.save(samples_dir / f"sample_{saved + 1}.jpg", "JPEG", quality=85)
                saved += 1
            except Exception:  # noqa: BLE001 - skip unreadable images
                continue
    total = len(members)
    dup_pct = (dup_count / total * 100) if total else 0.0
    return {
        "rows": total, "columns": 0, "missing_pct": 0.0, "duplicate_pct": round(dup_pct, 2),
        "quality": round(max(0.0, 100.0 - dup_pct), 1),
        "schema": [{"name": "files", "dtype": "file", "missing_pct": 0.0, "unique": total},
                   {"name": "images", "dtype": "file", "missing_pct": 0.0, "unique": len(images)}],
        "dtype": "Image" if images and len(images) >= total / 2 else "Other", "target": None,
    }


def tabular_preview(path: Path, n: int = 8) -> dict[str, Any]:
    df = load_frame(path, max_rows=n)
    return {"kind": "table", "columns": [str(c) for c in df.columns],
            "rows": [to_jsonable(r) for r in df.head(n).to_dict(orient="records")]}
