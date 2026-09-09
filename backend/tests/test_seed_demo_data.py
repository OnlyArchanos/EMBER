"""
Tests for scripts/seed_demo_data.py.

Guarantees that seed_demo_data.py is fully idempotent across multiple runs
and across different simulated calendar dates without duplicate accumulation.
"""

import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import FireDetection, FlaggedCase, PersistentSource, Zone
from app.services.classifier import classify_fires
from app.services.flagging import run_flagging
from app.services.persistence import run_persistence
from app.ml import infer
import scripts.seed_demo_data as seeder


@pytest.fixture()
def test_db():
    """In-memory SQLite database isolated for seeder testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    with patch("scripts.seed_demo_data.engine", engine), patch(
        "scripts.seed_demo_data.SessionLocal", TestingSession
    ):
        yield TestingSession
    Base.metadata.drop_all(bind=engine)


def test_cross_day_seeding_idempotency(test_db):
    """
    Seed once, record count, seed again with a different simulated date
    without manually clearing the database:
    - fire_detections row count must remain 249 (never 498).
    - zones count must remain 41.
    - max detection date must be shifted to yesterday relative to each base_date.
    """
    # 1. Run on day 1
    day1 = datetime.date(2026, 9, 9)
    seeder.main(base_date=day1)

    with test_db() as db:
        count_day1 = db.scalar(select(func.count(FireDetection.id)))
        zones_day1 = db.scalar(select(func.count(Zone.id)))
        max_date_day1 = max(f.acq_date for f in db.scalars(select(FireDetection)).all())

    assert count_day1 == 249
    assert zones_day1 == 41
    assert max_date_day1 == day1 - datetime.timedelta(days=1)

    # 2. Run on day 2 (+11 days) WITHOUT clearing DB manually
    day2 = datetime.date(2026, 9, 20)
    seeder.main(base_date=day2)

    with test_db() as db:
        count_day2 = db.scalar(select(func.count(FireDetection.id)))
        zones_day2 = db.scalar(select(func.count(Zone.id)))
        max_date_day2 = max(f.acq_date for f in db.scalars(select(FireDetection)).all())

    # Row count must remain 249, not accumulate to 498
    assert count_day2 == 249
    assert zones_day2 == 41
    assert max_date_day2 == day2 - datetime.timedelta(days=1)


def test_reseed_after_analysis_pipeline_clears_derived_state(test_db):
    """
    Re-running seed_demo_data.py after classification, persistence, and flagging
    must purge previously-derived sources and flags and reset fires to pending.
    """
    infer.load_model()
    day1 = datetime.date(2026, 9, 9)
    seeder.main(base_date=day1)

    # Run analysis pipeline on day 1
    with test_db() as db:
        classify_fires(db)
        run_persistence(db, current_date=day1)
        run_flagging(db)

        assert db.scalar(select(func.count(FireDetection.id))) == 249
        assert db.scalar(select(func.count(PersistentSource.id))) > 0
        assert db.scalar(select(func.count(FlaggedCase.id))) > 0

    # Re-seed on day 2 without manual database deletion
    day2 = datetime.date(2026, 9, 15)
    seeder.main(base_date=day2)

    with test_db() as db:
        # Fires reset to exactly 249 pending rows
        assert db.scalar(select(func.count(FireDetection.id))) == 249
        pending_count = db.scalar(
            select(func.count(FireDetection.id)).where(FireDetection.fire_type == "pending")
        )
        assert pending_count == 249

        # Stale persistent sources and flags from day 1 are purged
        assert db.scalar(select(func.count(PersistentSource.id))) == 0
        assert db.scalar(select(func.count(FlaggedCase.id))) == 0
