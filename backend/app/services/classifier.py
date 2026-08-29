"""
Service to classify pending FireDetections against known OSM Zones via spatial join.
"""

import geopandas as gpd
import pandas as pd
from shapely import wkt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FireDetection, Zone


def classify_fires(db: Session) -> int:
    """
    Finds all 'pending' FireDetections and classifies them based on intersection 
    with known Zones. Returns the number of fires classified.
    
    Mapping (Zone.zone_type -> FireDetection.fire_type):
    - industrial -> industrial
    - forest -> wildfire
    - farmland -> agricultural
    - (no match) -> unclassified
    """
    pending_fires = db.scalars(
        select(FireDetection).where(FireDetection.fire_type == "pending")
    ).all()
    
    if not pending_fires:
        return 0

    zones = db.scalars(select(Zone)).all()
    
    if not zones:
        for fire in pending_fires:
            fire.fire_type = "unclassified"
        db.commit()
        return len(pending_fires)

    # Create GeoDataFrame for fires
    fire_records = [
        {
            "id": f.id,
            "latitude": f.latitude,
            "longitude": f.longitude,
        } for f in pending_fires
    ]
    df_fires = pd.DataFrame(fire_records)
    gdf_fires = gpd.GeoDataFrame(
        df_fires, 
        geometry=gpd.points_from_xy(df_fires.longitude, df_fires.latitude),
        crs="EPSG:4326"
    )

    # Create GeoDataFrame for zones
    zone_records = [
        {
            "id": z.id,
            "zone_type": z.zone_type,
            "geometry": wkt.loads(z.geometry)
        } for z in zones
    ]
    gdf_zones = gpd.GeoDataFrame(zone_records, crs="EPSG:4326")

    # Spatial join (points within polygons)
    joined = gpd.sjoin(gdf_fires, gdf_zones, how="left", predicate="within")

    zone_to_fire_map = {
        "industrial": "industrial",
        "forest": "wildfire",
        "farmland": "agricultural"
    }

    priority_order = {
        "industrial": 3,
        "wildfire": 2,
        "agricultural": 1,
        "unclassified": 0
    }

    classification_updates = {}
    for _, row in joined.iterrows():
        fire_id = int(row["id_left"])
        matched_zone_type = row["zone_type"]
        
        if pd.isna(matched_zone_type):
            fire_type = "unclassified"
        else:
            fire_type = zone_to_fire_map.get(matched_zone_type, "unclassified")
            
        current_best = classification_updates.get(fire_id, "unclassified")
        if fire_id not in classification_updates or priority_order.get(fire_type, 0) > priority_order.get(current_best, 0):
            classification_updates[fire_id] = fire_type

    for fire in pending_fires:
        new_type = classification_updates.get(fire.id, "unclassified")
        fire.fire_type = new_type

    db.commit()
    return len(pending_fires)
