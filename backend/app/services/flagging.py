"""
Service to flag unexplained persistent sources.

Distance-to-nearest-zone and all other cluster features are computed via
compute_features() from app.ml.features — there is no independent distance
implementation here (RULES.md §5 train/serve-consistency rule).

Anomaly scoring delegates to infer.score_persistent_source() from
app.ml.infer — there is no mock or fallback.  If the model artifact has not
been loaded (infer.load_model() not called at startup), scoring raises
RuntimeError immediately so the misconfiguration is visible, not silent.
"""

from typing import Optional

import geopandas as gpd
from shapely import wkt
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.ml import infer
from app.ml.features import compute_features
from app.models import FireDetection, FlaggedCase, PersistentSource, Zone


def run_flagging(db: Session) -> int:
    """
    Finds active PersistentSources that are 'unclassified' (no known zone type)
    and creates a FlaggedCase if one doesn't exist, assigning a real ML anomaly
    score from infer.score_persistent_source() and the nearest known zone.
    Returns the number of new FlaggedCases created.

    Raises:
        RuntimeError: if infer.load_model() has not been called before this
            function runs (propagated from infer.score_persistent_source).
    """
    # 1. Fetch eligible persistent sources without an existing flag.
    # Unclassified means zone_type_at_location is None.
    sources = db.scalars(
        select(PersistentSource)
        .options(selectinload(PersistentSource.flagged_case))
        .where(
            PersistentSource.status == "active",
            PersistentSource.zone_type_at_location == None,
        )
    ).all()

    if not sources:
        return 0

    # 2. Build the zone GeoDataFrame once for the whole batch.
    # Projected to EPSG:7755 (India NNRMS) for accurate metric distances.
    # compute_features() reprojects each centroid point to match this CRS
    # internally, so both sides of every distance calculation are consistent.
    zones = db.scalars(select(Zone)).all()
    gdf_zones: Optional[gpd.GeoDataFrame] = None
    if zones:
        zone_records = [
            {"zone_type": z.zone_type, "geometry": wkt.loads(z.geometry)}
            for z in zones
        ]
        gdf_zones = gpd.GeoDataFrame(zone_records, crs="EPSG:4326").to_crs("EPSG:7755")

    new_flags_count = 0

    for ps in sources:
        # Idempotency guard: skip if already flagged (RULES.md §5).
        if ps.flagged_case is not None:
            continue

        members = list(
            db.scalars(
                select(FireDetection).where(FireDetection.cluster_id == ps.cluster_id)
            ).all()
        )

        if not members:
            continue

        # Delegate all feature computation — including nearest-zone distance —
        # to the shared features module.  No independent distance logic here.
        features = compute_features(ps, members, gdf_zones)

        nearest_dist_m: float = features["nearest_zone_distance_m"]
        nearest_type: Optional[str] = features["nearest_zone_type"]

        # Score via the trained model.  compute_features() is also called
        # internally by score_persistent_source() — the double call is a known
        # redundancy; a future refactor could accept a pre-computed feature dict.
        # Raises RuntimeError if load_model() was not called at startup.
        anomaly_score = infer.score_persistent_source(ps, members, gdf_zones)

        fc = FlaggedCase(
            persistent_source_id=ps.id,
            anomaly_score=anomaly_score,
            nearest_zone_type=nearest_type,
            nearest_zone_distance_m=nearest_dist_m,
            status="open",
        )
        db.add(fc)
        new_flags_count += 1

    db.commit()
    return new_flags_count
