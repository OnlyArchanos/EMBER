"""
Geocoding service for the SIH26162 fire-detection pipeline.

Resolves state and district names for a batch of fire-detection points via a
vectorised point-in-polygon spatial join against the OSM administrative
boundary GeoJSON cached by osm_client.py.  No live Nominatim call is made in
the primary path (RULES.md §6).
"""

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from app.services.osm_client import ADMIN_BOUNDARIES_PATH

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level cache -- loaded once on first use, never reloaded per call.
# ---------------------------------------------------------------------------

_boundaries: gpd.GeoDataFrame | None = None


def _load_boundaries() -> gpd.GeoDataFrame:
    """Load admin_boundaries.geojson into a GeoDataFrame (cached after first call).

    Splits the single FeatureCollection into state-level and district-level
    rows using the ``admin_level`` property written by osm_client.py
    (``"states"`` or ``"districts"``).

    Raises:
        FileNotFoundError: if the cache file hasn't been produced yet by
            ``osm_client.fetch_and_cache_admin_boundaries()``.
        ValueError: if the file is present but contains no usable features.
    """
    global _boundaries  # noqa: PLW0603

    if _boundaries is not None:
        return _boundaries

    path = Path(ADMIN_BOUNDARIES_PATH)
    if not path.exists():
        raise FileNotFoundError(
            f"Admin boundary cache not found at {path}. "
            "Run osm_client.fetch_and_cache_admin_boundaries() first."
        )

    gdf = gpd.read_file(path)  # CRS defaults to EPSG:4326 for GeoJSON

    if gdf.empty:
        raise ValueError(f"Admin boundary cache at {path} contains no features.")

    if "admin_level" not in gdf.columns:
        raise ValueError(
            "Admin boundary cache is missing the 'admin_level' column. "
            "Re-run osm_client.fetch_and_cache_admin_boundaries()."
        )

    # Ensure CRS is set; GeoJSON is always WGS-84 but be explicit.
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")

    logger.info(
        "Loaded %d admin boundary features from %s.", len(gdf), path
    )
    _boundaries = gdf
    return _boundaries


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_admin(
    points: pd.DataFrame | gpd.GeoDataFrame,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
) -> pd.DataFrame:
    """Resolve state and district for every row in *points* via spatial join.

    Uses a single vectorised GeoPandas ``sjoin`` against the cached OSM
    administrative boundary polygons — no per-row Python loop, no live
    Nominatim call.

    Args:
        points:  DataFrame or GeoDataFrame containing fire-detection rows.
                 Must have columns named *lat_col* and *lon_col* (floats,
                 WGS-84 decimal degrees) unless *points* is already a
                 GeoDataFrame with a valid Point geometry column.
        lat_col: Name of the latitude column (ignored if *points* is a
                 GeoDataFrame with an active geometry column).
        lon_col: Name of the longitude column (same caveat).

    Returns:
        A copy of *points* with two new columns added:
          - ``state``    — matched state name (str or None if unmatched)
          - ``district`` — matched district name (str or None if unmatched)

        Unmatched rows (points that fall outside all known boundaries, e.g.
        coastal detections or data errors) receive ``None`` in both columns —
        never silently defaulted to a nearest neighbour (RULES.md §1 rule 5).

    Raises:
        FileNotFoundError: propagated from ``_load_boundaries()`` if the
            cache file is absent.
        ValueError: propagated from ``_load_boundaries()`` if the cache is
            malformed, or raised here if *points* lacks the required columns.
    """
    boundaries = _load_boundaries()

    # ------------------------------------------------------------------
    # Build a point GeoDataFrame from the input, preserving original index.
    # ------------------------------------------------------------------
    if isinstance(points, gpd.GeoDataFrame) and not points.geometry.is_empty.all():
        pts_gdf = points.copy()
    else:
        # Plain DataFrame (or GeoDataFrame without geometry) — build Points.
        missing = [c for c in (lat_col, lon_col) if c not in points.columns]
        if missing:
            raise ValueError(
                f"points DataFrame is missing required columns: {missing}"
            )
        pts_gdf = gpd.GeoDataFrame(
            points.copy(),
            geometry=[
                Point(lon, lat)
                for lon, lat in zip(points[lon_col], points[lat_col])
            ],
            crs="EPSG:4326",
        )

    if pts_gdf.crs is None:
        pts_gdf = pts_gdf.set_crs("EPSG:4326")

    # ------------------------------------------------------------------
    # Split boundary cache into state and district layers.
    # admin_level values are the string keys from _ADMIN_QUERIES:
    #   "states"    -> OSM admin_level=4 (State / Union Territory)
    #   "districts" -> OSM admin_level=5 (District)
    # ------------------------------------------------------------------
    state_boundaries = (
        boundaries[boundaries["admin_level"] == "states"][["name", "geometry"]]
        .rename(columns={"name": "_state_name"})
    )
    district_boundaries = (
        boundaries[boundaries["admin_level"] == "districts"][["name", "geometry"]]
        .rename(columns={"name": "_district_name"})
    )

    # ------------------------------------------------------------------
    # Vectorised point-in-polygon joins.
    # predicate="within" is the standard for point-in-polygon queries.
    # A left join preserves every input row; unmatched rows get NaN.
    # De-duplicate in case a point sits exactly on a shared boundary.
    # ------------------------------------------------------------------
    joined_states = pts_gdf.sjoin(
        state_boundaries, how="left", predicate="within"
    )
    joined_states = joined_states[~joined_states.index.duplicated(keep="first")]

    joined_districts = pts_gdf.sjoin(
        district_boundaries, how="left", predicate="within"
    )
    joined_districts = joined_districts[
        ~joined_districts.index.duplicated(keep="first")
    ]

    # ------------------------------------------------------------------
    # Assemble result: graft state/district columns onto a copy of the
    # original input so the caller gets back the same type they passed in.
    # ------------------------------------------------------------------
    result = points.copy()
    result["state"] = (
        joined_states["_state_name"]
        .reindex(result.index)
        .where(joined_states["_state_name"].reindex(result.index).notna(), other=None)
    )
    result["district"] = (
        joined_districts["_district_name"]
        .reindex(result.index)
        .where(
            joined_districts["_district_name"].reindex(result.index).notna(),
            other=None,
        )
    )

    unmatched_state = result["state"].isna().sum()
    unmatched_district = result["district"].isna().sum()
    if unmatched_state or unmatched_district:
        logger.debug(
            "resolve_admin: %d/%d points unmatched for state, "
            "%d/%d unmatched for district.",
            unmatched_state,
            len(result),
            unmatched_district,
            len(result),
        )

    return result
