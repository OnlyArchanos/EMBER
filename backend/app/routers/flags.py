"""
Router for flagged unexplained persistent heat sources (GET /api/flags, GET /api/flags/{flag_id}).
Read-only for the prototype build — exposes analyst review cases and member detections.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import FireDetection, FlaggedCase
from app.schemas import FlaggedCaseDetailOut, FlaggedCaseOut

router = APIRouter(tags=["flags"])


@router.get("/flags", response_model=List[FlaggedCaseOut])
def get_flags(
    status: Optional[str] = "open",
    db: Session = Depends(get_db),
) -> List[FlaggedCaseOut]:
    """
    Return flagged cases as a bare array, filtered by status (defaults to 'open').
    Includes the linked PersistentSource summary in each item.
    """
    stmt = select(FlaggedCase).options(selectinload(FlaggedCase.persistent_source))
    if status:
        stmt = stmt.where(FlaggedCase.status == status)

    stmt = stmt.order_by(FlaggedCase.anomaly_score.desc(), FlaggedCase.id.desc())
    flags = db.scalars(stmt).all()
    return list(flags)


@router.get("/flags/{flag_id}", response_model=FlaggedCaseDetailOut)
def get_flag(
    flag_id: int,
    db: Session = Depends(get_db),
) -> FlaggedCaseDetailOut:
    """
    Return full detail for a single flagged case including its linked
    PersistentSource and list of member FireDetection records.
    Returns 404 if the flagged case is not found.
    """
    stmt = (
        select(FlaggedCase)
        .options(selectinload(FlaggedCase.persistent_source))
        .where(FlaggedCase.id == flag_id)
    )
    flag = db.scalars(stmt).first()
    if flag is None:
        raise HTTPException(status_code=404, detail="Flagged case not found")

    members = db.scalars(
        select(FireDetection)
        .where(FireDetection.cluster_id == flag.persistent_source.cluster_id)
        .order_by(FireDetection.acq_date.desc(), FireDetection.id.desc())
    ).all()

    return FlaggedCaseDetailOut(
        id=flag.id,
        persistent_source_id=flag.persistent_source_id,
        anomaly_score=flag.anomaly_score,
        nearest_zone_type=flag.nearest_zone_type,  # type: ignore[arg-type]
        nearest_zone_distance_m=flag.nearest_zone_distance_m,
        status=flag.status,  # type: ignore[arg-type]
        case_note=flag.case_note,
        created_at=flag.created_at,
        updated_at=flag.updated_at,
        persistent_source=flag.persistent_source,  # type: ignore[arg-type]
        member_detections=list(members),
    )
