"""
Historical data ingestion script for the SIH26162 fire-detection pipeline.

Fetches VIIRS NRT fire/hotspot data for India across historical date windows
(using the FIRMS country/area CSV endpoint with explicit [DATE] parameters).
Spaces requests to respect rate limits, writes raw/processed files, and
upserts into the database.

Run from backend/:
    python scripts/fetch_historical.py --days 30
"""

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Path setup — make app/ importable when run as a script from backend/
# ---------------------------------------------------------------------------

_BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_DIR))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.services.firms_client import (  # noqa: E402
    SOURCES,
    _INTER_REQUEST_DELAY_S,
    _parse_csv,
    fetch_csv,
    upsert_detection,
    write_processed,
    write_raw,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def get_date_windows(end_date: date, days_back: int, max_window: int = 10) -> list[tuple[date, int]]:
    """Generate (start_date, day_range) tuples covering days_back up to end_date."""
    windows = []
    # FIRMS takes start_date and day_range.
    # We step forward from (end_date - days_back)
    start = end_date - timedelta(days=days_back)
    current_start = start
    remaining = days_back
    
    while remaining > 0:
        window_days = min(remaining, max_window)
        windows.append((current_start, window_days))
        current_start += timedelta(days=window_days)
        remaining -= window_days
        
    return windows


def fetch_historical(db, days_back: int) -> int:
    today = datetime.now(timezone.utc).date()
    windows = get_date_windows(today, days_back)
    
    all_frames: list[pd.DataFrame] = []
    total = 0
    request_count = 0
    
    logger.info("Starting historical fetch for %d days back from %s.", days_back, today)
    
    for start_date, day_range in windows:
        date_str = start_date.strftime("%Y-%m-%d")
        logger.info("Fetching window: %s for %d days", date_str, day_range)
        
        for satellite_token, firms_product in SOURCES:
            if request_count > 0:
                time.sleep(_INTER_REQUEST_DELAY_S)
            request_count += 1
            
            # Fetch raw data
            raw_text = fetch_csv(
                satellite_token=satellite_token,
                firms_product=firms_product,
                day_range=day_range,
                date_str=date_str
            )
            
            # Land raw data locally BEFORE parsing or DB insertion (RULES.md §6)
            write_raw(satellite_token, raw_text, label=f"hist_{date_str}")
            
            # Parse and normalise
            frame = _parse_csv(raw_text, satellite_token)
            if not frame.empty:
                all_frames.append(frame)
                logger.info(
                    "Fetched %d detections for %s starting %s", 
                    len(frame), satellite_token, date_str
                )
            else:
                logger.info("No detections for %s starting %s", satellite_token, date_str)

    if not all_frames:
        logger.info("No historical data returned for the specified period.")
        return 0

    # Combine all historical frames
    merged = pd.concat(all_frames, ignore_index=True)
    
    # Land processed data locally BEFORE DB insertion (RULES.md §6)
    write_processed(merged, label=f"hist_{days_back}days")
    
    # Upsert into DB
    for record in merged.to_dict(orient="records"):
        upsert_detection(db, record)
        total += 1
        
    logger.info("Processed %d historical detections total.", total)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch historical FIRMS data.")
    parser.add_argument(
        "--days", 
        type=int, 
        default=30, 
        help="Days of history to fetch (default: 30)"
    )
    args = parser.parse_args()
    
    # Ensure all tables exist — idempotent
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        fetch_historical(db, args.days)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
