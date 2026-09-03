"""
Tests for app/ml/known_sites_fixture.py.

Confirms that build_site_fixture() is deterministic and that its field values
exactly match the module-level constants.  This pins the behaviour that both
callers (validate_known_sites.py and train.py) rely on: a change to any
constant is caught here, and a regression that makes the function's output
inconsistent with its constants is also caught.

No database session is required — build_site_fixture() returns unsaved objects.
"""

import datetime

import pytest

from app.ml.known_sites_fixture import (
    FIXTURE_ACQ_TIME,
    FIXTURE_BRIGHTNESS,
    FIXTURE_CONFIDENCE,
    FIXTURE_DAYNIGHT,
    FIXTURE_DETECTION_COUNT,
    FIXTURE_FRP,
    FIXTURE_SATELLITE,
    build_site_fixture,
    load_known_sites,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

_SITE_A = {
    "name": "Test Site A",
    "lat": 22.348,
    "lon": 69.868,
    "geometry": "POLYGON ((69.8 22.3, 70.0 22.3, 70.0 22.4, 69.8 22.4, 69.8 22.3))",
    "zone_type": "industrial",
}

_SITE_B = {
    "name": "Test Site B",
    "lat": 12.0,
    "lon": 77.0,
    "geometry": "POLYGON ((76.9 11.9, 77.1 11.9, 77.1 12.1, 76.9 12.1, 76.9 11.9))",
    "zone_type": "industrial",
}

_BASE = datetime.date(2025, 3, 1)


# ── Determinism: same inputs → identical field values ─────────────────────────


def test_build_site_fixture_is_deterministic():
    """
    Calling build_site_fixture twice with the same arguments must produce
    field-for-field identical output.  This is the core guarantee that both
    callers (validate_known_sites.py and train.py) see the same fixture data.
    """
    ps1, members1 = build_site_fixture(_SITE_A, _BASE, site_id=1)
    ps2, members2 = build_site_fixture(_SITE_A, _BASE, site_id=1)

    # PersistentSource fields
    assert ps1.centroid_latitude == ps2.centroid_latitude
    assert ps1.centroid_longitude == ps2.centroid_longitude
    assert ps1.days_active == ps2.days_active
    assert ps1.member_count == ps2.member_count
    assert ps1.first_seen == ps2.first_seen
    assert ps1.last_seen == ps2.last_seen
    assert ps1.zone_type_at_location == ps2.zone_type_at_location
    assert ps1.status == ps2.status
    assert ps1.id == ps2.id

    # FireDetection fields — every member
    assert len(members1) == len(members2)
    for m1, m2 in zip(members1, members2):
        assert m1.frp == m2.frp
        assert m1.brightness == m2.brightness
        assert m1.daynight == m2.daynight
        assert m1.satellite == m2.satellite
        assert m1.confidence == m2.confidence
        assert m1.acq_date == m2.acq_date
        assert m1.acq_time == m2.acq_time
        assert m1.latitude == m2.latitude
        assert m1.longitude == m2.longitude
        assert m1.fire_type == m2.fire_type
        assert m1.is_persistent == m2.is_persistent
        assert m1.cluster_id == m2.cluster_id


# ── Field values match module constants ────────────────────────────────────────


def test_ps_centroid_is_site_lat_lon():
    """PersistentSource centroid must come from the site dict, not a placeholder."""
    ps, _ = build_site_fixture(_SITE_A, _BASE)
    assert ps.centroid_latitude == _SITE_A["lat"]
    assert ps.centroid_longitude == _SITE_A["lon"]


def test_ps_centroid_differs_between_sites():
    """A different site dict must produce different centroid coordinates."""
    ps_a, _ = build_site_fixture(_SITE_A, _BASE)
    ps_b, _ = build_site_fixture(_SITE_B, _BASE)
    assert ps_a.centroid_latitude != ps_b.centroid_latitude
    assert ps_a.centroid_longitude != ps_b.centroid_longitude


def test_detection_count_matches_constant():
    _, members = build_site_fixture(_SITE_A, _BASE)
    assert len(members) == FIXTURE_DETECTION_COUNT


def test_ps_days_active_matches_constant():
    ps, _ = build_site_fixture(_SITE_A, _BASE)
    assert ps.days_active == FIXTURE_DETECTION_COUNT
    assert ps.member_count == FIXTURE_DETECTION_COUNT


def test_detection_dates_span_from_base_date():
    """Dates must run from base_date to base_date + FIXTURE_DETECTION_COUNT - 1."""
    _, members = build_site_fixture(_SITE_A, _BASE)
    expected_dates = [
        _BASE + datetime.timedelta(days=i) for i in range(FIXTURE_DETECTION_COUNT)
    ]
    actual_dates = [m.acq_date for m in members]
    assert actual_dates == expected_dates


def test_ps_first_last_seen_match_detection_span():
    """PS first_seen and last_seen must bracket the detection date range."""
    ps, members = build_site_fixture(_SITE_A, _BASE)
    assert ps.first_seen == members[0].acq_date
    assert ps.last_seen == members[-1].acq_date


def test_member_frp_matches_constant():
    _, members = build_site_fixture(_SITE_A, _BASE)
    for m in members:
        assert m.frp == FIXTURE_FRP


def test_member_brightness_matches_constant():
    _, members = build_site_fixture(_SITE_A, _BASE)
    for m in members:
        assert m.brightness == FIXTURE_BRIGHTNESS


def test_member_daynight_matches_constant():
    _, members = build_site_fixture(_SITE_A, _BASE)
    for m in members:
        assert m.daynight == FIXTURE_DAYNIGHT


def test_member_satellite_matches_constant():
    _, members = build_site_fixture(_SITE_A, _BASE)
    for m in members:
        assert m.satellite == FIXTURE_SATELLITE


def test_member_confidence_matches_constant():
    _, members = build_site_fixture(_SITE_A, _BASE)
    for m in members:
        assert m.confidence == FIXTURE_CONFIDENCE


def test_member_acq_time_matches_constant():
    _, members = build_site_fixture(_SITE_A, _BASE)
    for m in members:
        assert m.acq_time == FIXTURE_ACQ_TIME


def test_member_lat_lon_matches_site():
    """Every detection's lat/lon must come from the site dict."""
    _, members = build_site_fixture(_SITE_A, _BASE)
    for m in members:
        assert m.latitude == _SITE_A["lat"]
        assert m.longitude == _SITE_A["lon"]


def test_member_fire_type_is_pending():
    """
    fire_type must be 'pending' so that validate_known_sites.py's classify_fires()
    run actually classifies the detections (classifier skips non-pending rows).
    train.py's hook passes these to compute_features() which ignores fire_type.
    """
    _, members = build_site_fixture(_SITE_A, _BASE)
    for m in members:
        assert m.fire_type == "pending"


def test_member_cluster_id_is_none():
    """
    cluster_id must be None on construction — not yet assigned by persistence.py.
    """
    _, members = build_site_fixture(_SITE_A, _BASE)
    for m in members:
        assert m.cluster_id is None


def test_ps_zone_type_from_site_dict():
    ps, _ = build_site_fixture(_SITE_A, _BASE)
    assert ps.zone_type_at_location == _SITE_A["zone_type"]


def test_ps_id_is_negative_site_id():
    """Temporary id must be negative so it cannot collide with real DB rows."""
    ps, _ = build_site_fixture(_SITE_A, _BASE, site_id=3)
    assert ps.id == -3


def test_site_id_changes_ps_id_and_cluster_id():
    """Different site_id values must produce different ps.id values."""
    ps1, _ = build_site_fixture(_SITE_A, _BASE, site_id=1)
    ps2, _ = build_site_fixture(_SITE_A, _BASE, site_id=2)
    assert ps1.id != ps2.id
    assert ps1.cluster_id != ps2.cluster_id


# ── load_known_sites: smoke test that the real fixture file is loadable ────────


def test_load_known_sites_returns_nonempty_list():
    """
    Confirms the JSON fixture file exists, is valid JSON, and contains at least
    one site with the required keys.
    """
    sites = load_known_sites()
    assert isinstance(sites, list)
    assert len(sites) > 0
    for site in sites:
        assert "lat" in site
        assert "lon" in site
        assert "zone_type" in site
        assert "geometry" in site
