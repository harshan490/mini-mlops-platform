"""SQLite engine and session helpers (SQLModel)."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from app.config import DB_PATH

engine = create_engine(
    f"sqlite:///{DB_PATH.as_posix()}",
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record) -> None:  # pragma: no cover - driver hook
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()


def init_db() -> None:
    import app.models  # noqa: F401  (registers tables)

    SQLModel.metadata.create_all(engine)


def drop_db() -> None:
    import app.models  # noqa: F401

    SQLModel.metadata.drop_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """Session for background threads. Commits are explicit."""
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
