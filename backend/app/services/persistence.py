"""
Service to detect persistent heat sources using DBSCAN clustering.

Cluster identity across runs is always PersistentSource.id — never DBSCAN's
raw per-run label (see RULES.md §5 and data-model.md §PersistentSource).
Each run matches its DBSCAN groups to existing active PersistentSource rows
by centroid proximity before deciding whether to continue or create a source.
"""

import datetime
import math
import logging
from collections import Counter
from typing import List, Optional

import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.metrics.pairwise import haversine_distances
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models import FireDetection, PersistentSource

logger = logging.getLogger(__name__)

# --- Tunable thresholds (RULES.md §5: named constants, never inline magic numbers) ---

# Minimum number of distinct acquisition days for a cluster to be considered persistent.
MIN_DAYS_ACTIVE: int = 3

# A PersistentSource moves to 'ended' when last_seen is older than this many days.
ENDED_THRESHOLD_DAYS: int = 7

# DBSCAN neighbourhood radius in km; converted to radians for haversine metric.
EPS_KM: float = 1.0

# Earth radius used for km ↔ radian conversion (RULES.md §5).
EARTH_RADIUS_KM: float = 6371.0088

# Minimum cluster size for DBSCAN.
MIN_SAMPLES: int = 2

# Maximum centroid-to-centroid distance (km) for matching a new DBSCAN group to an
# existing active PersistentSource. Slightly wider than EPS_KM so that a centroid
# that has drifted slightly as members accumulate still matches the same source.
# Starting value — revisit once validate_known_sites.py results exist (RULES.md §5).
CLUSTER_MATCH_RADIUS_KM: float = 1.5


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in km between two WGS84 points."""
    return haversine_distances(
        [[math.radians(lat1), math.radians(lon1)]],
        [[math.radians(lat2), math.radians(lon2)]],
    )[0][0] * EARTH_RADIUS_KM


def run_persistence(db: Session, current_date: Optional[datetime.date] = None) -> int:
    """
    Finds persistent heat sources from non-pending FireDetections.

    Cluster identity is stable across runs: each DBSCAN group is matched to an
    existing active PersistentSource by centroid proximity, not by DBSCAN label.
    Returns the number of currently active persistent sources.
    """
    if current_date is None:
        current_date = datetime.date.today()

    # Fetch all non-pending fires.
    fires: List[FireDetection] = db.scalars(
        select(FireDetection).where(FireDetection.fire_type != "pending")
    ).all()

    if not fires:
        return 0

    # Build radian coordinate array for DBSCAN (haversine requires radians).
    coords = np.array([[math.radians(f.latitude), math.radians(f.longitude)] for f in fires])

    eps_radians = EPS_KM / EARTH_RADIUS_KM
    labels: np.ndarray = DBSCAN(
        eps=eps_radians, min_samples=MIN_SAMPLES, metric="haversine"
    ).fit_predict(coords)

    # Group non-noise fires by DBSCAN label (label == -1 is noise; excluded per RULES.md §5).
    dbscan_groups: dict[int, List[FireDetection]] = {}
    for fire, label in zip(fires, labels):
        if label == -1:
            fire.cluster_id = -1
            fire.is_persistent = False
            continue
        dbscan_groups.setdefault(label, []).append(fire)

    # Load all currently active PersistentSource rows; their stored centroid is the
    # authoritative location for proximity matching (never recomputed from members here).
    active_sources: List[PersistentSource] = db.scalars(
        select(PersistentSource).where(PersistentSource.status == "active")
    ).all()

    for label, group_fires in dbscan_groups.items():
        # Centroid of this run's DBSCAN group.
        group_lat = sum(f.latitude for f in group_fires) / len(group_fires)
        group_lon = sum(f.longitude for f in group_fires) / len(group_fires)

        # --- Match to existing active PersistentSource by centroid proximity ---
        candidates: List[tuple[float, PersistentSource]] = []
        for source in active_sources:
            dist_km = _haversine_km(
                group_lat, group_lon,
                source.centroid_latitude, source.centroid_longitude,
            )
            if dist_km <= CLUSTER_MATCH_RADIUS_KM:
                candidates.append((dist_km, source))

        matched_ps: Optional[PersistentSource] = None
        if len(candidates) == 1:
            matched_ps = candidates[0][1]
        elif len(candidates) > 1:
            # Two or more active sources are within match radius — edge case worth flagging
            # (two real persistent sources that close together is unusual; don't silently merge).
            candidates.sort(key=lambda t: t[0])
            matched_ps = candidates[0][1]
            ids = [str(s.id) for _, s in candidates]
            logger.warning(
                "DBSCAN group centroid (%.4f, %.4f) is within %.1f km of %d active "
                "PersistentSource rows [ids: %s]. Matched to nearest (id=%d, dist=%.3f km). "
                "Two persistent sources this close together should be reviewed.",
                group_lat, group_lon, CLUSTER_MATCH_RADIUS_KM, len(candidates),
                ", ".join(ids), matched_ps.id, candidates[0][0],
            )

        # --- Build the full member set: existing members + new group members ---
        all_members: List[FireDetection] = list(group_fires)
        if matched_ps is not None:
            existing_members: List[FireDetection] = db.scalars(
                select(FireDetection).where(FireDetection.cluster_id == matched_ps.id)
            ).all()
            new_ids = {f.id for f in group_fires}
            for em in existing_members:
                if em.id not in new_ids:
                    all_members.append(em)

        unique_dates = {f.acq_date for f in all_members}
        days_active = len(unique_dates)

        # Below persistence threshold: mark group members but don't create/update a source.
        if days_active < MIN_DAYS_ACTIVE:
            for f in group_fires:
                # If matched, keep the existing cluster_id (history is intact on the source).
                f.cluster_id = matched_ps.id if matched_ps is not None else None
                f.is_persistent = False
            continue

        # --- Persistence threshold reached ---
        first_seen = min(unique_dates)
        last_seen = max(unique_dates)
        days_since_last = (current_date - last_seen).days
        status = "ended" if days_since_last > ENDED_THRESHOLD_DAYS else "active"

        # Combined centroid over the full member set.
        new_centroid_lat = sum(f.latitude for f in all_members) / len(all_members)
        new_centroid_lon = sum(f.longitude for f in all_members) / len(all_members)

        # Majority zone type (fire_type → zone_type translation per RULES.md §5).
        fire_type_to_zone = {
            "wildfire": "forest",
            "agricultural": "farmland",
            "industrial": "industrial",
        }
        zone_types = [
            fire_type_to_zone[f.fire_type]
            for f in all_members
            if f.fire_type in fire_type_to_zone
        ]
        zone_type_at_location = (
            Counter(zone_types).most_common(1)[0][0] if zone_types else None
        )

        if matched_ps is not None:
            ps = matched_ps
        else:
            # New source: create with a temporary cluster_id, flush to get the DB-assigned id,
            # then set cluster_id = id per data-model.md's "always equal to its own id" rule.
            ps = PersistentSource(
                cluster_id=-2,  # placeholder; overwritten after flush
                centroid_latitude=new_centroid_lat,
                centroid_longitude=new_centroid_lon,
                first_seen=first_seen,
                last_seen=last_seen,
                days_active=days_active,
                member_count=len(all_members),
                zone_type_at_location=zone_type_at_location,
                status=status,
            )
            db.add(ps)
            db.flush()  # obtain the DB-assigned id
            ps.cluster_id = ps.id
            active_sources.append(ps)

        ps.centroid_latitude = new_centroid_lat
        ps.centroid_longitude = new_centroid_lon
        ps.first_seen = first_seen
        ps.last_seen = last_seen
        ps.days_active = days_active
        ps.member_count = len(all_members)
        ps.zone_type_at_location = zone_type_at_location
        ps.status = status

        # Stamp every member in the current run's group with the stable PersistentSource.id.
        for f in group_fires:
            f.cluster_id = ps.id
            f.is_persistent = True

    db.commit()

    # Mark sources whose last detection has aged out.
    _expire_ended_sources(db, current_date)

    return db.scalar(
        select(func.count(PersistentSource.id)).where(PersistentSource.status == "active")
    )


def _expire_ended_sources(db: Session, current_date: datetime.date) -> None:
    """Move active PersistentSource rows to 'ended' if last_seen is stale."""
    cutoff = current_date - datetime.timedelta(days=ENDED_THRESHOLD_DAYS)
    stale = db.scalars(
        select(PersistentSource)
        .where(PersistentSource.status == "active")
        .where(PersistentSource.last_seen < cutoff)
    ).all()
    for ps in stale:
        ps.status = "ended"
    if stale:
        db.commit()
