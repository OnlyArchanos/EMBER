"""
Tests for persistence.py — covers the regression cases listed in RULES.md §5.

Key invariants tested:
- Noise cluster (label == -1) is excluded from PersistentSource creation.
- PersistentSource identity is stable across runs (keyed by PersistentSource.id,
  never DBSCAN's raw per-run label).
- days_active/member_count accumulate correctly across runs; they never reset.
- fire_type → zone_type translation is applied before storing zone_type_at_location.
"""

import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import FireDetection, PersistentSource
from app.services.persistence import run_persistence


@pytest.fixture()
def db_session() -> Session:
    """In-memory SQLite session for isolated model-level tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _make_fire(
    lat: float,
    lon: float,
    acq_date: datetime.date,
    fire_type: str = "industrial",
) -> FireDetection:
    """Helper: create a minimal FireDetection at the given location and date."""
    return FireDetection(
        latitude=lat,
        longitude=lon,
        brightness=300.0,
        frp=10.0,
        acq_date=acq_date,
        acq_time="1200",
        daynight="d",
        satellite="snpp",
        confidence="n",
        fire_type=fire_type,
    )


def test_persistence_basic_clustering(db_session: Session):
    """A 3-day cluster at one location produces one active PersistentSource."""
    today = datetime.date.today()
    fires = [
        _make_fire(10.0, 10.0, today - datetime.timedelta(days=2)),
        _make_fire(10.0, 10.0, today - datetime.timedelta(days=1)),
        _make_fire(10.0, 10.0, today),
    ]
    # 2-day cluster at a distant location — should not reach MIN_DAYS_ACTIVE.
    fires += [
        _make_fire(20.0, 20.0, today - datetime.timedelta(days=1), fire_type="wildfire"),
        _make_fire(20.0, 20.0, today, fire_type="wildfire"),
    ]
    db_session.add_all(fires)
    db_session.commit()

    count = run_persistence(db_session, current_date=today)
    assert count == 1

    sources = db_session.query(PersistentSource).all()
    assert len(sources) == 1

    ps = sources[0]
    assert ps.days_active == 3
    assert ps.member_count == 3
    assert ps.zone_type_at_location == "industrial"
    assert ps.status == "active"
    # Stored centroid must be set.
    assert ps.centroid_latitude is not None
    assert ps.centroid_longitude is not None
    # cluster_id must always equal the row's own id (data-model.md §PersistentSource).
    assert ps.cluster_id == ps.id


def test_persistence_noise_exclusion(db_session: Session):
    """Widely scattered points (each > 1 km apart) are DBSCAN noise; no PersistentSource created."""
    today = datetime.date.today()
    f1 = _make_fire(10.0, 10.0, today, fire_type="unclassified")
    f2 = _make_fire(20.0, 20.0, today - datetime.timedelta(days=1), fire_type="unclassified")
    f3 = _make_fire(30.0, 30.0, today - datetime.timedelta(days=2), fire_type="unclassified")
    db_session.add_all([f1, f2, f3])
    db_session.commit()

    count = run_persistence(db_session, current_date=today)
    assert count == 0
    assert db_session.query(PersistentSource).count() == 0

    db_session.refresh(f1)
    # DBSCAN marks isolated points as noise (-1).
    assert f1.cluster_id == -1
    assert f1.is_persistent is False


def test_persistence_fire_type_translation(db_session: Session):
    """wildfire → forest and agricultural → farmland translation must be applied to zone_type_at_location."""
    today = datetime.date.today()
    fires = [
        _make_fire(10.0, 10.0, today - datetime.timedelta(days=2), fire_type="wildfire"),
        _make_fire(10.0, 10.0, today - datetime.timedelta(days=1), fire_type="wildfire"),
        _make_fire(10.0, 10.0, today, fire_type="wildfire"),
    ]
    db_session.add_all(fires)
    db_session.commit()

    run_persistence(db_session, current_date=today)

    ps = db_session.query(PersistentSource).first()
    assert ps is not None
    # 'wildfire' must be stored as 'forest' (RULES.md §5).
    assert ps.zone_type_at_location == "forest"


def test_cross_run_stable_identity(db_session: Session):
    """
    Regression for RULES.md §5's cluster-identity rule.

    Two separate run_persistence() calls over the same physical cluster must:
    - Produce exactly one PersistentSource row (no duplicates).
    - Return the identical PersistentSource.id from both runs.
    - Set FireDetection.cluster_id to that same id on every member, both old
      and new, after the second run.
    - Reflect accumulated totals (days_active, member_count) after the second
      run — never reset values to just the current run's detections.
    """
    today = datetime.date.today()

    # Run 1 data: 3 detections spread across 3 days at the same spot.
    f1 = _make_fire(10.0, 10.0, today - datetime.timedelta(days=3))
    f2 = _make_fire(10.0, 10.0, today - datetime.timedelta(days=2))
    f3 = _make_fire(10.0, 10.0, today - datetime.timedelta(days=1))
    db_session.add_all([f1, f2, f3])
    db_session.commit()

    count_run1 = run_persistence(db_session, current_date=today)
    assert count_run1 == 1

    ps_after_run1 = db_session.query(PersistentSource).all()
    assert len(ps_after_run1) == 1, "Run 1 must produce exactly one PersistentSource"

    ps = ps_after_run1[0]
    assert ps.days_active == 3
    assert ps.member_count == 3
    assert ps.cluster_id == ps.id, "cluster_id must always equal the row's own id"
    stable_ps_id = ps.id

    for f in [f1, f2, f3]:
        db_session.refresh(f)
        assert f.cluster_id == stable_ps_id
        assert f.is_persistent is True

    # Run 2: add 2 new detections at the same physical location, a few days later.
    # The new points are close enough to be within EPS_KM and CLUSTER_MATCH_RADIUS_KM.
    f4 = _make_fire(10.0001, 10.0001, today)
    f5 = _make_fire(10.0002, 10.0002, today + datetime.timedelta(days=1))
    db_session.add_all([f4, f5])
    db_session.commit()

    count_run2 = run_persistence(
        db_session, current_date=today + datetime.timedelta(days=1)
    )
    assert count_run2 == 1

    all_sources = db_session.query(PersistentSource).all()
    assert len(all_sources) == 1, (
        "Run 2 must not create a duplicate PersistentSource for the same physical location"
    )

    ps_after_run2 = all_sources[0]

    # The row identity must be identical — same database id, never a new row.
    assert ps_after_run2.id == stable_ps_id, (
        "PersistentSource.id must be stable across runs for the same physical cluster"
    )

    # Accumulated totals must reflect the combined member set, not just run 2's detections.
    # Unique dates: today-3, today-2, today-1, today, today+1 = 5 distinct days.
    assert ps_after_run2.days_active == 5, (
        "days_active must accumulate across runs, not reset to the current run's count"
    )
    assert ps_after_run2.member_count == 5, (
        "member_count must reflect the full combined member set after run 2"
    )

    # Every member — both from run 1 and run 2 — must carry the stable cluster_id.
    for f in [f1, f2, f3, f4, f5]:
        db_session.refresh(f)
        assert f.cluster_id == stable_ps_id, (
            f"FireDetection id={f.id} has cluster_id={f.cluster_id}, expected {stable_ps_id}"
        )
        assert f.is_persistent is True


def test_two_distinct_clusters_stay_separate(db_session: Session):
    """Two clusters far apart each get their own PersistentSource; neither merges into the other."""
    today = datetime.date.today()

    cluster_a = [_make_fire(10.0, 10.0, today - datetime.timedelta(days=i)) for i in range(3)]
    cluster_b = [_make_fire(20.0, 20.0, today - datetime.timedelta(days=i)) for i in range(3)]
    db_session.add_all(cluster_a + cluster_b)
    db_session.commit()

    count = run_persistence(db_session, current_date=today)
    assert count == 2

    sources = db_session.query(PersistentSource).all()
    assert len(sources) == 2

    ids = {ps.id for ps in sources}
    cluster_ids = {ps.cluster_id for ps in sources}
    assert ids == cluster_ids, "each PersistentSource.cluster_id must equal its own id"

    # All cluster-A members point to one source, all cluster-B members to the other.
    a_ids = {f.cluster_id for f in cluster_a}
    b_ids = {f.cluster_id for f in cluster_b}
    assert len(a_ids) == 1
    assert len(b_ids) == 1
    assert a_ids != b_ids, "the two clusters must not share a cluster_id"
