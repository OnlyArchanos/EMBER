"""
Feature engineering for the ML anomaly-detection layer.

compute_features() computes ML features for a single PersistentSource from its
member FireDetection rows and a pre-built zone GeoDataFrame.  Both train.py
(batch path) and infer.py (single-source path) call into this module — there
is exactly one implementation of each feature, never two separately-written
computations (RULES.md §5).
"""

import logging
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from app.models import FireDetection, PersistentSource

logger = logging.getLogger(__name__)

# Canonical feature column order — used by train.py and infer.py to guarantee
# consistent column layout between the training matrix and inference vectors.
# Never reorder without retraining the model artifact.
FEATURE_COLUMNS: list[str] = [
    "frp_mean",
    "frp_max",
    "frp_trend",
    "day_night_ratio",
    "detection_density",
    "confidence_high_frac",
    "nearest_zone_distance_m",
]

# Sentinel for nearest_zone_distance_m when gdf_zones has no rows.
# Chosen as a clearly-out-of-range negative value so it fails loudly if it
# ever reaches the model.  train.py rejects any training matrix row containing
# this value before fitting (see train.py's pre-fit guard).
NO_ZONES_SENTINEL: float = -1.0


def normalize_score(neg_score: float, score_min: float, score_max: float) -> float:
    """
    Map a negated IsolationForest score to [0, 1] using training-set bounds.

    neg_score is -score_samples() output; higher means more anomalous.
    score_min and score_max are the min/max of neg_scores over the training set,
    stored in the model artifact by train.py.

    Returns a float clipped to [0.0, 1.0].  If the training set was degenerate
    (score_min == score_max), returns 0.5 rather than dividing by zero.

    Both train.py's post-fit validation hook and infer.py's scoring path call
    this function — there is exactly one normalization implementation.
    """
    if score_max == score_min:
        return 0.5
    return float(np.clip(
        (neg_score - score_min) / (score_max - score_min), 0.0, 1.0
    ))


