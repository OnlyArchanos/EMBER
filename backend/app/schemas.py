"""
Pydantic request/response schemas for the SIH26162 fire-detection API.

Every field name matches docs/api-contract.md and docs/data-model.md exactly —
these are frozen contracts; do not rename fields here without first updating
those documents and obtaining explicit human sign-off (RULES.md §1, rule 2).

Enums are defined once here and reused by every schema that references the
same allowed values.  Database models (models.py) and API schemas are allowed
to diverge in principle (RULES.md §7.1 rationale), but the field sets are
currently identical — divergence is not needed yet and is not introduced.
"""

import datetime
from enum import Enum
from typing import Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict

from app.config import DataMode


# ---------------------------------------------------------------------------
# Enums — defined once, reused below
# ---------------------------------------------------------------------------


class FireType(str, Enum):
    pending = "pending"
    industrial = "industrial"
    wildfire = "wildfire"
    agricultural = "agricultural"
    unclassified = "unclassified"


class ZoneType(str, Enum):
    industrial = "industrial"
    forest = "forest"
    farmland = "farmland"


class Satellite(str, Enum):
    snpp = "snpp"
    noaa20 = "noaa20"
    noaa21 = "noaa21"


class DayNight(str, Enum):
    d = "d"
    n = "n"


class PersistentSourceStatus(str, Enum):
    active = "active"
    ended = "ended"


class FlagStatus(str, Enum):
    open = "open"
    reviewed = "reviewed"
    dismissed = "dismissed"


# ---------------------------------------------------------------------------
# FireDetection
# ---------------------------------------------------------------------------


class FireDetectionOut(BaseModel):
    """Response schema for a single FireDetection record (GET /api/fires,
    GET /api/fires/{fire_id}, and embedded in FlaggedCaseDetailOut)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    latitude: float
    longitude: float
    brightness: float
    frp: float
    acq_date: datetime.date
    acq_time: str
    daynight: DayNight
    satellite: Satellite
    confidence: str
    fire_type: FireType
    state: Optional[str]
    district: Optional[str]
    cluster_id: Optional[int]
    is_persistent: bool
    # created_at is intentionally omitted from the API response — it is an
    # internal ingestion timestamp used for dedup and debugging, not shown
    # in the UI (data-model.md §FireDetection note on created_at).


# ---------------------------------------------------------------------------
# Paginated envelope — used only by GET /api/fires
# ---------------------------------------------------------------------------

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated envelope: {"results": [...], "total": int, "limit": int, "offset": int}.
    Used exclusively by endpoints returning FireDetection-scale data
    (api-contract.md conventions section)."""

    results: List[T]
    total: int
    limit: int
    offset: int


# Concrete alias used by the fires router so it does not have to import T.
FireDetectionPage = PaginatedResponse[FireDetectionOut]


# ---------------------------------------------------------------------------
# Zone
# ---------------------------------------------------------------------------


class ZoneOut(BaseModel):
    """Response schema for a cached OSM zone polygon (GET /api/zones).
    Returned as a bare array — no pagination envelope (api-contract.md)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    osm_id: Optional[str]
    zone_type: ZoneType
    name: Optional[str]
    geometry: str  # WKT string as stored
    source: str


# ---------------------------------------------------------------------------
# PersistentSource
# ---------------------------------------------------------------------------


class PersistentSourceSummaryOut(BaseModel):
    """Embedded summary of a PersistentSource inside FlaggedCaseOut.
    Fields match the subset called out in api-contract.md §GET /api/flags:
    first_seen, last_seen, days_active, member_count, status."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    cluster_id: int
    first_seen: datetime.date
    last_seen: datetime.date
    days_active: int
    member_count: int
    zone_type_at_location: Optional[ZoneType]
    status: PersistentSourceStatus


class PersistentSourceOut(BaseModel):
    """Full response schema for a PersistentSource record, used when the full
    object is needed (e.g. GET /api/flags/{flag_id} detail view)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    cluster_id: int
    first_seen: datetime.date
    last_seen: datetime.date
    days_active: int
    member_count: int
    zone_type_at_location: Optional[ZoneType]
    status: PersistentSourceStatus


# ---------------------------------------------------------------------------
# FlaggedCase
# ---------------------------------------------------------------------------


class FlaggedCaseOut(BaseModel):
    """Response schema for a FlaggedCase in the list view (GET /api/flags).
    Includes the linked PersistentSource summary as required by api-contract.md."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    persistent_source_id: int
    anomaly_score: float
    nearest_zone_type: Optional[ZoneType]
    nearest_zone_distance_m: float
    status: FlagStatus
    case_note: Optional[str]
    created_at: datetime.datetime
    updated_at: datetime.datetime
    # Embedded PersistentSource summary (api-contract.md §GET /api/flags)
    persistent_source: PersistentSourceSummaryOut


class FlaggedCaseDetailOut(BaseModel):
    """Response schema for GET /api/flags/{flag_id} — includes the full linked
    PersistentSource and the list of member FireDetection records."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    persistent_source_id: int
    anomaly_score: float
    nearest_zone_type: Optional[ZoneType]
    nearest_zone_distance_m: float
    status: FlagStatus
    case_note: Optional[str]
    created_at: datetime.datetime
    updated_at: datetime.datetime
    persistent_source: PersistentSourceOut
    # Member detections are populated by the router from a separate query
    # (FireDetection has no FK to FlaggedCase; membership is via cluster_id).
    member_detections: List[FireDetectionOut]


# ---------------------------------------------------------------------------
# PATCH /api/flags/{flag_id} request body
# ---------------------------------------------------------------------------


class FlagUpdateIn(BaseModel):
    """Request body for PATCH /api/flags/{flag_id}.
    Both fields are optional individually, but the router must enforce that
    at least one is provided (api-contract.md §PATCH /api/flags/{flag_id})."""

    status: Optional[FlagStatus] = None
    case_note: Optional[str] = None


# ---------------------------------------------------------------------------
# GET /api/stats response
# ---------------------------------------------------------------------------


class TrendPoint(BaseModel):
    """One element of the trend array in StatsOut."""

    date: datetime.date
    count: int


class StatsOut(BaseModel):
    """Response schema for GET /api/stats (sidebar aggregate numbers).
    Field names match api-contract.md §GET /api/stats (trend omitted for prototype)."""

    total_fires: int
    by_type: dict[str, int]
    by_state: dict[str, int]
    persistent_active_count: int
    persistent_ended_count: int
    flagged_open_count: int


# ---------------------------------------------------------------------------
# GET /api/health response
# ---------------------------------------------------------------------------


class HealthOut(BaseModel):
    """Response schema for GET /api/health."""

    status: Literal["ok"]
    mode: DataMode
