"""Database engine, session factory, and a lightweight connectivity check.

The connection string (with credentials) comes from settings, which reads it
from the environment — never hard-coded. We intentionally do not log the URL.
"""
from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from .models import Base

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yields a session and always closes it."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def check_db() -> bool:
    """Return True if the database accepts a trivial query."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


__all__ = ["Base", "engine", "SessionLocal", "get_session", "check_db"]
