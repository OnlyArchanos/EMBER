"""
SQLAlchemy ORM table definitions for the SIH26162 fire-detection pipeline.
This module is data-structure only — no business logic, no queries.
Field names, types, enum values, and defaults are frozen by docs/data-model.md;
do not rename or add fields here without first updating that document and
obtaining explicit human sign-off (RULES.md §1, rule 2).
"""

import datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FireDetection(Base):
    """One row per raw NASA FIRMS detection. See data-model.md §FireDetection."""

    __tablename__ = "fire_detections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    brightness: Mapped[float] = mapped_column(Float, nullable=False)
    frp: Mapped[float] = mapped_column(Float, nullable=False)
    acq_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    # acq_time is stored as a string exactly as FIRMS reports it (HHMM).
    acq_time: Mapped[str] = mapped_column(String(4), nullable=False)
    # daynight: 'd' | 'n'
    daynight: Mapped[str] = mapped_column(String(1), nullable=False)
    # satellite: 'snpp' | 'noaa20' | 'noaa21'
    satellite: Mapped[str] = mapped_column(String(8), nullable=False)
    # confidence: raw FIRMS value ('l' / 'n' / 'h' for VIIRS)
    confidence: Mapped[str] = mapped_column(String(2), nullable=False)
    # fire_type enum: 'pending' | 'industrial' | 'wildfire' | 'agricultural' | 'unclassified'
    # Default is 'pending' (not yet classified). 'unclassified' is a separate, distinct value
    # meaning the classifier ran and found no matching zone — do NOT conflate the two.
    # Rows that are still 'pending' must be excluded from persistence and flagging logic.
    fire_type: Mapped[str] = mapped_column(
        String(14), nullable=False, default="pending", server_default="pending"
    )
    state: Mapped[str | None] = mapped_column(String, nullable=True)
    district: Mapped[str | None] = mapped_column(String, nullable=True)
    # cluster_id: set by persistence.py; None until clustering has run; -1 = DBSCAN noise
    # (excluded from persistence logic per RULES.md §5).
    cluster_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_persistent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        server_default="CURRENT_TIMESTAMP",
    )

    # Deduplication key: (round(latitude, 4), round(longitude, 4), acq_date, acq_time, satellite)
    # NOT enforced as a DB-level unique constraint here — dedup is enforced by the ingestion
    # service in Phase 2 (services/firms_client.py), keeping this file to data structure only
    # per RULES.md §3. A DB constraint here would also complicate the "update existing row on
    # match" semantics required by data-model.md.


class Zone(Base):
    """Cached OSM polygons used for classification and map overlay. See data-model.md §Zone."""

    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    osm_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # zone_type enum: 'industrial' | 'forest' | 'farmland'
    zone_type: Mapped[str] = mapped_column(String(12), nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    # geometry stored as WKT; spatial joins are done in GeoPandas at the service layer.
    geometry: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(
        String, nullable=False, default="osm", server_default="osm"
    )


class PersistentSource(Base):
    """One row per DBSCAN cluster that passed the noise-excluded persistence check.
    See data-model.md §PersistentSource. cluster_id is never -1 here."""

    __tablename__ = "persistent_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # cluster_id always equals this row's own id (data-model.md §PersistentSource); never -1.
    cluster_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # centroid_latitude/longitude: representative location of the cluster, recomputed as new
    # members join. Used each run to match a DBSCAN group back to this physical source by
    # proximity. Required by data-model.md §PersistentSource; absent previously — added here
    # as a code-conforms-to-contract fix (no contract change; fields are in the frozen schema).
    centroid_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    centroid_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    first_seen: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    last_seen: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    days_active: Mapped[int] = mapped_column(Integer, nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # zone_type_at_location: one of Zone.zone_type's values, or null for an unclassified location.
    zone_type_at_location: Mapped[str | None] = mapped_column(String(12), nullable=True)
    # status enum: 'active' | 'ended'
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    flagged_case: Mapped["FlaggedCase | None"] = relationship(
        "FlaggedCase", back_populates="persistent_source", uselist=False
    )


class FlaggedCase(Base):
    """One row per persistent source that is unclassified and above the ML confidence threshold.
    See data-model.md §FlaggedCase. Stores why it was flagged (anomaly_score, nearest zone
    info) per RULES.md §5 — a flag with no stored reasoning is not acceptable."""

    __tablename__ = "flagged_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    persistent_source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("persistent_sources.id"), nullable=False
    )
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False)
    # nearest_zone_type: closest known zone type even though it didn't contain the point.
    nearest_zone_type: Mapped[str | None] = mapped_column(String(12), nullable=True)
    nearest_zone_distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    # status enum: 'open' | 'reviewed' | 'dismissed'
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default="open"
    )
    case_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        server_default="CURRENT_TIMESTAMP",
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        server_default="CURRENT_TIMESTAMP",
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

    persistent_source: Mapped["PersistentSource"] = relationship(
        "PersistentSource", back_populates="flagged_case"
    )
