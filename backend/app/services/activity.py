"""Acting-user resolution, the activity feed and alert creation."""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header
from sqlmodel import Session, select

from app.db import get_session, session_scope
from app.models import Activity, Alert, User
from app.services.hub import hub
from app.utils import utcnow

DEFAULT_USERNAME = "harshan"


def resolve_user(session: Session, username: Optional[str]) -> Optional[User]:
    if username:
        user = session.exec(select(User).where(User.username == username.strip().lower())).first()
        if user:
            return user
    user = session.exec(select(User).where(User.username == DEFAULT_USERNAME)).first()
    return user or session.exec(select(User).order_by(User.id)).first()


def get_actor(
    x_user: Optional[str] = Header(default=None, alias="X-User"),
    session: Session = Depends(get_session),
) -> Optional[User]:
    """The workspace member performing the request (sent by the HUD as X-User)."""
    return resolve_user(session, x_user)


def add_activity(session: Session, user_id: Optional[int], kind: str, action: str, message: str, link: str = "") -> None:
    """Stage an activity row in the caller's session (caller commits)."""
    session.add(Activity(user_id=user_id, kind=kind, action=action, message=message, link=link, ts=utcnow()))


def log_activity(user_id: Optional[int], kind: str, action: str, message: str, link: str = "") -> None:
    """Record an activity row from a background thread."""
    with session_scope() as s:
        add_activity(s, user_id, kind, action, message, link)
        s.commit()


def raise_alert(
    severity: str,
    kind: str,
    category: str,
    title: str,
    message: str,
    deployment_id: Optional[int] = None,
    resolved: bool = True,
) -> Alert:
    with session_scope() as s:
        alert = Alert(
            severity=severity,
            kind=kind,
            category=category,
            title=title,
            message=message,
            deployment_id=deployment_id,
            resolved=resolved,
            read=False,
            ts=utcnow(),
        )
        s.add(alert)
        s.commit()
        s.refresh(alert)
    hub.publish("alerts", {"type": "alert", "id": alert.id, "severity": severity, "kind": kind, "title": title})
    return alert
