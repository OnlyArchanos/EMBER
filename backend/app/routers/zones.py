"""
Router for OpenStreetMap zone overlay polygons (GET /api/zones).
Provides cached polygon geometries for map overlay and spatial filtering.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Zone
from app.schemas import ZoneOut

router = APIRouter(tags=["zones"])


@router.get("/zones", response_model=List[ZoneOut])
def get_zones(
    zone_type: Optional[str] = None,
    db: Session = Depends(get_db),
) -> List[ZoneOut]:
    """Return cached zone polygons as a bare array, optionally filtered by zone_type."""
    stmt = select(Zone)
    if zone_type is not None:
        stmt = stmt.where(Zone.zone_type == zone_type)
    zones = db.scalars(stmt).all()
    return list(zones)
