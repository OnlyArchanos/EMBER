"""
NASA FIRMS ingestion client for the EMBER fire-detection pipeline.

Fetches VIIRS NRT fire/hotspot data for India from all three current satellite
sources (Suomi NPP, NOAA-20, NOAA-21), normalises the merged CSV into
FireDetection-compatible records, lands raw and processed files before any DB
write (RULES.md §6), and performs dedup-aware inserts (data-model.md §FireDetection).

Public API consumed by other modules:
  - normalise_firms_frame()  — shared normalisation (also used by seed_demo_data.py)
  - upsert_detection()       — dedup-aware insert/update (also used by seed_demo_data.py,
                                fetch_historical.py)
  - fetch_csv()              — HTTP fetch with retry/backoff (also used by
                                fetch_historical.py)
  - SOURCES / RAW_DIR / PROCESSED_DIR — constants reused by fetch_historical.py

Nothing here touches fire_type — classification is Phase 3.
"""

import io
import logging
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.models import FireDetection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FIRMS endpoint configuration
# ---------------------------------------------------------------------------

# Canonical satellite token -> FIRMS product name used in the URL.
# Satellite is determined by which endpoint we queried, never parsed from CSV.
SOURCES: list[tuple[str, str]] = [
    ("snpp",   "VIIRS_SNPP_NRT"),
    ("noaa20", "VIIRS_NOAA20_NRT"),
    ("noaa21", "VIIRS_NOAA21_NRT"),
]

FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov/api/country/csv"
FIRMS_AREA_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

# FIRMS real-time country/area API caps day_range at 10.
# We use 1 (yesterday + today window) for scheduled NRT pulls; the scheduler
# drives how often this runs (FETCH_INTERVAL_HOURS), not this module.
_DAY_RANGE = 1

# Paths for mandatory file landing before any DB write (RULES.md §6).
RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw"
PROCESSED_DIR = Path(__file__).resolve().parents[3] / "data" / "processed"

# Retry / backoff settings — shared with fetch_historical.py via fetch_csv().
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE_S = 5