def compute_features(
    ps: PersistentSource,
    members: list[FireDetection],
    gdf_zones: Optional[gpd.GeoDataFrame],
) -> dict[str, object]:
    """
    Compute ML features for a single PersistentSource.

    Returns a dict with all FEATURE_COLUMNS keys (float) plus
    'nearest_zone_type' (str or None — metadata output for flagging.py,
    not a model input, excluded from FEATURE_COLUMNS).

    Callers who build a DataFrame directly from this dict must index by
    FEATURE_COLUMNS to select model inputs and exclude 'nearest_zone_type'.
    compute_features_batch() does this automatically.

    When gdf_zones is None or empty, nearest_zone_distance_m is set to
    NO_ZONES_SENTINEL and nearest_zone_type to None, and a warning is logged.
    This should never occur in production: zones must be fetched before any
    PersistentSource exists.

    gdf_zones must be in a projected (metric) CRS, not EPSG:4326, so that
    distances are in metres.  The centroid point is reprojected to gdf_zones.crs
    internally — both sides of every distance calculation are always in the same
    CRS.

    Raises:
        ValueError: if members is empty, or if gdf_zones is non-empty but in a
            geographic (degree-based) CRS.
    """
    if not members:
        raise ValueError(
            f"PersistentSource id={ps.id}: members list is empty; "
            "cannot compute features."
        )

    frp_values = np.array([m.frp for m in members], dtype=float)

    # F1: frp_mean — average fire radiative power across all member detections.
    frp_mean = float(np.mean(frp_values))

    # F2: frp_max — peak fire radiative power ever observed in this cluster.
    frp_max = float(np.max(frp_values))

    # F3: frp_trend — linear slope of daily-mean FRP over time (FRP units/day).
    # Aggregated to daily means before fitting so the slope measures genuine
    # intensity change, not overpass-count variation: a day with more satellite
    # passes would otherwise contribute more data points to the regression and
    # bias the slope toward high-observation days regardless of actual FRP change.
    unique_dates = {m.acq_date for m in members}
    if len(unique_dates) < 2:
        # Defensive: days_active >= MIN_DAYS_ACTIVE >= 3 is enforced upstream,
        # so single-date clusters shouldn't reach here; clamp is belt-and-suspenders.
        frp_trend = 0.0
    else:
        daily_df = pd.DataFrame(
            {"date": [m.acq_date.toordinal() for m in members], "frp": frp_values}
        )
        daily_mean = daily_df.groupby("date")["frp"].mean().reset_index()
        # np.polyfit degree-1 returns [slope, intercept]; no division-by-zero risk.
        frp_trend = float(np.polyfit(daily_mean["date"], daily_mean["frp"], deg=1)[0])

    # F4: day_night_ratio — fraction of detections acquired during daytime.
    # len(members) >= MIN_SAMPLES >= 2 by construction; no division risk.
    day_count = sum(1 for m in members if m.daynight == "d")
    day_night_ratio = float(day_count / len(members))

    # F5: detection_density — mean member detections per active day.
    # Both numerator and denominator are derived from the members argument, not
    # from stored ORM fields (ps.member_count / ps.days_active), so this stays
    # consistent with the other features if the caller has filtered the member
    # list or if ps.member_count is momentarily stale.
    # Simplification: satellite overpass frequency varies geographically; density
    # reflects detection opportunity as well as true fire intensity.
    # len(unique_dates) >= 1 always (members is non-empty); no division risk.
    detection_density = float(len(members) / len(unique_dates))

    # F6: confidence_high_frac — fraction of members with FIRMS confidence 'h'.
    high_count = sum(1 for m in members if m.confidence == "h")
    confidence_high_frac = float(high_count / len(members))

    # F7: nearest_zone_distance_m — distance in metres from cluster centroid to
    # the nearest Zone polygon of any type.  Computed for every PersistentSource
    # (not just unclassified ones) so train.py gets this feature for both
    # explained and unexplained examples.
    if gdf_zones is None or len(gdf_zones) == 0:
        logger.warning(
            "PersistentSource id=%d: gdf_zones is empty; nearest_zone_distance_m "
            "set to sentinel %s.  Zone data must be fetched before persistence "
            "detection runs — this should not occur in production.",
            ps.id,
            NO_ZONES_SENTINEL,
        )
        nearest_zone_distance_m: float = NO_ZONES_SENTINEL
        nearest_zone_type: Optional[str] = None
    else:
        if gdf_zones.crs is None or gdf_zones.crs.is_geographic:
            raise ValueError(
                "gdf_zones must be in a projected (metric) CRS so that distances "
                f"are in metres; got {gdf_zones.crs!r}.  Call .to_crs() before "
                "passing the GeoDataFrame to compute_features."
            )
        # Reproject the centroid to match gdf_zones.crs so both sides of the
        # distance call are in the same metric CRS.  Keying off gdf_zones.crs
        # (not a hardcoded EPSG code) keeps this correct in tests that use a
        # different metric projection.
        centroid_geom = (
            gpd.GeoDataFrame(
                geometry=[Point(ps.centroid_longitude, ps.centroid_latitude)],
                crs="EPSG:4326",
            )
            .to_crs(gdf_zones.crs)
            .geometry.iloc[0]
        )

        # Vectorized: one distance() call over the full zone GeoDataFrame.
        # Use .loc[min_idx] (label-based), not .iloc[min_idx] (position-based):
        # idxmin() returns an index label, and on a non-contiguous index those
        # two are different — .iloc with a label silently returns the wrong row.
        distances = gdf_zones.geometry.distance(centroid_geom)
        min_idx = distances.idxmin()
        nearest_zone_distance_m = float(distances.loc[min_idx])
        nearest_zone_type = str(gdf_zones.loc[min_idx]["zone_type"])

    return {
        "frp_mean": frp_mean,
        "frp_max": frp_max,
        "frp_trend": frp_trend,
        "day_night_ratio": day_night_ratio,
        "detection_density": detection_density,
        "confidence_high_frac": confidence_high_frac,
        "nearest_zone_distance_m": nearest_zone_distance_m,
        # Metadata output for flagging.py — not a model input, excluded from FEATURE_COLUMNS.
        # Callers building a DataFrame from this dict must use FEATURE_COLUMNS to
        # select model inputs; compute_features_batch() does this automatically.
        "nearest_zone_type": nearest_zone_type,
    }


def compute_features_batch(
    sources: list[tuple[PersistentSource, list[FireDetection]]],
    gdf_zones: Optional[gpd.GeoDataFrame],
) -> pd.DataFrame:
    """
    Compute features for a batch of (PersistentSource, members) pairs.

    Returns a DataFrame with columns exactly matching FEATURE_COLUMNS, in that
    order.  'nearest_zone_type' is excluded — it is metadata, not a model feature.

    The implementation is compute_features() called once per source: there is
    no separately-written batch logic.  The shared code path is compute_features().

    Used by train.py.  infer.py uses compute_features() directly for single-source
    inference.
    """
    rows = [compute_features(ps, members, gdf_zones) for ps, members in sources]
    df = pd.DataFrame(rows)
    # Slice to FEATURE_COLUMNS to enforce column order and drop metadata columns.
    return df[FEATURE_COLUMNS]
