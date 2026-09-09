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

import datetime
import json
import logging
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import delete  # noqa: E402
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Path setup — make app/ importable when run as a script from backend/
# ---------------------------------------------------------------------------

_BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_DIR))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import FireDetection, FlaggedCase, PersistentSource  # noqa: E402
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

def _load_fires(db: Session, base_date: datetime.date | None = None) -> int:
    """Read fires.csv and upsert each row via firms_client.upsert_detection.

    Detection dates are shifted relative to load time so the most recent
    detection is anchored shortly before 'today' (yesterday by default, or
    base_date - 1 day if base_date is specified). Exact day-spacing between
    detections is preserved so clustering and persistence logic behave
    identically regardless of calendar date.
    """
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

    # Shift dates relative to load time
    if not frame.empty and "acq_date" in frame.columns:
        parsed_dates = pd.to_datetime(frame["acq_date"]).dt.date
        max_acq_date = parsed_dates.max()
        anchor = base_date if base_date is not None else datetime.date.today()
        target_max_date = anchor - datetime.timedelta(days=1)
        shift_days = (target_max_date - max_acq_date).days

        if shift_days != 0:
            frame["acq_date"] = parsed_dates.apply(
                lambda d: d + datetime.timedelta(days=shift_days)
            )
            logger.info(
                "Shifted fire detection dates by %d day(s) "
                "(original max: %s, new max: %s, relative spacing preserved).",
                shift_days,
                max_acq_date,
                target_max_date,
            )
        else:
            frame["acq_date"] = parsed_dates

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

def _clear_previous_seed(db: Session) -> None:
    """Clear previously seeded fire detections and derived analysis state.

    Ensures that re-running seed_demo_data.py across different calendar days
    replaces shifted detections cleanly rather than accumulating duplicates.
    """
    deleted_flags = db.execute(delete(FlaggedCase)).rowcount
    deleted_fires = db.execute(delete(FireDetection)).rowcount
    deleted_sources = db.execute(delete(PersistentSource)).rowcount
    if deleted_fires > 0 or deleted_sources > 0 or deleted_flags > 0:
        logger.info(
            "Cleared previous demo data: %d fire(s), %d persistent source(s), %d flag(s).",
            deleted_fires,
            deleted_sources,
            deleted_flags,
        )
    db.flush()


def main(base_date: datetime.date | None = None) -> None:
    _check_seed_dir()

    # Ensure all tables exist — idempotent, does nothing if already present.
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        _clear_previous_seed(db)
        fire_count = _load_fires(db, base_date=base_date)
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
    import argparse

    parser = argparse.ArgumentParser(
        description="Seed offline demo data with dates relative to load time."
    )
    parser.add_argument(
        "--base-date",
        type=lambda s: datetime.date.fromisoformat(s),
        default=None,
        help="Optional ISO date (YYYY-MM-DD) to anchor detection dates to. Defaults to today.",
    )
    args = parser.parse_args()
    main(base_date=args.base_date)


