"""
Router for fire detections (GET /api/fires, GET /api/fires/{fire_id}).
Provides filtered detection records for the map and detail popup.
"""

import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FireDetection
from app.schemas import FireDetectionOut

router = APIRouter(tags=["fires"])

# Ordinal rank mapping for VIIRS confidence ratings ('l' < 'n' < 'h')
CONFIDENCE_RANKS = {
    "l": 0,
    "n": 1,
    "h": 2,
}


@router.get("/fires", response_model=List[FireDetectionOut])
def get_fires(
    fire_type: Optional[str] = None,
    state: Optional[str] = None,
    date_from: Optional[datetime.date] = None,
    date_to: Optional[datetime.date] = None,
    is_persistent: Optional[str] = None,
    min_confidence: Optional[str] = None,
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> List[FireDetectionOut]:
    """
    Return a bare array of classified FireDetection records.
    Excludes all 'pending' rows under any filter combination.
    """
    # Reject or return empty immediately if pending is requested
    if fire_type is not None and fire_type.strip().lower() == "pending":
        return []

    # If date_from > date_to, return an empty array without error
    if date_from is not None and date_to is not None and date_from > date_to:
        return []

    # Absolute exclusion: pending rows are never returned
    stmt = select(FireDetection).where(FireDetection.fire_type != "pending")

    if fire_type is not None:
        stmt = stmt.where(FireDetection.fire_type == fire_type.strip().lower())

    if state is not None:
        # Exact-match and case-sensitive; NULL state rows are excluded when filtered
        stmt = stmt.where(FireDetection.state == state)

    if date_from is not None:
        stmt = stmt.where(FireDetection.acq_date >= date_from)

    if date_to is not None:
        stmt = stmt.where(FireDetection.acq_date <= date_to)

    if min_confidence is not None:
        normalized_conf = min_confidence.strip().lower()
        if normalized_conf not in CONFIDENCE_RANKS:
            return []
        threshold_rank = CONFIDENCE_RANKS[normalized_conf]
        allowed_confidences = [
            c for c, rank in CONFIDENCE_RANKS.items() if rank >= threshold_rank
        ]
        stmt = stmt.where(FireDetection.confidence.in_(allowed_confidences))

    if is_persistent is not None:
        val = is_persistent.strip().lower()
        if val == "true":
            stmt = stmt.where(FireDetection.is_persistent.is_(True))
        elif val == "false":
            stmt = stmt.where(FireDetection.is_persistent.is_(False))
        else:
            return []

    # Clamp limit to max 2000 as hard cap insurance
    clamped_limit = min(max(1, limit), 2000)
    stmt = stmt.order_by(FireDetection.acq_date.desc(), FireDetection.id.desc()).limit(
        clamped_limit
    )

    fires = db.scalars(stmt).all()
    return list(fires)


@router.get("/fires/{fire_id}", response_model=FireDetectionOut)
def get_fire(
    fire_id: int,
    db: Session = Depends(get_db),
) -> FireDetectionOut:
    """
    Return full detail for a single fire detection.
    Pending rows return 404 — the exclusion is absolute.
    """
    stmt = select(FireDetection).where(
        FireDetection.id == fire_id,
        FireDetection.fire_type != "pending",
    )
    fire = db.scalars(stmt).first()
    if fire is None:
        raise HTTPException(status_code=404, detail="Fire detection not found")
    return fire
