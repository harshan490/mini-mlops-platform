"""Workspace settings, integration checks, encrypted API keys and local auth."""
from __future__ import annotations

import socket
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlmodel import Session, select

from app.config import FERNET_KEY, JWT_ALGORITHM, JWT_SECRET
from app.db import get_session
from app.models import ApiKey, User
from app.services.activity import add_activity, get_actor
from app.services.settings_store import SESSION_TIMEOUTS, settings_store, verify_password
from app.utils import iso, utcnow

router = APIRouter(tags=["settings"])
fernet = Fernet(FERNET_KEY.encode())
PROVIDERS = ["OpenAI", "Hugging Face", "NVIDIA", "AWS", "Gemini", "Anthropic", "Other"]


# ------------------------------------------------------------------ settings
@router.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return settings_store.public()


@router.put("/api/settings")
def put_settings(patch: dict[str, Any], session: Session = Depends(get_session), actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    try:
        result = settings_store.update(patch)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    add_activity(session, actor.id if actor else None, "settings", "saved", f"Saved settings ({', '.join(sorted(patch))})", "/settings")
    session.commit()
    return result


@router.post("/api/settings/reset")
def reset_settings(session: Session = Depends(get_session), actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    result = settings_store.reset()
    add_activity(session, actor.id if actor else None, "settings", "reset", "Reset settings to defaults", "/settings")
    session.commit()
    return result


# -------------------------------------------------------------- integrations
class TestBody(BaseModel):
    url: Optional[str] = None


def _http_check(url: str, path: str) -> tuple[bool, str, float]:
    started = time.perf_counter()
    try:
        r = httpx.get(url.rstrip("/") + path, timeout=2.0)
        ms = (time.perf_counter() - started) * 1000
        return r.status_code < 500, f"HTTP {r.status_code}", ms
    except httpx.HTTPError as exc:
        return False, type(exc).__name__, (time.perf_counter() - started) * 1000


def _tcp_check(url: str, default_port: int) -> tuple[bool, str, float]:
    parsed = urlparse(url if "://" in url else f"tcp://{url}")
    host, port = parsed.hostname or "localhost", parsed.port or default_port
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True, f"TCP {host}:{port} open", (time.perf_counter() - started) * 1000
    except OSError as exc:
        return False, f"TCP {host}:{port} {exc.__class__.__name__}", (time.perf_counter() - started) * 1000


@router.post("/api/integrations/{name}/test")
def test_integration(name: str, body: Optional[TestBody] = None) -> dict[str, Any]:
    integrations = settings_store.get()["integrations"]
    if name not in integrations:
        raise HTTPException(404, f"Unknown integration {name}")
    url = (body.url if body and body.url else integrations[name]["url"]).strip()
    if name == "mlflow":
        ok, detail, ms = _http_check(url, "/health")
    elif name == "prometheus":
        ok, detail, ms = _http_check(url, "/-/healthy")
    else:
        ok, detail, ms = _tcp_check(url, 5432)
    return {"name": name, "url": url, "connected": ok, "detail": detail, "latency_ms": round(ms, 1), "checked_at": iso(utcnow())}


# ------------------------------------------------------------------ API keys
def _mask(provider: str, value: str) -> str:
    prefix = value[:4] if len(value) > 8 else value[:2]
    return f"{prefix}{'•' * 14}{value[-4:] if len(value) > 8 else ''}"


def _serialize_key(k: ApiKey) -> dict[str, Any]:
    return {"id": k.id, "provider": k.provider, "label": k.label, "masked": k.masked, "created_at": iso(k.created_at)}


@router.get("/api/apikeys")
def list_keys(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_serialize_key(k) for k in session.exec(select(ApiKey).order_by(ApiKey.id)).all()]


class KeyBody(BaseModel):
    provider: str
    value: str
    label: str = ""


@router.post("/api/apikeys")
def add_key(body: KeyBody, session: Session = Depends(get_session), actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    value = body.value.strip()
    if body.provider not in PROVIDERS:
        raise HTTPException(400, f"provider must be one of {PROVIDERS}")
    if len(value) < 8:
        raise HTTPException(400, "Key looks too short (min 8 characters)")
    key = ApiKey(provider=body.provider, label=body.label.strip() or body.provider, ciphertext=fernet.encrypt(value.encode()).decode(),
                 masked=_mask(body.provider, value), owner_id=actor.id if actor else None)
    session.add(key)
    add_activity(session, key.owner_id, "settings", "apikey", f"Added {body.provider} API key", "/settings")
    session.commit()
    session.refresh(key)
    return _serialize_key(key)


@router.delete("/api/apikeys/{key_id}")
def delete_key(key_id: int, session: Session = Depends(get_session), actor: Optional[User] = Depends(get_actor)) -> dict[str, Any]:
    key = session.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(404, "Key not found")
    add_activity(session, actor.id if actor else None, "settings", "apikey", f"Deleted {key.provider} API key", "/settings")
    session.delete(key)
    session.commit()
    return {"deleted": True}


@router.get("/api/apikeys/{key_id}/reveal")
def reveal_key(key_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    key = session.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(404, "Key not found")
    try:
        value = fernet.decrypt(key.ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise HTTPException(500, "Key cannot be decrypted with the current FERNET_KEY") from exc
    return {"id": key.id, "value": value}


# ---------------------------------------------------------------------- auth
class LoginBody(BaseModel):
    username: str
    password: str


def token_ttl_hours() -> int:
    return SESSION_TIMEOUTS.get(settings_store.get()["security"].get("session_timeout", "24h"), 24)


def create_token(username: str) -> tuple[str, datetime]:
    exp = datetime.now(timezone.utc) + timedelta(hours=token_ttl_hours())
    return jwt.encode({"sub": username, "exp": exp}, JWT_SECRET, algorithm=JWT_ALGORITHM), exp


def decode_token(token: str) -> Optional[str]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM]).get("sub")
    except JWTError:
        return None


def bearer(request: Request) -> Optional[str]:
    header = request.headers.get("authorization", "")
    return header[7:] if header.lower().startswith("bearer ") else None


@router.post("/api/auth/login")
def login(body: LoginBody) -> dict[str, Any]:
    username, pw_hash = settings_store.admin_credentials()
    if body.username.strip() != username or not verify_password(body.password, pw_hash):
        time.sleep(0.4)  # slow down guessing
        raise HTTPException(401, "Invalid username or password")
    token, exp = create_token(username)
    return {"access_token": token, "token_type": "bearer", "expires_at": exp.isoformat(), "username": username}


@router.get("/api/auth/status")
def auth_status(request: Request) -> dict[str, Any]:
    required = bool(settings_store.get()["security"].get("require_auth"))
    token = bearer(request)
    user = decode_token(token) if token else None
    return {"require_auth": required, "authenticated": user is not None, "username": user,
            "admin_username": settings_store.admin_credentials()[0]}


class PasswordBody(BaseModel):
    current_password: str
    new_password: str
    username: Optional[str] = None


@router.post("/api/auth/password")
def change_password(body: PasswordBody) -> dict[str, Any]:
    username, pw_hash = settings_store.admin_credentials()
    if not verify_password(body.current_password, pw_hash):
        raise HTTPException(401, "Current password is incorrect")
    if len(body.new_password) < 4:
        raise HTTPException(400, "New password must be at least 4 characters")
    new_user = (body.username or username).strip() or username
    settings_store.set_admin_password(new_user, body.new_password)
    return {"updated": True, "username": new_user}
