"""SQLAlchemy engine/session setup.

Defaults to a local SQLite file (`DATABASE_URL=sqlite:///./data/sync.db`) so
the service runs with zero external setup. Swap `DATABASE_URL` to point at
Postgres/MySQL in production -- nothing else in the codebase assumes SQLite.

This is a greenfield project (no pre-existing schema to preserve), so tables
are created with `Base.metadata.create_all()` on startup rather than a
migration tool. Once the schema stabilizes, introduce Alembic before making
further changes -- see backend/README.md "Known limitations".
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from core.config import settings


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_dir(database_url: str) -> None:
    if database_url.startswith("sqlite:///") and database_url != "sqlite:///:memory:":
        path = database_url.removeprefix("sqlite:///")
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)


_ensure_sqlite_dir(settings.database_url)

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    from db import models  # noqa: F401 - register models on Base before create_all

    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
