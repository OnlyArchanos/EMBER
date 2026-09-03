import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import FireDetection, FlaggedCase, PersistentSource, Zone
from app.services.flagging import run_flagging


@pytest.fixture()
def db_session() -> Session:
    """In-memory SQLite session for isolated model-level tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def test_run_flagging_happy_path(db_session: Session, monkeypatch):
    """
    Confirms a new FlaggedCase is created for an unclassified active source.

    infer.score_persistent_source() is monkeypatched to return a fixed value
    so this test does not require a trained model artifact on disk.  The patch
    targets app.ml.infer.score_persistent_source — the same attribute that
    flagging.py accesses via its `from app.ml import infer` module reference.
    Using 0.7 (not 0.5) so the assertion distinguishes the real wired call
    from the old placeholder that always returned 0.5.
    """
    monkeypatch.setattr(
        "app.ml.infer.score_persistent_source",
        lambda ps, members, gdf_zones: 0.7,
    )

    # Setup Zone
    industrial_zone = Zone(
        zone_type="industrial",
        geometry="POLYGON ((9 9, 11 9, 11 11, 9 11, 9 9))"
    )
    db_session.add(industrial_zone)
    db_session.commit()

    # Setup PersistentSource (Unclassified)
    ps = PersistentSource(
        cluster_id=1,
        centroid_latitude=0.0,
        centroid_longitude=0.0,
        first_seen=datetime.date.today() - datetime.timedelta(days=3),
        last_seen=datetime.date.today(),
        days_active=4,
        member_count=4,
        zone_type_at_location=None,  # Unclassified
        status="active"
    )
    db_session.add(ps)
    db_session.commit()

    # Add member fires
    f1 = FireDetection(
        latitude=0.0, longitude=0.0, brightness=300.0, frp=10.0,
        acq_date=datetime.date.today(), acq_time="1200", daynight="d",
        satellite="snpp", confidence="n", fire_type="unclassified",
        cluster_id=1, is_persistent=True
    )
    db_session.add(f1)
    db_session.commit()

    # Run flagging
    count = run_flagging(db_session)
    assert count == 1

    fc = db_session.query(FlaggedCase).first()
    assert fc is not None
    assert fc.persistent_source_id == ps.id
    # 0.7 from the monkeypatched infer — confirms real wiring, not old 0.5 mock.
    assert fc.anomaly_score == 0.7
    assert fc.nearest_zone_type == "industrial"
    assert fc.nearest_zone_distance_m > 0
    # case_note is None: the placeholder auto-note was removed with the mock function.
    assert fc.case_note is None


def test_run_flagging_no_duplicates(db_session: Session):
    """
    Confirms that a source with an existing FlaggedCase is skipped.

    No monkeypatch needed: run_flagging() returns 0 (count == 0) before
    reaching the scoring call, so infer.score_persistent_source() is never
    invoked in this test path.
    """
    ps = PersistentSource(
        cluster_id=1,
        centroid_latitude=0.0,
        centroid_longitude=0.0,
        first_seen=datetime.date.today() - datetime.timedelta(days=3),
        last_seen=datetime.date.today(),
        days_active=4,
        member_count=4,
        zone_type_at_location=None,
        status="active"
    )
    db_session.add(ps)
    db_session.commit()

    f1 = FireDetection(
        latitude=0.0, longitude=0.0, brightness=300.0, frp=10.0,
        acq_date=datetime.date.today(), acq_time="1200", daynight="d",
        satellite="snpp", confidence="n", fire_type="unclassified",
        cluster_id=1, is_persistent=True
    )
    db_session.add(f1)
    db_session.commit()

    # Create existing flag
    fc_existing = FlaggedCase(
        persistent_source_id=ps.id,
        anomaly_score=0.9,
        nearest_zone_distance_m=100.0,
        status="open"
    )
    db_session.add(fc_existing)
    db_session.commit()

    # Run flagging again
    count = run_flagging(db_session)
    assert count == 0  # Should skip the one that already has a flag

    flags = db_session.query(FlaggedCase).all()
    assert len(flags) == 1


def test_run_flagging_dismissed_duplicate(db_session: Session):
    """
    Confirms that a source with a dismissed FlaggedCase is also skipped.

    No monkeypatch needed: the idempotency guard fires before scoring, so
    infer.score_persistent_source() is never invoked in this test path.
    """
    ps = PersistentSource(
        cluster_id=1,
        centroid_latitude=0.0,
        centroid_longitude=0.0,
        first_seen=datetime.date.today() - datetime.timedelta(days=3),
        last_seen=datetime.date.today(),
        days_active=4,
        member_count=4,
        zone_type_at_location=None,
        status="active"
    )
    db_session.add(ps)
    db_session.commit()

    f1 = FireDetection(
        latitude=0.0, longitude=0.0, brightness=300.0, frp=10.0,
        acq_date=datetime.date.today(), acq_time="1200", daynight="d",
        satellite="snpp", confidence="n", fire_type="unclassified",
        cluster_id=1, is_persistent=True
    )
    db_session.add(f1)
    db_session.commit()

    # Create existing flag with dismissed status
    fc_existing = FlaggedCase(
        persistent_source_id=ps.id,
        anomaly_score=0.9,
        nearest_zone_distance_m=100.0,
        status="dismissed"
    )
    db_session.add(fc_existing)
    db_session.commit()

    # Run flagging again
    count = run_flagging(db_session)
    assert count == 0  # Should skip the one that already has a flag

    flags = db_session.query(FlaggedCase).all()
    assert len(flags) == 1