# Pacing delay between successive satellite requests to be a good API citizen.
_INTER_REQUEST_DELAY_S = 1.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_and_ingest(
    db: Session,
    day_range: int = _DAY_RANGE,
    bbox: tuple[float, float, float, float] | dict[str, float] | None = None,
) -> int:
    """Fetch VIIRS NRT data from all three sources, normalise, land
    files, and upsert into the database.

    Returns the total number of rows processed (inserted + updated).
    Raises on any unrecoverable fetch failure -- never fails silently.

    Args:
        db:        SQLAlchemy session; caller is responsible for commit/rollback.
        day_range: Number of days to request from FIRMS (1-10). Default 1.
        bbox:      Optional (west, south, east, north) tuple or dict to scope
                   the fetch to a bounding box. When omitted, defaults to all of India.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    all_frames: list[pd.DataFrame] = []
    label = "bbox" if bbox else ""

    for i, (satellite_token, firms_product) in enumerate(SOURCES):
        if i > 0:
            time.sleep(_INTER_REQUEST_DELAY_S)

        raw_text = fetch_csv(
            satellite_token, firms_product, day_range, bbox=bbox
        )
        write_raw(satellite_token, raw_text, label=label)

        frame = _parse_csv(raw_text, satellite_token)
        if frame.empty:
            logger.info("No detections returned for %s.", satellite_token)
        else:
            logger.info(
                "Fetched %d detections for %s.", len(frame), satellite_token
            )
        all_frames.append(frame)

    if not any(not f.empty for f in all_frames):
        logger.info("All three sources returned zero detections.")
        return 0

    merged = pd.concat(all_frames, ignore_index=True)
    write_processed(merged, label=label)

    total = 0
    for record in merged.to_dict(orient="records"):
        upsert_detection(db, record)
        total += 1

    logger.info("Processed %d detections total across all three sources.", total)
    return total


def upsert_detection(db: Session, record: dict) -> FireDetection:
    """Insert a new FireDetection or update an existing one on a natural-key match.

    Natural key: (round(latitude, 4), round(longitude, 4), acq_date, acq_time, satellite).
    On a match, updates confidence/brightness/frp on the existing row.
    On no match, inserts a new row.  fire_type is never set here; the DB
    default ('pending') applies to all new rows.

    Args:
        db:     SQLAlchemy session; caller commits.
        record: Dict whose keys match FireDetection's fields exactly.

    Returns:
        The inserted or updated FireDetection ORM object (not yet committed).
    """
    rounded_lat = round(float(record["latitude"]), 4)
    rounded_lon = round(float(record["longitude"]), 4)

    existing = (
        db.query(FireDetection)
        .filter(
            FireDetection.latitude == rounded_lat,
            FireDetection.longitude == rounded_lon,
            FireDetection.acq_date == record["acq_date"],
            FireDetection.acq_time == record["acq_time"],
            FireDetection.satellite == record["satellite"],
        )
        .first()
    )

    if existing is not None:
        existing.confidence = record["confidence"]
        existing.brightness = record["brightness"]
        existing.frp = record["frp"]
        logger.debug(
            "Updated existing detection id=%d (lat=%.4f lon=%.4f %s %s %s).",
            existing.id,
            rounded_lat,
            rounded_lon,
            record["acq_date"],
            record["acq_time"],
            record["satellite"],
        )
        return existing

    detection = FireDetection(
        latitude=rounded_lat,
        longitude=rounded_lon,
        brightness=float(record["brightness"]),
        frp=float(record["frp"]),
        acq_date=record["acq_date"],
        acq_time=record["acq_time"],
        daynight=record["daynight"],
        satellite=record["satellite"],
        confidence=record["confidence"],
        # fire_type deliberately omitted -- DB default 'pending' applies.
        # state/district/cluster_id/is_persistent use their own DB defaults.
    )
    db.add(detection)
    return detection


# ---------------------------------------------------------------------------
# Normalisation (public — shared with seed_demo_data.py)
# ---------------------------------------------------------------------------

# Column subset that constitutes a normalised FIRMS frame.
_OUTPUT_COLS = [
    "latitude", "longitude", "brightness", "frp",
    "acq_date", "acq_time", "daynight", "satellite", "confidence",
]


def normalise_firms_frame(
    frame: pd.DataFrame, satellite_token: str | None = None
) -> pd.DataFrame:
    """Apply the canonical normalisation transforms to a FIRMS-like DataFrame.

    This is the single source of truth for rounding, type coercion, column
    renaming, and casing conventions.  Used by _parse_csv (live/historical
    path, where satellite_token is always set from the queried endpoint) and
    by seed_demo_data.py (offline path, where satellite is already a column
    in the seed CSV and satellite_token is None).

    Args:
        frame:           DataFrame with at least the _OUTPUT_COLS columns
                         (plus possibly 'bright_ti4' as an alias for
                         'brightness').
        satellite_token: If provided, overrides the 'satellite' column with
                         this value (set from which endpoint was queried,
                         per data-model.md).  If None, the existing
                         'satellite' column is kept as-is.

    Returns:
        A new DataFrame containing only _OUTPUT_COLS, normalised.
    """
    frame = frame.copy()

    # Round coordinates per the dedup contract.
    frame["latitude"] = frame["latitude"].astype(float).round(4)
    frame["longitude"] = frame["longitude"].astype(float).round(4)

    # acq_date: FIRMS reports YYYY-MM-DD; parse to datetime.date.
    frame["acq_date"] = pd.to_datetime(frame["acq_date"], format="%Y-%m-%d").dt.date

    # acq_time: FIRMS reports as an integer (e.g. 145 -> "0145", 1230 -> "1230").
    # Normalise to exactly 4 chars, zero-padded.
    frame["acq_time"] = frame["acq_time"].astype(str).str.zfill(4)

    # daynight: FIRMS reports 'D' or 'N'; contract specifies lowercase 'd'|'n'.
    frame["daynight"] = frame["daynight"].astype(str).str.lower()

    # satellite: set from the queried source when a token is provided,
    # otherwise keep the existing column (seed CSV path).
    if satellite_token is not None:
        frame["satellite"] = satellite_token

    # confidence: FIRMS VIIRS NRT uses 'l', 'n', 'h' (low/nominal/high).
    frame["confidence"] = frame["confidence"].astype(str).str.lower()

    # brightness: FIRMS calls this 'bright_ti4' (primary channel) in VIIRS NRT.
    # Fall back to 'brightness' if the column name differs.
    if "bright_ti4" in frame.columns:
        frame["brightness"] = frame["bright_ti4"].astype(float)
    elif "brightness" in frame.columns:
        frame["brightness"] = frame["brightness"].astype(float)
    else:
        logger.warning(
            "No brightness column found; defaulting to 0.0."
        )
        frame["brightness"] = 0.0

    frame["frp"] = frame["frp"].astype(float)

    return frame[_OUTPUT_COLS]


# ---------------------------------------------------------------------------
# HTTP fetch with retry/backoff (public — shared with fetch_historical.py)
# ---------------------------------------------------------------------------

def fetch_csv(
    satellite_token: str,
    firms_product: str,
    day_range: int,
    date_str: str | None = None,
    bbox: tuple[float, float, float, float] | dict[str, float] | None = None,
) -> str:
    """Fetch raw CSV text from the FIRMS country/area API with retry + backoff.

    Retries up to _MAX_RETRIES times with exponential back-off on HTTP 429,
    503, and request timeouts.

    Args:
        satellite_token: Canonical satellite name (for logging).
        firms_product:   FIRMS product string for the URL.
        day_range:       Number of days to request (1-10).
        date_str:        Optional YYYY-MM-DD start date for historical pulls.
                         Omit for NRT (most-recent) data.
        bbox:            Optional (west, south, east, north) tuple or dict to scope
                         the fetch to a bounding box. When omitted, defaults to all of India.

    Raises:
        requests.RequestException: after all retries are exhausted.
    """
    if bbox is not None:
        if isinstance(bbox, dict):
            w, s, e, n = bbox["west"], bbox["south"], bbox["east"], bbox["north"]
        else:
            w, s, e, n = bbox
        url = f"{FIRMS_AREA_BASE}/{settings.NASA_FIRMS_MAP_KEY}/{firms_product}/{w},{s},{e},{n}/{day_range}"
    else:
        url = f"{FIRMS_BASE}/{settings.NASA_FIRMS_MAP_KEY}/{firms_product}/IND/{day_range}"

    if date_str is not None:
        url = f"{url}/{date_str}"

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info(
                "FIRMS request attempt %d/%d: %s (satellite=%s)",
                attempt, _MAX_RETRIES, url, satellite_token,
            )
            response = requests.get(url, timeout=60)
        except requests.Timeout:
            logger.warning(
                "FIRMS timeout on attempt %d/%d for %s.",
                attempt, _MAX_RETRIES, satellite_token,
            )
            _backoff(attempt)
            continue
        except requests.RequestException as exc:
            logger.error("FIRMS network error for %s: %s", satellite_token, exc)
            _backoff(attempt)
            continue

        if response.status_code in (429, 503):
            logger.warning(
                "FIRMS returned HTTP %s for %s, attempt %d/%d.",
                response.status_code, satellite_token, attempt, _MAX_RETRIES,
            )
            _backoff(attempt)
            continue

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            logger.error(
                "FIRMS fetch failed for %s: HTTP %s -- %s",
                satellite_token, response.status_code, response.text[:200],
            )
            raise

        return response.text

    raise requests.RequestException(
        f"FIRMS request for '{satellite_token}' failed after {_MAX_RETRIES} attempts."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _backoff(attempt: int) -> None:
    """Sleep for an exponentially increasing duration between retry attempts."""
    delay = _RETRY_BACKOFF_BASE_S * (2 ** (attempt - 1))
    logger.info("Backing off for %ds before next FIRMS attempt.", delay)
    time.sleep(delay)


def _parse_csv(raw_text: str, satellite_token: str) -> pd.DataFrame:
    """Parse FIRMS CSV text into a normalised DataFrame matching FireDetection fields.

    satellite is set from satellite_token (the source queried), not from the
    CSV's own satellite column, which is ambiguous across VIIRS products.

    Returns an empty DataFrame if the response has no data rows.
    """
    try:
        frame = pd.read_csv(io.StringIO(raw_text))
    except Exception as exc:
        logger.error(
            "Failed to parse CSV for %s: %s. Raw text (first 200 chars): %s",
            satellite_token, exc, raw_text[:200],
        )
        raise

    if frame.empty or "latitude" not in frame.columns:
        return pd.DataFrame()

    return normalise_firms_frame(frame, satellite_token=satellite_token)


def write_raw(satellite_token: str, raw_text: str, label: str = "") -> None:
    """Write the untouched API response to data/raw/ (RULES.md §6)."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = f"_{label}" if label else ""
    filename = RAW_DIR / f"firms_{satellite_token}{suffix}_{timestamp}.csv"
    filename.write_text(raw_text, encoding="utf-8")
    logger.debug("Raw response written to %s", filename)


def write_processed(merged: pd.DataFrame, label: str = "") -> None:
    """Write the normalised, merged DataFrame to data/processed/ (RULES.md §6)."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = f"_{label}" if label else ""
    filename = PROCESSED_DIR / f"firms_merged{suffix}_{timestamp}.csv"
    merged.to_csv(filename, index=False)
    logger.debug("Processed data written to %s", filename)
