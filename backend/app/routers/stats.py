"""
Router for aggregate dashboard statistics (GET /api/stats).
Provides summarized counts for the sidebar display.
"""

import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FireDetection, FlaggedCase, PersistentSource
from app.schemas import StatsOut

router = APIRouter(tags=["stats"])


@router.get("/stats", response_model=StatsOut)
def get_stats(
    fire_type: Optional[str] = None,
    state: Optional[str] = None,
    date_from: Optional[datetime.date] = None,
    date_to: Optional[datetime.date] = None,
    db: Session = Depends(get_db),
) -> StatsOut:
    """
    Return aggregate statistics matching sidebar summary requirements.
    Excludes 'pending' rows from total_fires, by_type, and by_state.
    Returns all zeros if the database is genuinely empty.
    """
    # Prototype decision: persistent and flag metrics are intentional global lifetime counts,
    # unaffected by date_from/date_to/fire_type/state filters, reflecting current operational state.
    persistent_active_count = (
        db.scalar(
            select(func.count(PersistentSource.id)).where(
                PersistentSource.status == "active"
            )
        )
        or 0
    )
    persistent_ended_count = (
        db.scalar(
            select(func.count(PersistentSource.id)).where(
                PersistentSource.status == "ended"
            )
        )
        or 0
    )
    flagged_open_count = (
        db.scalar(
            select(func.count(FlaggedCase.id)).where(FlaggedCase.status == "open")
        )
        or 0
    )

    # If pending is queried or date_from > date_to, fire aggregates are zero
    if (fire_type is not None and fire_type.strip().lower() == "pending") or (
        date_from is not None and date_to is not None and date_from > date_to
    ):
        return StatsOut(
            total_fires=0,
            by_type={},
            by_state={},
            persistent_active_count=persistent_active_count,
            persistent_ended_count=persistent_ended_count,
            flagged_open_count=flagged_open_count,
        )

    # Base fire filters: strictly exclude pending
    fire_filters = [FireDetection.fire_type != "pending"]

    if fire_type is not None:
        fire_filters.append(FireDetection.fire_type == fire_type.strip().lower())

    if state is not None:
        fire_filters.append(FireDetection.state == state)

    if date_from is not None:
        fire_filters.append(FireDetection.acq_date >= date_from)

    if date_to is not None:
        fire_filters.append(FireDetection.acq_date <= date_to)

    # Total fires matching filters
    total_fires = (
        db.scalar(select(func.count(FireDetection.id)).where(*fire_filters)) or 0
    )

    # Counts by fire_type
    type_rows = db.execute(
        select(FireDetection.fire_type, func.count(FireDetection.id))
        .where(*fire_filters)
        .group_by(FireDetection.fire_type)
    ).all()
    by_type = {row[0]: row[1] for row in type_rows}

    # Counts by state (excluding rows where state is NULL)
    state_rows = db.execute(
        select(FireDetection.state, func.count(FireDetection.id))
        .where(*fire_filters, FireDetection.state.is_not(None))
        .group_by(FireDetection.state)
    ).all()
    by_state = {row[0]: row[1] for row in state_rows}

    return StatsOut(
        total_fires=total_fires,
        by_type=by_type,
        by_state=by_state,
        persistent_active_count=persistent_active_count,
        persistent_ended_count=persistent_ended_count,
        flagged_open_count=flagged_open_count,
    )
