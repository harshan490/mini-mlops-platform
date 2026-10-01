"""Dataset library: listing, upload + profiling, versions, tags, previews."""
from __future__ import annotations

import shutil
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.config import DATASETS_DIR, MAX_UPLOAD_BYTES, UPLOAD_TMP_DIR
from app.db import get_session
from app.models import Dataset, DatasetVersion, Run, User
from app.services import storage
from app.services.activity import add_activity, get_actor
from app.services.datasets import TABULAR_EXT, detect_format, profile_tabular, profile_zip, tabular_preview
from app.services.users import find_user, owner_brief, user_map
from app.utils import iso, utcnow

router = APIRouter(prefix="/api/datasets", tags=["datasets"])
TYPES = ["Image", "Tabular", "Time Series", "Text", "Other"]
STATUSES = ["Ready", "Processing", "Failed"]


def _versions(session: Session, dataset_id: int) -> list[DatasetVersion]:
    return list(session.exec(select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id)
                             .order_by(DatasetVersion.version)).all())


def _current(versions: list[DatasetVersion], ds: Dataset) -> Optional[DatasetVersion]:
    for v in versions:
        if v.version == ds.current_version:
            return v
    return versions[-1] if versions else None


def _samples_dir(ds_id: int, version: int) -> Path:
    return DATASETS_DIR / str(ds_id) / f"v{version}" / "samples"


def serialize(ds: Dataset, versions: list[DatasetVersion], umap: dict, detail: bool = False) -> dict[str, Any]:
    cur = _current(versions, ds)
    out: dict[str, Any] = {
        "id": ds.id, "name": ds.name, "description": ds.description, "type": ds.dtype, "status": ds.status,
        "tags": ds.tags or [], "target_column": ds.target_column, "is_real": ds.is_real,
        "current_version": ds.current_version, "versions": len(versions),
        "size_bytes": cur.size_bytes if cur else 0, "samples": cur.rows if cur else 0,
        "columns": cur.columns if cur else 0, "quality": cur.quality if cur else 0.0,
        "missing_pct": cur.missing_pct if cur else 0.0, "duplicate_pct": cur.duplicate_pct if cur else 0.0,
        "trainable": bool(ds.is_real and cur and cur.file_path and cur.file_format in {"csv", "parquet", "xlsx", "xls"}),
        "owner": owner_brief(umap, ds.owner_id), "created_at": iso(ds.created_at), "updated_at": iso(ds.updated_at),
    }
    if detail:
        out["version_list"] = [{
            "version": v.version, "size_bytes": v.size_bytes, "rows": v.rows, "columns": v.columns,
            "quality": v.quality, "missing_pct": v.missing_pct, "duplicate_pct": v.duplicate_pct,
            "file_name": v.file_name, "file_format": v.file_format, "has_file": bool(v.file_path),
            "schema": v.schema_info or [], "note": v.note, "created_at": iso(v.created_at),
            "owner": owner_brief(umap, v.owner_id),
        } for v in versions]
    return out


