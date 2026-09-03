"""
Shared fixture construction for known-industrial-sites validation.

Both scripts/validate_known_sites.py and app/ml/train.py use this module
to build synthetic FireDetection rows and PersistentSource objects for the
known-industrial-sites fixture.  Having one implementation here ensures
that the two callers always receive identical synthetic data; there is no
separately-maintained detection-construction loop at each call site.

The JSON loader is also centralised here so the fixture path is defined
exactly once.
"""

import datetime
import json
import pathlib

from app.models import FireDetection, PersistentSource

# Fixture JSON path — relative to this file so it works regardless of the
# working directory from which train.py or validate_known_sites.py is invoked.
KNOWN_SITES_PATH: pathlib.Path = (
    pathlib.Path(__file__).parent.parent.parent / "data" / "seed" / "known_industrial_sites.json"
)

# ── Detection constants ───────────────────────────────────────────────────────
# These values represent a canonical high-confidence daytime industrial
# detection signature.  Both callers (validate_known_sites.py and train.py)
# receive objects built from exactly these constants — changing a value here
# automatically propagates to both.  Do not redeclare these at call sites.

FIXTURE_FRP: float = 50.0
FIXTURE_BRIGHTNESS: float = 300.0
FIXTURE_DAYNIGHT: str = "d"
FIXTURE_SATELLITE: str = "snpp"
FIXTURE_CONFIDENCE: str = "h"
FIXTURE_ACQ_TIME: str = "1200"
FIXTURE_DETECTION_COUNT: int = 5  # one detection per day for FIXTURE_DETECTION_COUNT days


def load_known_sites() -> list[dict]:
    """
    Load and return the known-industrial-sites fixture list.

    Raises FileNotFoundError if the JSON file is absent — both callers depend
    on it and neither can proceed without it.
    """
    if not KNOWN_SITES_PATH.exists():
        raise FileNotFoundError(
            f"Known-sites fixture not found at {KNOWN_SITES_PATH}.  "
            "This file must be present in data/seed/ for validation to run."
        )
    with open(KNOWN_SITES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_site_fixture(
    site: dict,
    base_date: datetime.date,
    *,
    site_id: int = 1,
) -> tuple[PersistentSource, list[FireDetection]]:
    """
    Build unsaved PersistentSource and FireDetection objects for one known site.

    Returns a (ps, members) pair.  Neither object is attached to a database
    session — callers may add them to a session or pass them directly to
    compute_features(), whichever is appropriate.

    Detection rows span FIXTURE_DETECTION_COUNT consecutive days starting at
    base_date.  Callers control base_date to satisfy their context:
    - validate_known_sites.py passes today so the cluster reads as active
      (last_seen < today - ENDED_THRESHOLD_DAYS would mark it ended).
    - train.py's ML hook passes a fixed historical date for reproducibility.

    Args:
        site:      Dict from known_industrial_sites.json.  Required keys:
                   "lat" (float), "lon" (float), "zone_type" (str).
        base_date: First acquisition date for the synthetic detections.
        site_id:   Temporary cluster/id value for the unsaved PS.  Caller
                   should supply a unique value per site when iterating a list
                   (e.g. enumerate index + 1) so error messages are readable.
    """
    lat: float = site["lat"]
    lon: float = site["lon"]

    ps = PersistentSource(
        cluster_id=site_id,
        centroid_latitude=lat,
        centroid_longitude=lon,
        first_seen=base_date,
        last_seen=base_date + datetime.timedelta(days=FIXTURE_DETECTION_COUNT - 1),
        days_active=FIXTURE_DETECTION_COUNT,
        member_count=FIXTURE_DETECTION_COUNT,
        zone_type_at_location=site.get("zone_type", "industrial"),
        status="active",
    )
    # Temporary negative id so features.py error messages include a readable
    # id without requiring a DB flush.
    ps.id = -site_id

    members = [
        FireDetection(
            latitude=lat,
            longitude=lon,
            brightness=FIXTURE_BRIGHTNESS,
            frp=FIXTURE_FRP,
            acq_date=base_date + datetime.timedelta(days=i),
            acq_time=FIXTURE_ACQ_TIME,
            daynight=FIXTURE_DAYNIGHT,
            satellite=FIXTURE_SATELLITE,
            confidence=FIXTURE_CONFIDENCE,
            # "pending" is the correct initial fire_type: validate_known_sites.py
            # runs classify_fires() which sets it to "industrial".  train.py's
            # hook passes these objects directly to compute_features(), which
            # does not read fire_type, so "pending" is harmless there too.
            fire_type="pending",
            cluster_id=None,    # not yet assigned by persistence.py
            is_persistent=False,
        )
        for i in range(FIXTURE_DETECTION_COUNT)
    ]

    return ps, members
