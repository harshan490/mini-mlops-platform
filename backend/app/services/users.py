"""User lookups shared by serializers."""
from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.models import User


def user_map(session: Session) -> dict[int, dict[str, Any]]:
    return {
        u.id: {"id": u.id, "username": u.username, "display_name": u.display_name, "accent": u.accent}
        for u in session.exec(select(User)).all()
    }


def owner_brief(umap: dict[int, dict[str, Any]], owner_id: Optional[int]) -> Optional[dict[str, Any]]:
    return umap.get(owner_id) if owner_id else None


def find_user(session: Session, username: Optional[str]) -> Optional[User]:
    if not username:
        return None
    return session.exec(select(User).where(User.username == username.strip().lower())).first()
