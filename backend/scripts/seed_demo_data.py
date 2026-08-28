"""
Offline demo seeder for the SIH26162 fire-detection pipeline.

Loads fire detection and zone records from backend/data/seed/ into the local
SQLite database — zero network access.  Reuses firms_client.upsert_detection
and osm_client.upsert_zone as the single insert path (RULES.md §1 rule 3).

Expected seed files:
  data/seed/fires.csv       -- FIRMS-normalised CSV: same column names that
                               firms_client._parse_csv() produces.
  data/seed/zones.geojson   -- GeoJSON FeatureCollection: same Feature structure
                               that osm_client._parse_overpass_to_features()
                               produces, with properties.zone_type set on each
                               feature.

Run from backend/:
    python scripts/seed_demo_data.py

Safe to run repeatedly — upsert semantics prevent duplicate rows.
"""

import json
import logging
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Path setup — make app/ importable when run as a script from backend/
# ---------------------------------------------------------------------------

_BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_DIR))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.services.firms_client import normalise_firms_frame, upsert_detection  # noqa: E402
from app.services.osm_client import upsert_zone  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_SEED_DIR = _BACKEND_DIR / "data" / "seed"
_FIRES_CSV = _SEED_DIR / "fires.csv"
_ZONES_GEOJSON = _SEED_DIR / "zones.geojson"


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def _check_seed_dir() -> None:
    """Fail fast with an actionable message if seed data is missing."""
    if not _SEED_DIR.exists():
        sys.exit(
            f"ERROR: Seed directory not found: {_SEED_DIR}\n"
            "Create it and add fires.csv and zones.geojson before seeding."
        )

    has_fires = _FIRES_CSV.exists()
    has_zones = _ZONES_GEOJSON.exists()

    if not has_fires and not has_zones:
        sys.exit(
            f"ERROR: {_SEED_DIR} exists but contains neither fires.csv nor "
            "zones.geojson.\n"
            "Add at least one of these files before running the seeder."
        )

    missing = []
    if not has_fires:
        missing.append(f"  fires.csv     (expected at {_FIRES_CSV})")
    if not has_zones:
        missing.append(f"  zones.geojson (expected at {_ZONES_GEOJSON})")
    if missing:
        logger.warning(
            "Some seed files are absent — only the present ones will be loaded:\n%s",
            "\n".join(missing),
        )


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _load_fires(db: Session) -> int:
    """Read fires.csv and upsert each row via firms_client.upsert_detection."""
    if not _FIRES_CSV.exists():
        logger.info("fires.csv not present — skipping fire detections.")
        return 0

    try:
        frame = pd.read_csv(_FIRES_CSV)
    except Exception as exc:
        sys.exit(f"ERROR: Could not read {_FIRES_CSV}: {exc}")

    required = {
        "latitude", "longitude", "brightness", "frp",
        "acq_date", "acq_time", "daynight", "satellite", "confidence",
    }
    missing_cols = required - set(frame.columns)
    if missing_cols:
        sys.exit(
            f"ERROR: fires.csv is missing required columns: {sorted(missing_cols)}\n"
            "Expected columns match what firms_client.normalise_firms_frame() produces."
        )

    # Normalise using the single shared function.  satellite_token is None
    # because the seed CSV already has a 'satellite' column with canonical values.
    frame = normalise_firms_frame(frame)

    count = 0
    for record in frame.to_dict(orient="records"):
        upsert_detection(db, record)
        count += 1

    logger.info("Processed %d fire detection row(s) from fires.csv.", count)
    return count


def _load_zones(db: Session) -> int:
    """Read zones.geojson and upsert each feature via osm_client.upsert_zone."""
    if not _ZONES_GEOJSON.exists():
        logger.info("zones.geojson not present — skipping zone records.")
        return 0

    try:
        raw = _ZONES_GEOJSON.read_text(encoding="utf-8-sig")
        geojson = json.loads(raw)
    except Exception as exc:
        sys.exit(f"ERROR: Could not read or parse {_ZONES_GEOJSON}: {exc}")

    if geojson.get("type") != "FeatureCollection":
        sys.exit(
            f"ERROR: {_ZONES_GEOJSON} must be a GeoJSON FeatureCollection "
            f"(got type={geojson.get('type')!r})."
        )

    features = geojson.get("features", [])
    if not features:
        sys.exit(
            f"ERROR: {_ZONES_GEOJSON} contains no features.\n"
            "Add at least one zone polygon before running the seeder."
        )

    valid_zone_types = {"industrial", "forest", "farmland"}
    count = 0
    skipped = 0
    for feat in features:
        zone_type = (feat.get("properties") or {}).get("zone_type")
        if zone_type not in valid_zone_types:
            logger.warning(
                "Skipping feature with invalid/missing zone_type=%r "
                "(must be one of %s).",
                zone_type,
                sorted(valid_zone_types),
            )
            skipped += 1
            continue
        upsert_zone(db, feat, zone_type)
        count += 1

    if skipped:
        logger.warning("Skipped %d zone feature(s) with invalid zone_type.", skipped)
    logger.info("Processed %d zone feature(s) from zones.geojson.", count)
    return count


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    _check_seed_dir()

    # Ensure all tables exist — idempotent, does nothing if already present.
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        fire_count = _load_fires(db)
        zone_count = _load_zones(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    logger.info(
        "Seed complete — %d fire detection(s), %d zone(s) loaded.",
        fire_count,
        zone_count,
    )


if __name__ == "__main__":
    main()

