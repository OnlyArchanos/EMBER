"""
SQLAlchemy engine, session factory, declarative base, and FastAPI
dependency for the SIH26162 fire-detection backend.  This module
contains only connection/session wiring — no business logic of any kind.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base that all ORM model classes inherit from."""


engine = create_engine(
    settings.DATABASE_URL,
    # SQLite requires this flag for multi-threaded use (e.g. FastAPI + APScheduler).
    # For other databases the argument is silently ignored, so it is safe to keep.
    connect_args={"check_same_thread": False}
    if settings.DATABASE_URL.startswith("sqlite")
    else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session and ensures it is
    closed after the request, even if an exception is raised."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
