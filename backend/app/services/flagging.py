"""
Service to flag unexplained persistent sources.
"""

from typing import Any

import geopandas as gpd
import pandas as pd
from shapely import wkt
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.models import FireDetection, FlaggedCase, PersistentSource, Zone


def _score_anomaly(cluster_features: Any) -> float:
    """
    Temporary placeholder for the ML anomaly score model.
    Phase 4 will replace this with real inference from ml/infer.py.
    """
    return 0.5


def run_flagging(db: Session) -> int:
    """
    Finds active PersistentSources that are 'unclassified' (no known zone type)
    and creates a FlaggedCase if one doesn't exist, assigning an anomaly score
    and identifying the nearest known zone.
    Returns the number of new FlaggedCases created.
    """
    # 1. Fetch eligible persistent sources without an existing flag
    # Unclassified means zone_type_at_location is None
    sources = db.scalars(
        select(PersistentSource)
        .options(selectinload(PersistentSource.flagged_case))
        .where(
            PersistentSource.status == "active",
            PersistentSource.zone_type_at_location == None
        )
    ).all()
    
    new_flags_count = 0
    
    if not sources:
        return 0

    # 2. Fetch all Zones for distance calculation
    zones = db.scalars(select(Zone)).all()
    if not zones:
        # If there are no zones at all in the DB, we can't find a nearest zone.
        # But this edge case shouldn't happen in production. 
        # We'll just leave them unflagged or flag them with no nearest zone.
        pass
        
    gdf_zones = None
    if zones:
        zone_records = [
            {
                "zone_type": z.zone_type,
                "geometry": wkt.loads(z.geometry)
            } for z in zones
        ]
        gdf_zones = gpd.GeoDataFrame(zone_records, crs="EPSG:4326")
        # Project to EPSG:7755 (India NNRMS) for accurate metric distance
        gdf_zones = gdf_zones.to_crs("EPSG:7755")

    for ps in sources:
        # Requirement 6: Check if already flagged
        if ps.flagged_case is not None:
            continue
            
        # Fetch member detections to find centroid
        members = db.scalars(
            select(FireDetection).where(FireDetection.cluster_id == ps.cluster_id)
        ).all()
        
        if not members:
            continue
            
        lat = sum(m.latitude for m in members) / len(members)
        lon = sum(m.longitude for m in members) / len(members)
        
        # Calculate nearest zone distance
        nearest_type = None
        nearest_dist_m = 0.0
        
        if gdf_zones is not None:
            # Create a GeoSeries for this single point
            point_gdf = gpd.GeoDataFrame(
                geometry=gpd.points_from_xy([lon], [lat]),
                crs="EPSG:4326"
            ).to_crs("EPSG:7755")
            
            # calculate distances to all zones
            distances = gdf_zones.geometry.distance(point_gdf.geometry[0])
            min_idx = distances.idxmin()
            
            nearest_dist_m = float(distances[min_idx])
            nearest_type = gdf_zones.iloc[min_idx]["zone_type"]

        # Call placeholder ML function
        # For now cluster_features is None since features.py isn't built yet
        anomaly_score = _score_anomaly(cluster_features=None)

        fc = FlaggedCase(
            persistent_source_id=ps.id,
            anomaly_score=anomaly_score,
            nearest_zone_type=nearest_type,
            nearest_zone_distance_m=nearest_dist_m,
            status="open",
            case_note="[AUTO-NOTE] anomaly_score is a Phase 3 placeholder (0.5); ML model not yet integrated."
        )
        db.add(fc)
        new_flags_count += 1

    db.commit()
    return new_flags_count
