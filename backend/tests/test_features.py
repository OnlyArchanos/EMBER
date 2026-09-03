"""
Tests for app/ml/features.py.

Uses an in-memory SQLite session (same pattern as test_flagging.py) so that
PersistentSource.id is assigned by the DB engine, making ValueError messages
realistic.  All zone GeoDataFrames are built synthetically — no external data.

Coverage:
  - F1/F2: FRP mean and max spot-checks
  - F3:    frp_trend sign, single-date clamp, and daily-aggregation correctness
           (verifies that overpass count does not bias the slope)
  - F4:    day_night_ratio boundary values (all-day, all-night, mixed)
  - F5:    detection_density derived from members argument, not stored ORM fields
  - F6:    confidence_high_frac (all-high, none-high, mixed)
  - F7:    nearest_zone_distance_m (inside zone, far from zone, correct zone type)
  - Edge:  empty members → ValueError; None gdf_zones → sentinel; empty GeoDataFrame
           → sentinel; geographic CRS → ValueError; non-contiguous index → .loc correctness
  - Batch: compute_features_batch column order and nearest_zone_type exclusion
  - NaN:   no NaN propagates into any FEATURE_COLUMNS value for valid input
"""

import datetime
import math

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.ml.features import (
    FEATURE_COLUMNS,
    NO_ZONES_SENTINEL,
    compute_features,
    compute_features_batch,
)
from app.models import FireDetection, PersistentSource


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session() -> Session:
    """In-memory SQLite session for isolated tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _add_ps(
    session: Session,
    *,
    centroid_lat: float = 12.0,
    centroid_lon: float = 77.0,
    days_active: int = 5,
    member_count: int = 10,
) -> PersistentSource:
    """Insert and flush a minimal PersistentSource; returns it with a real id."""
    ps = PersistentSource(
        cluster_id=-2,  # placeholder; overwritten after flush
        centroid_latitude=centroid_lat,
        centroid_longitude=centroid_lon,
        first_seen=datetime.date(2025, 1, 1),
        last_seen=datetime.date(2025, 1, days_active),
        days_active=days_active,
        member_count=member_count,
        zone_type_at_location=None,
        status="active",
    )
    session.add(ps)
    session.flush()
    ps.cluster_id = ps.id
    session.flush()
    return ps


def _make_member(
    *,
    frp: float = 50.0,
    acq_date: datetime.date = datetime.date(2025, 1, 1),
    daynight: str = "d",
    confidence: str = "n",
    lat: float = 12.0,
    lon: float = 77.0,
) -> FireDetection:
    """Unsaved FireDetection; does not need a DB session for feature computation."""
    return FireDetection(
        latitude=lat,
        longitude=lon,
        brightness=300.0,
        frp=frp,
        acq_date=acq_date,
        acq_time="0600",
        daynight=daynight,
        satellite="snpp",
        confidence=confidence,
        fire_type="unclassified",
        cluster_id=1,
        is_persistent=True,
    )


def _metric_zone_gdf(
    *,
    zone_type: str = "industrial",
    geom=None,
    crs: str = "EPSG:7755",
    custom_index: list | None = None,
) -> gpd.GeoDataFrame:
    """
    Build a single-zone GeoDataFrame.  geom should be in EPSG:4326; it will be
    projected to crs unless crs == 'EPSG:4326' (used for the geographic-CRS test).
    custom_index, if given, replaces the default 0-based RangeIndex.
    """
    if geom is None:
        geom = box(76.99, 11.99, 77.01, 12.01)
    gdf = gpd.GeoDataFrame([{"zone_type": zone_type, "geometry": geom}], crs="EPSG:4326")
    if crs != "EPSG:4326":
        gdf = gdf.to_crs(crs)
    if custom_index is not None:
        gdf.index = custom_index
    return gdf


# ---------------------------------------------------------------------------
# F1 / F2 — FRP mean and max
# ---------------------------------------------------------------------------


def test_frp_mean_and_max(db_session: Session):
    ps = _add_ps(db_session)
    members = [
        _make_member(frp=10.0, acq_date=datetime.date(2025, 1, 1)),
        _make_member(frp=20.0, acq_date=datetime.date(2025, 1, 2)),
        _make_member(frp=30.0, acq_date=datetime.date(2025, 1, 3)),
    ]
    result = compute_features(ps, members, _metric_zone_gdf())
    assert result["frp_mean"] == pytest.approx(20.0)
    assert result["frp_max"] == pytest.approx(30.0)


def test_frp_uniform_value_no_variance(db_session: Session):
    """All members with identical FRP — mean == max, no division or NaN."""
    ps = _add_ps(db_session)
    base = datetime.date(2025, 1, 1)
    members = [
        _make_member(frp=42.0, acq_date=base + datetime.timedelta(i))
        for i in range(4)
    ]
    result = compute_features(ps, members, _metric_zone_gdf())
    assert result["frp_mean"] == pytest.approx(42.0)
    assert result["frp_max"] == pytest.approx(42.0)
    assert not math.isnan(result["frp_trend"])


# ---------------------------------------------------------------------------
# F3 — frp_trend (daily aggregation + sign + single-date clamp)
# ---------------------------------------------------------------------------


def test_frp_trend_increasing(db_session: Session):
    """Monotonically increasing daily-mean FRP → positive slope."""
    ps = _add_ps(db_session)
    base = datetime.date(2025, 1, 1)
    members = [
        _make_member(frp=10.0, acq_date=base),
        _make_member(frp=20.0, acq_date=base + datetime.timedelta(1)),
        _make_member(frp=30.0, acq_date=base + datetime.timedelta(2)),
    ]
    result = compute_features(ps, members, _metric_zone_gdf())
    assert result["frp_trend"] > 0.0


def test_frp_trend_decreasing(db_session: Session):
    """Monotonically decreasing daily-mean FRP → negative slope."""
    ps = _add_ps(db_session)
    base = datetime.date(2025, 1, 1)
    members = [
        _make_member(frp=30.0, acq_date=base),
        _make_member(frp=20.0, acq_date=base + datetime.timedelta(1)),
        _make_member(frp=10.0, acq_date=base + datetime.timedelta(2)),
    ]
    result = compute_features(ps, members, _metric_zone_gdf())
    assert result["frp_trend"] < 0.0


def test_frp_trend_single_date_clamped_to_zero(db_session: Session):
    """All members on one date → frp_trend == 0.0 (defensive clamp)."""
    ps = _add_ps(db_session, days_active=3)
    same_day = datetime.date(2025, 1, 1)
    members = [
        _make_member(frp=50.0, acq_date=same_day),
        _make_member(frp=60.0, acq_date=same_day),
        _make_member(frp=70.0, acq_date=same_day),
    ]
    result = compute_features(ps, members, _metric_zone_gdf())
    assert result["frp_trend"] == 0.0


def test_frp_trend_daily_aggregation_not_raw_pairs(db_session: Session):
    """
    Regression for Issue 6 (code review).

    Day 1: frp=10 (one detection).
    Day 2: frp=10 and frp=30 (two detections, daily mean = 20).
    Day 3: frp=10 (one detection).

    Daily means: [10, 20, 10] — up then back down → linear slope ≈ 0.

    Using raw pairs without daily aggregation gives slope = 5.0 (positive)
    because day 2's two observations pull the regression toward day 2.
    The correct implementation must produce ≈ 0, not 5.
    """
    ps = _add_ps(db_session)
    base = datetime.date(2025, 1, 1)
    members = [
        _make_member(frp=10.0, acq_date=base),                          # day 1
        _make_member(frp=10.0, acq_date=base + datetime.timedelta(1)),  # day 2, pass 1
        _make_member(frp=30.0, acq_date=base + datetime.timedelta(1)),  # day 2, pass 2
        _make_member(frp=10.0, acq_date=base + datetime.timedelta(2)),  # day 3
    ]
    result = compute_features(ps, members, _metric_zone_gdf())
    # Daily means [10, 20, 10]: symmetric → slope = 0.
    # Raw-pair polyfit would give slope = 5.0 — this assertion catches a regression
    # back to the un-aggregated implementation.
    assert result["frp_trend"] == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# F4 — day_night_ratio (boundary values)
# ---------------------------------------------------------------------------


def test_day_night_ratio_all_day(db_session: Session):
    ps = _add_ps(db_session)
    base = datetime.date(2025, 1, 1)
    members = [
        _make_member(daynight="d", acq_date=base + datetime.timedelta(i))
        for i in range(4)
    ]
    result = compute_features(ps, members, _metric_zone_gdf())
    assert result["day_night_ratio"] == pytest.approx(1.0)


def test_day_night_ratio_all_night(db_session: Session):
    ps = _add_ps(db_session)
    base = datetime.date(2025, 1, 1)
    members = [
        _make_member(daynight="n", acq_date=base + datetime.timedelta(i))
        for i in range(4)
    ]
    result = compute_features(ps, members, _metric_zone_gdf())
    assert result["day_night_ratio"] == pytest.approx(0.0)


def test_day_night_ratio_mixed(db_session: Session):
    ps = _add_ps(db_session)
    base = datetime.date(2025, 1, 1)
    members = [
        _make_member(daynight="d", acq_date=base),
        _make_member(daynight="d", acq_date=base + datetime.timedelta(1)),
        _make_member(daynight="n", acq_date=base + datetime.timedelta(2)),
        _make_member(daynight="n", acq_date=base + datetime.timedelta(3)),
    ]
    result = compute_features(ps, members, _metric_zone_gdf())
    assert result["day_night_ratio"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# F5 — detection_density (must use members arg, not stored ORM fields)
# ---------------------------------------------------------------------------


def test_detection_density_uses_members_not_stored_fields(db_session: Session):
    """
    Regression for Issue 2 (code review).

    ps.member_count=100 and ps.days_active=10 (stored ORM) → stored ratio = 10.0.
    Actual members: 4 detections over 2 distinct dates → correct density = 2.0.

    If the implementation uses ps.member_count/ps.days_active the test fails.
    """
    ps = _add_ps(db_session, days_active=10, member_count=100)
    base = datetime.date(2025, 1, 1)
    members = [
        _make_member(acq_date=base),
        _make_member(acq_date=base),
        _make_member(acq_date=base + datetime.timedelta(1)),
        _make_member(acq_date=base + datetime.timedelta(1)),
    ]
    result = compute_features(ps, members, _metric_zone_gdf())
    assert result["detection_density"] == pytest.approx(2.0)
    assert result["detection_density"] != pytest.approx(10.0)


def test_detection_density_multiple_per_day(db_session: Session):
    """6 members over 3 dates → density = 2.0."""
    ps = _add_ps(db_session, days_active=3, member_count=6)
    base = datetime.date(2025, 1, 1)
    members = [
        _make_member(acq_date=base),
        _make_member(acq_date=base),
        _make_member(acq_date=base + datetime.timedelta(1)),
        _make_member(acq_date=base + datetime.timedelta(1)),
        _make_member(acq_date=base + datetime.timedelta(2)),
        _make_member(acq_date=base + datetime.timedelta(2)),
    ]
    result = compute_features(ps, members, _metric_zone_gdf())
    assert result["detection_density"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# F6 — confidence_high_frac
# ---------------------------------------------------------------------------


def test_confidence_high_frac_all_high(db_session: Session):
    ps = _add_ps(db_session)
    base = datetime.date(2025, 1, 1)
    members = [
        _make_member(confidence="h", acq_date=base + datetime.timedelta(i))
        for i in range(4)
    ]
    result = compute_features(ps, members, _metric_zone_gdf())
    assert result["confidence_high_frac"] == pytest.approx(1.0)


def test_confidence_high_frac_none_high(db_session: Session):
    ps = _add_ps(db_session)
    base = datetime.date(2025, 1, 1)
    members = [
        _make_member(confidence="l", acq_date=base + datetime.timedelta(i))
        for i in range(4)
    ]
    result = compute_features(ps, members, _metric_zone_gdf())
    assert result["confidence_high_frac"] == pytest.approx(0.0)


def test_confidence_high_frac_mixed(db_session: Session):
    ps = _add_ps(db_session)
    base = datetime.date(2025, 1, 1)
    members = [
        _make_member(confidence="h", acq_date=base),
        _make_member(confidence="n", acq_date=base + datetime.timedelta(1)),
        _make_member(confidence="l", acq_date=base + datetime.timedelta(2)),
        _make_member(confidence="h", acq_date=base + datetime.timedelta(3)),
    ]
    result = compute_features(ps, members, _metric_zone_gdf())
    assert result["confidence_high_frac"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# F7 — nearest_zone_distance_m (inside, outside, zone type, non-contiguous index)
# ---------------------------------------------------------------------------


def test_nearest_zone_distance_centroid_inside_zone(db_session: Session):
    """Centroid inside a zone polygon → distance == 0.0."""
    ps = _add_ps(db_session, centroid_lat=12.0, centroid_lon=77.0)
    base = datetime.date(2025, 1, 1)
    members = [_make_member(acq_date=base + datetime.timedelta(i)) for i in range(4)]
    # A large zone that fully contains the centroid.
    large_zone = box(76.0, 11.0, 78.0, 13.0)
    gdf = _metric_zone_gdf(geom=large_zone)
    result = compute_features(ps, members, gdf)
    assert result["nearest_zone_distance_m"] == pytest.approx(0.0, abs=1.0)


def test_nearest_zone_distance_far_from_zone(db_session: Session):
    """Centroid ~880 km from the zone → distance is well above 100 000 m."""
    # Zone near (12.0, 77.0); centroid at (20.0, 77.0).
    ps = _add_ps(db_session, centroid_lat=20.0, centroid_lon=77.0)
    base = datetime.date(2025, 1, 1)
    members = [
        _make_member(lat=20.0, lon=77.0, acq_date=base + datetime.timedelta(i))
        for i in range(4)
    ]
    gdf = _metric_zone_gdf(geom=box(76.99, 11.99, 77.01, 12.01))
    result = compute_features(ps, members, gdf)
    assert result["nearest_zone_distance_m"] > 100_000


def test_nearest_zone_type_in_output(db_session: Session):
    """nearest_zone_type metadata key is present and matches the zone."""
    ps = _add_ps(db_session)
    base = datetime.date(2025, 1, 1)
    members = [_make_member(acq_date=base + datetime.timedelta(i)) for i in range(4)]
    gdf = _metric_zone_gdf(zone_type="farmland")
    result = compute_features(ps, members, gdf)
    assert result["nearest_zone_type"] == "farmland"


def test_nearest_zone_noncontiguous_index(db_session: Session):
    """
    Regression for Issue 3 (code review): .loc must be used, not .iloc.

    Two zones with index labels [5, 10].  The centroid is close to the zone at
    label 10 ("industrial") and far from the zone at label 5 ("forest").

    With .iloc[min_idx]: min_idx from idxmin() would be label 10, and
    .iloc[10] on a 2-row DataFrame raises IndexError.
    With .loc[min_idx]:  .loc[10] correctly returns the "industrial" row.
    """
    zone_near = box(76.99, 11.99, 77.01, 12.01)  # near centroid (12.0, 77.0)
    zone_far = box(69.0, 30.0, 71.0, 32.0)         # far away (northwestern India)

    gdf = gpd.GeoDataFrame(
        [
            {"zone_type": "forest", "geometry": zone_far},
            {"zone_type": "industrial", "geometry": zone_near},
        ],
        crs="EPSG:4326",
    ).to_crs("EPSG:7755")
    gdf.index = [5, 10]  # non-contiguous; .iloc[10] would raise IndexError

    ps = _add_ps(db_session, centroid_lat=12.0, centroid_lon=77.0)
    base = datetime.date(2025, 1, 1)
    members = [_make_member(acq_date=base + datetime.timedelta(i)) for i in range(4)]

    result = compute_features(ps, members, gdf)
    # Nearest is "industrial" (index 10, inside zone); "forest" is ~2500 km away.
    assert result["nearest_zone_type"] == "industrial"
    assert result["nearest_zone_distance_m"] == pytest.approx(0.0, abs=2_000.0)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_members_raises_value_error(db_session: Session):
    """Empty members list must raise ValueError, not return silently."""
    ps = _add_ps(db_session)
    with pytest.raises(ValueError, match="members list is empty"):
        compute_features(ps, [], _metric_zone_gdf())


def test_none_gdf_zones_returns_sentinel(db_session: Session):
    """None gdf_zones → NO_ZONES_SENTINEL for distance, None for zone type."""
    ps = _add_ps(db_session)
    base = datetime.date(2025, 1, 1)
    members = [_make_member(acq_date=base + datetime.timedelta(i)) for i in range(4)]
    result = compute_features(ps, members, None)
    assert result["nearest_zone_distance_m"] == NO_ZONES_SENTINEL
    assert result["nearest_zone_type"] is None


def test_empty_geodataframe_returns_sentinel(db_session: Session):
    """GeoDataFrame with zero rows → NO_ZONES_SENTINEL (not a ValueError)."""
    ps = _add_ps(db_session)
    base = datetime.date(2025, 1, 1)
    members = [_make_member(acq_date=base + datetime.timedelta(i)) for i in range(4)]
    empty_gdf = gpd.GeoDataFrame({"zone_type": [], "geometry": []}, crs="EPSG:7755")
    result = compute_features(ps, members, empty_gdf)
    assert result["nearest_zone_distance_m"] == NO_ZONES_SENTINEL


def test_geographic_crs_raises_value_error(db_session: Session):
    """
    Regression for Issue 4 (code review): passing a geographic CRS must raise
    ValueError immediately, not silently store degree-valued distances.
    """
    ps = _add_ps(db_session)
    base = datetime.date(2025, 1, 1)
    members = [_make_member(acq_date=base + datetime.timedelta(i)) for i in range(4)]
    # Intentionally NOT calling .to_crs() — stays in geographic EPSG:4326.
    gdf_geographic = _metric_zone_gdf(crs="EPSG:4326")
    with pytest.raises(ValueError, match="projected"):
        compute_features(ps, members, gdf_geographic)


# ---------------------------------------------------------------------------
# Feature column identity and batch function
# ---------------------------------------------------------------------------


def test_all_feature_columns_present(db_session: Session):
    """All FEATURE_COLUMNS keys must appear in the dict returned by compute_features."""
    ps = _add_ps(db_session)
    base = datetime.date(2025, 1, 1)
    members = [_make_member(acq_date=base + datetime.timedelta(i)) for i in range(4)]
    result = compute_features(ps, members, _metric_zone_gdf())
    for col in FEATURE_COLUMNS:
        assert col in result, f"Feature column missing from output: {col}"


def test_compute_features_batch_column_order(db_session: Session):
    """compute_features_batch returns a DataFrame with columns in FEATURE_COLUMNS order."""
    ps = _add_ps(db_session)
    base = datetime.date(2025, 1, 1)
    members = [_make_member(acq_date=base + datetime.timedelta(i)) for i in range(4)]
    df = compute_features_batch([(ps, members)], _metric_zone_gdf())
    assert list(df.columns) == FEATURE_COLUMNS


def test_compute_features_batch_excludes_nearest_zone_type(db_session: Session):
    """nearest_zone_type must not appear in the DataFrame returned by compute_features_batch."""
    ps = _add_ps(db_session)
    base = datetime.date(2025, 1, 1)
    members = [_make_member(acq_date=base + datetime.timedelta(i)) for i in range(4)]
    df = compute_features_batch([(ps, members)], _metric_zone_gdf())
    assert "nearest_zone_type" not in df.columns


# ---------------------------------------------------------------------------
# NaN propagation guard
# ---------------------------------------------------------------------------


def test_no_nan_in_feature_columns(db_session: Session):
    """No NaN value should appear in any FEATURE_COLUMNS field for valid input."""
    ps = _add_ps(db_session)
    base = datetime.date(2025, 1, 1)
    members = [
        _make_member(
            frp=50.0, confidence="h", daynight="d",
            acq_date=base + datetime.timedelta(i),
        )
        for i in range(4)
    ]
    result = compute_features(ps, members, _metric_zone_gdf())
    for col in FEATURE_COLUMNS:
        val = result[col]
        assert isinstance(val, float), f"{col} is not a float: {val!r}"
        assert not math.isnan(val), f"NaN in feature column: {col}"
