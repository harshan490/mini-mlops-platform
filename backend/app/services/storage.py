"""Paths inside the storage directory are stored relative to it."""
from __future__ import annotations

from pathlib import Path

from app.config import STORAGE_DIR


def rel(path: str | Path) -> str:
    p = Path(path).resolve()
    try:
        return p.relative_to(STORAGE_DIR.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def resolve(relpath: str | None) -> Path | None:
    if not relpath:
        return None
    p = Path(relpath)
    return p if p.is_absolute() else STORAGE_DIR / p


def display(relpath: str | None) -> str | None:
    """Human-readable path shown in the UI, e.g. storage/runs/exp-29/model.joblib."""
    if not relpath:
        return None
    p = Path(relpath)
    return p.as_posix() if p.is_absolute() else f"storage/{p.as_posix()}"
