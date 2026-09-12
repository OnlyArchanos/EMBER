"""
Tests for geocode startup pipeline integration.
Confirms that geocode_fires populates state/district from admin boundaries
and skips already-geocoded rows on subsequent runs.
"""

import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import FireDetection
from app.services.geocode import geocode_fires


test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=test_engine
)


@pytest.fixture(autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


def test_geocode_fires_populates_state_and_skips_subsequent():
    """Verify that geocode_fires resolves state/district for fire detections
    and skips already-resolved records on re-runs."""
    db = TestingSessionLocal()
    try:
        # Sample fire detections near Hazira, Gujarat
        fires_data = [
            FireDetection(
                latitude=21.1009,
                longitude=72.6377,
                brightness=330.0,
                frp=10.0,
                acq_date=datetime.date(2026, 8, 31),
                acq_time="0830",
                daynight="D",
                satellite="noaa20",
                confidence="nominal",
                fire_type="unclassified",
                state=None,
                district=None,
            ),
            FireDetection(
                latitude=21.7604,
                longitude=72.6378,
                brightness=320.0,
                frp=8.0,
                acq_date=datetime.date(2026, 8, 31),
                acq_time="0830",
                daynight="D",
                satellite="noaa20",
                confidence="nominal",
                fire_type="industrial",
                state=None,
                district=None,
            ),
        ]
        db.add_all(fires_data)
        db.commit()

        # First run: should geocode both fires
        updated = geocode_fires(db)
        assert updated >= 2

        # Verify state is populated as "Gujarat"
        records = db.query(FireDetection).all()
        assert len(records) == 2
        for r in records:
            assert r.state == "Gujarat"
            assert r.district is not None

        # Second run: all fires have state populated, so it should skip and return 0
        second_run = geocode_fires(db)
        assert second_run == 0
    finally:
        db.close()
