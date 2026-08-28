"""Tests for ORM model behavior — specifically FlaggedCase.updated_at auto-refresh."""

import datetime
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import FlaggedCase, PersistentSource


@pytest.fixture()
def db_session() -> Session:
    """In-memory SQLite session for isolated model-level tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


class TestFlaggedCaseUpdatedAt:
    """FlaggedCase.updated_at must auto-refresh when a column is modified,
    thanks to the onupdate hook added in the review fix."""

    def test_updated_at_changes_on_update(self, db_session: Session) -> None:
        # Create a PersistentSource (FK target) first.
        ps = PersistentSource(
            cluster_id=1,
            first_seen=datetime.date(2025, 1, 1),
            last_seen=datetime.date(2025, 1, 5),
            days_active=5,
            member_count=10,
            status="active",
        )
        db_session.add(ps)
        db_session.flush()

        fc = FlaggedCase(
            persistent_source_id=ps.id,
            anomaly_score=0.85,
            nearest_zone_type="industrial",
            nearest_zone_distance_m=1200.0,
            status="open",
        )
        db_session.add(fc)
        db_session.flush()

        original_updated_at = fc.updated_at
        assert original_updated_at is not None

        # Small sleep to ensure the timestamp changes (sub-second resolution).
        time.sleep(0.05)

        # Simulate a PATCH: update the status.
        fc.status = "reviewed"
        db_session.flush()

        # SQLAlchemy's onupdate fires on flush for dirty attributes.
        assert fc.updated_at is not None
        assert fc.updated_at > original_updated_at