@router.get("")
def list_datasets(q: str = "", type: str = "", status: str = "", sort: str = "recent", owner: str = "",
                  limit: int = Query(200, le=500), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    stmt = select(Dataset)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where((Dataset.name.ilike(like)) | (Dataset.description.ilike(like)) | (Dataset.dtype.ilike(like)))
    if type:
        stmt = stmt.where(Dataset.dtype == type)
    if status:
        stmt = stmt.where(Dataset.status == status)
    if owner:
        user = find_user(session, owner)
        stmt = stmt.where(Dataset.owner_id == (user.id if user else -1))
    rows = session.exec(stmt).all()
    umap = user_map(session)
    all_versions = session.exec(select(DatasetVersion)).all()
    by_ds: dict[int, list[DatasetVersion]] = {}
    for v in sorted(all_versions, key=lambda v: v.version):
        by_ds.setdefault(v.dataset_id, []).append(v)
    items = [serialize(d, by_ds.get(d.id, []), umap) for d in rows]
    if q:  # tags are JSON, filter them in Python
        ql = q.lower()
        tag_hits = {d.id for d in session.exec(select(Dataset)).all() if any(ql in t.lower() for t in (d.tags or []))}
        extra = [serialize(d, by_ds.get(d.id, []), umap) for d in session.exec(select(Dataset)).all()
                 if d.id in tag_hits and d.id not in {i["id"] for i in items}
                 and (not type or d.dtype == type) and (not status or d.status == status)]
        items.extend(extra)
    keys = {
        "recent": (lambda d: d["updated_at"] or "", True),
        "name": (lambda d: d["name"].lower(), False),
        "size": (lambda d: d["size_bytes"], True),
        "quality": (lambda d: d["quality"], True),
        "samples": (lambda d: d["samples"], True),
    }
    key, rev = keys.get(sort, keys["recent"])
    items.sort(key=key, reverse=rev)
    return items[:limit]


@router.get("/stats")
def dataset_stats(session: Session = Depends(get_session)) -> dict[str, Any]:
    datasets = session.exec(select(Dataset)).all()
    versions = session.exec(select(DatasetVersion)).all()
    now = utcnow()
    week = now - timedelta(days=7)
    current = {d.id: d.current_version for d in datasets}
    cur_versions = [v for v in versions if current.get(v.dataset_id) == v.version]
    total_size = sum(v.size_bytes for v in cur_versions)
    new_ds = sum(1 for d in datasets if d.created_at >= week)
    new_versions = [v for v in versions if v.created_at >= week]
    size_added = sum(v.size_bytes for v in cur_versions if v.created_at >= week)

    # Growth: cumulative size of each dataset's newest version as of each day (30 days).
    growth = []
    for i in range(30, -1, -1):
        day_end = (now - timedelta(days=i)).replace(hour=23, minute=59, second=59)
        latest: dict[int, DatasetVersion] = {}
        for v in versions:
            if v.created_at <= day_end and (v.dataset_id not in latest or v.version > latest[v.dataset_id].version):
                latest[v.dataset_id] = v
        growth.append({"date": day_end.date().isoformat(), "size_bytes": sum(v.size_bytes for v in latest.values())})
    types = {t: 0 for t in TYPES}
    for d in datasets:
        types[d.dtype if d.dtype in types else "Other"] += 1
    umap = user_map(session)
    ds_names = {d.id: d.name for d in datasets}
    recent = sorted(versions, key=lambda v: v.created_at, reverse=True)[:6]
    status_of = {d.id: d.status for d in datasets}
    return {
        "total_datasets": len(datasets), "total_size_bytes": total_size, "total_versions": len(versions),
        "delta_datasets": new_ds, "delta_size_bytes": size_added, "delta_versions": len(new_versions),
        "growth": growth,
        "types": [{"type": t, "count": c} for t, c in types.items()],
        "recent_uploads": [{
            "dataset_id": v.dataset_id, "dataset": ds_names.get(v.dataset_id, "?"), "version": v.version,
            "file_name": v.file_name or f"{ds_names.get(v.dataset_id, 'dataset')}_v{v.version}",
            "size_bytes": v.size_bytes, "status": "Completed" if status_of.get(v.dataset_id) != "Failed" else "Failed",
            "created_at": iso(v.created_at), "owner": owner_brief(umap, v.owner_id),
        } for v in recent],
    }


def _save_upload(upload: UploadFile) -> tuple[Path, int]:
    UPLOAD_TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = UPLOAD_TMP_DIR / f"{uuid.uuid4().hex}_{Path(upload.filename or 'upload').name}"
    size = 0
    with tmp.open("wb") as fh:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                fh.close()
                tmp.unlink(missing_ok=True)
                raise HTTPException(413, f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
            fh.write(chunk)
    if size == 0:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, "Uploaded file is empty")
    return tmp, size


def _store_version(session: Session, ds: Dataset, version: int, tmp: Path, filename: str, size: int, fmt: str,
                   actor: Optional[User], note: str) -> tuple[DatasetVersion, dict[str, Any]]:
    dest_dir = DATASETS_DIR / str(ds.id) / f"v{version}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(filename).name
    shutil.move(str(tmp), dest)
    try:
        if fmt == "zip":
            prof = profile_zip(dest, _samples_dir(ds.id, version))
        else:
            prof = profile_tabular(dest)
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise HTTPException(400, f"Could not read the file: {exc}") from exc
    dv = DatasetVersion(dataset_id=ds.id, version=version, file_path=storage.rel(dest), file_name=dest.name,
                        file_format=fmt, size_bytes=size, rows=prof["rows"], columns=prof["columns"],
                        missing_pct=prof["missing_pct"], duplicate_pct=prof["duplicate_pct"], quality=prof["quality"],
                        schema_info=prof["schema"], note=note, owner_id=actor.id if actor else None, created_at=utcnow())
    session.add(dv)
    return dv, prof


@router.post("")
def upload_dataset(file: UploadFile = File(...), name: str = Form(""), description: str = Form(""),
                   tags: str = Form(""), target_column: str = Form(""), session: Session = Depends(get_session),
                   actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    filename = Path(file.filename or "").name
    try:
        fmt = detect_format(filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    ds_name = (name or Path(filename).stem).strip()
    if not ds_name:
        raise HTTPException(400, "Dataset name is required")
    if session.exec(select(Dataset).where(Dataset.name == ds_name)).first():
        raise HTTPException(409, f"Dataset '{ds_name}' already exists; upload a new version instead.")
    tmp, size = _save_upload(file)
    ds = Dataset(name=ds_name, description=description.strip(), status="Processing",
                 tags=[t.strip() for t in tags.split(",") if t.strip()], owner_id=actor.id if actor else None,
                 is_real=True, current_version=1)
    session.add(ds)
    session.commit()
    session.refresh(ds)
    try:
        dv, prof = _store_version(session, ds, 1, tmp, filename, size, fmt, actor, "Initial upload")
    except HTTPException:
        session.delete(ds)
        session.commit()
        tmp.unlink(missing_ok=True)
        raise
    ds.dtype = prof["dtype"]
    ds.status = "Ready"
    if fmt != "zip":
        ds.target_column = target_column.strip() or prof["target"]
    if not ds.description:
        ds.description = f"Uploaded {filename}"
    ds.updated_at = utcnow()
    session.add(ds)
    add_activity(session, actor.id if actor else None, "dataset", "uploaded",
                 f"Uploaded dataset {ds.name} ({prof['rows']:,} rows, quality {prof['quality']:.0f}%)", f"/datasets?select={ds.id}")
    session.commit()
    return serialize(ds, _versions(session, ds.id), user_map(session), detail=True)


@router.post("/bulk-delete")
def bulk_delete(body: dict[str, list[int]], session: Session = Depends(get_session),
                actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    results = []
    for ds_id in body.get("ids", []):
        try:
            _delete(session, ds_id, actor)
            results.append({"id": ds_id, "deleted": True})
        except HTTPException as exc:
            results.append({"id": ds_id, "deleted": False, "error": exc.detail})
    return {"results": results}


@router.get("/{dataset_id}")
def get_dataset(dataset_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    ds = session.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(404, "Dataset not found")
    out = serialize(ds, _versions(session, ds.id), user_map(session), detail=True)
    runs = session.exec(select(Run).where(Run.dataset_id == ds.id, Run.kind != "trial")).all()
    out["used_by_runs"] = [{"id": r.id, "code": r.code, "status": r.status} for r in runs]
    return out


class DatasetPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    status: Optional[str] = None
    target_column: Optional[str] = None
    current_version: Optional[int] = None


@router.patch("/{dataset_id}")
def patch_dataset(dataset_id: int, body: DatasetPatch, session: Session = Depends(get_session),
                  actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    ds = session.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(404, "Dataset not found")
    changes = []
    if body.name is not None and body.name.strip() != ds.name:
        new = body.name.strip()
        if not new:
            raise HTTPException(400, "Name cannot be empty")
        if session.exec(select(Dataset).where(Dataset.name == new)).first():
            raise HTTPException(409, "Another dataset already uses that name")
        ds.name = new
        changes.append("name")
    if body.description is not None:
        ds.description = body.description.strip()
        changes.append("description")
    if body.tags is not None:
        clean = []
        for t in body.tags:
            t = str(t).strip().lower()
            if t and t not in clean:
                if len(t) > 32:
                    raise HTTPException(400, "Tags must be at most 32 characters")
                clean.append(t)
        ds.tags = clean
        changes.append("tags")
    if body.status is not None:
        if body.status not in STATUSES:
            raise HTTPException(400, f"status must be one of {STATUSES}")
        ds.status = body.status
        changes.append("status")
    if body.target_column is not None:
        ds.target_column = body.target_column.strip() or None
        changes.append("target")
    if body.current_version is not None:
        if not any(v.version == body.current_version for v in _versions(session, ds.id)):
            raise HTTPException(404, "Version not found")
        ds.current_version = body.current_version
        changes.append("current version")
    ds.updated_at = utcnow()
    session.add(ds)
    if changes:
        add_activity(session, actor.id if actor else None, "dataset", "updated",
                     f"Updated {', '.join(changes)} of dataset {ds.name}", f"/datasets?select={ds.id}")
    session.commit()
    return serialize(ds, _versions(session, ds.id), user_map(session), detail=True)


def _delete(session: Session, dataset_id: int, actor: Optional[User]) -> None:
    ds = session.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(404, "Dataset not found")
    runs = session.exec(select(Run).where(Run.dataset_id == ds.id)).all()
    if runs:
        codes = ", ".join(sorted({r.code for r in runs if r.kind != "trial"})[:4])
        raise HTTPException(409, f"{ds.name} is used by runs {codes}; delete those runs first to keep lineage intact.")
    for v in _versions(session, ds.id):
        session.delete(v)
    name = ds.name
    session.delete(ds)
    add_activity(session, actor.id if actor else None, "dataset", "deleted", f"Deleted dataset {name}", "/datasets")
    session.commit()
    shutil.rmtree(DATASETS_DIR / str(dataset_id), ignore_errors=True)


@router.delete("/{dataset_id}")
def delete_dataset(dataset_id: int, session: Session = Depends(get_session),
                   actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    _delete(session, dataset_id, actor)
    return {"deleted": True, "id": dataset_id}


@router.post("/{dataset_id}/versions")
def new_version(dataset_id: int, file: UploadFile = File(...), note: str = Form(""),
                session: Session = Depends(get_session), actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    ds = session.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(404, "Dataset not found")
    filename = Path(file.filename or "").name
    try:
        fmt = detect_format(filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    versions = _versions(session, ds.id)
    number = (max(v.version for v in versions) + 1) if versions else 1
    tmp, size = _save_upload(file)
    try:
        _dv, prof = _store_version(session, ds, number, tmp, filename, size, fmt, actor, note.strip() or f"Version {number}")
    finally:
        tmp.unlink(missing_ok=True)
    ds.current_version = number
    ds.is_real = True
    ds.status = "Ready"
    if fmt != "zip" and not ds.target_column:
        ds.target_column = prof["target"]
    ds.updated_at = utcnow()
    session.add(ds)
    add_activity(session, actor.id if actor else None, "dataset", "version",
                 f"Uploaded {ds.name} v{number} ({prof['rows']:,} rows)", f"/datasets?select={ds.id}")
    session.commit()
    return serialize(ds, _versions(session, ds.id), user_map(session), detail=True)


def _version_row(session: Session, ds: Dataset, version: Optional[int]) -> DatasetVersion:
    number = version or ds.current_version
    dv = session.exec(select(DatasetVersion).where(DatasetVersion.dataset_id == ds.id, DatasetVersion.version == number)).first()
    if dv is None:
        raise HTTPException(404, "Version not found")
    return dv


@router.get("/{dataset_id}/preview")
def preview(dataset_id: int, version: Optional[int] = None, session: Session = Depends(get_session)) -> dict[str, Any]:
    ds = session.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(404, "Dataset not found")
    dv = _version_row(session, ds, version)
    samples = _samples_dir(ds.id, dv.version)
    if samples.exists():
        files = sorted(p.name for p in samples.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
        if files:
            note = "" if dv.file_path else "Synthetic sample renders (metadata-only dataset)"
            return {"kind": "images", "version": dv.version, "note": note,
                    "images": [f"/api/datasets/{ds.id}/samples/{dv.version}/{f}" for f in files]}
    path = storage.resolve(dv.file_path)
    if path is not None and path.exists() and path.suffix.lower() in TABULAR_EXT:
        try:
            return {**tabular_preview(path), "version": dv.version, "note": ""}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"Preview failed: {exc}") from exc
    return {"kind": "none", "version": dv.version,
            "note": "Metadata-only dataset: the files are not stored on this machine, so there is nothing to preview."}


@router.get("/{dataset_id}/samples/{version}/{filename}")
def sample_file(dataset_id: int, version: int, filename: str) -> FileResponse:
    path = _samples_dir(dataset_id, version) / Path(filename).name
    if not path.exists():
        raise HTTPException(404, "Sample not found")
    return FileResponse(path)


@router.get("/{dataset_id}/download")
def download(dataset_id: int, version: Optional[int] = None, session: Session = Depends(get_session)) -> FileResponse:
    ds = session.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(404, "Dataset not found")
    dv = _version_row(session, ds, version)
    path = storage.resolve(dv.file_path)
    if path is None or not path.exists():
        raise HTTPException(404, "This version is metadata-only; no file is stored locally.")
    return FileResponse(path, filename=f"{ds.name}_v{dv.version}{path.suffix}")
