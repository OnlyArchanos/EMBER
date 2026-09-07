"""
OpenStreetMap / Overpass ingestion client for the SIH26162 fire-detection pipeline.

Fetches three landuse polygon types for India -- industrial, forest, farmland --
via Overpass QL and upserts them into the Zone table keyed on osm_id (never
wipes and reinserts the whole table).  Also fetches state- and district-level
administrative boundary polygons (admin_level=4 and admin_level=5 for India per
the OSM India Administrative Boundaries wiki) and caches them to
data/processed/admin_boundaries.geojson for use by geocode.py -- those
boundaries are NOT Zone records and are never written to the zones table.

Raw Overpass JSON responses land in data/raw/ before any DB write or file write
(RULES.md s6).  Overpass is treated as inherently unreliable for large queries;
timeouts and rate-limit responses are handled with exponential-backoff retries.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from shapely.geometry import shape
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Zone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths -- raw and processed landing zones (RULES.md s6)
# ---------------------------------------------------------------------------

_RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw"
_PROCESSED_DIR = Path(__file__).resolve().parents[3] / "data" / "processed"

# Cached admin boundaries written here; read by geocode.py for point-in-polygon.
# Each Feature in this file carries an "admin_level" property with value "states"
# (OSM admin_level=4, State / Union Territory) or "districts" (OSM admin_level=5,
# District).  geocode.py uses this to split state vs. district lookups.
ADMIN_BOUNDARIES_PATH = _PROCESSED_DIR / "admin_boundaries.geojson"

# ---------------------------------------------------------------------------
# Overpass endpoint and retry settings
# ---------------------------------------------------------------------------

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Three attempts with 30 -> 60 -> 120 s back-off covers most transient load spikes.
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE_S = 30

# Server timeout hint (seconds); the HTTP client timeout is set slightly higher
# so the server gets the chance to return an error rather than the socket hanging.
_OVERPASS_TIMEOUT = 180

# ---------------------------------------------------------------------------
# Zone-type -> Overpass QL query mapping
# Matches Zone.zone_type enum exactly: 'industrial' | 'forest' | 'farmland'
# ---------------------------------------------------------------------------

_ZONE_QUERIES: dict[str, str] = {
    "industrial": (
        f"[out:json][timeout:{_OVERPASS_TIMEOUT}];\n"
        "area[\"ISO3166-1\"=\"IN\"]->.india;\n"
        "(\n"
        "  way[\"landuse\"=\"industrial\"](area.india);\n"
        "  relation[\"landuse\"=\"industrial\"](area.india);\n"
        ");\n"
        "out body;\n"
        ">;\n"
        "out skel qt;"
    ),
    "forest": (
        f"[out:json][timeout:{_OVERPASS_TIMEOUT}];\n"
        "area[\"ISO3166-1\"=\"IN\"]->.india;\n"
        "(\n"
        "  way[\"landuse\"=\"forest\"](area.india);\n"
        "  relation[\"landuse\"=\"forest\"](area.india);\n"
        "  way[\"natural\"=\"wood\"](area.india);\n"
        "  relation[\"natural\"=\"wood\"](area.india);\n"
        ");\n"
        "out body;\n"
        ">;\n"
        "out skel qt;"
    ),
    "farmland": (
        f"[out:json][timeout:{_OVERPASS_TIMEOUT}];\n"
        "area[\"ISO3166-1\"=\"IN\"]->.india;\n"
        "(\n"
        "  way[\"landuse\"=\"farmland\"](area.india);\n"
        "  relation[\"landuse\"=\"farmland\"](area.india);\n"
        "  way[\"landuse\"=\"orchard\"](area.india);\n"
        "  relation[\"landuse\"=\"orchard\"](area.india);\n"
        ");\n"
        "out body;\n"
        ">;\n"
        "out skel qt;"
    ),
}

# Admin boundary queries -- fetched separately, NOT written to the zones table.
# India OSM admin_level values (OSM India Administrative Boundaries wiki):
#   admin_level=4  ->  State / Union Territory
#   admin_level=5  ->  District
_ADMIN_QUERIES: dict[str, str] = {
    "states": (
        f"[out:json][timeout:{_OVERPASS_TIMEOUT}];\n"
        "area[\"ISO3166-1\"=\"IN\"]->.india;\n"
        "(\n"
        "  relation[\"boundary\"=\"administrative\"][\"admin_level\"=\"4\"](area.india);\n"
        ");\n"
        "out body;\n"
        ">;\n"
        "out skel qt;"
    ),
    "districts": (
        f"[out:json][timeout:{_OVERPASS_TIMEOUT}];\n"
        "area[\"ISO3166-1\"=\"IN\"]->.india;\n"
        "(\n"
        "  relation[\"boundary\"=\"administrative\"][\"admin_level\"=\"5\"](area.india);\n"
        ");\n"
        "out body;\n"
        ">;\n"
        "out skel qt;"
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _build_zone_query(
    zone_type: str,
    bbox: tuple[float, float, float, float] | dict[str, float] | None = None,
) -> str:
    """Return the Overpass QL query string for zone_type, optionally scoped by bbox.

    Overpass expects bounding box as (south, west, north, east).
    When bbox is None, defaults to all-India query using area['ISO3166-1'='IN'].
    """
    base_query = _ZONE_QUERIES[zone_type]
    if bbox is None:
        return base_query

    if isinstance(bbox, dict):
        w, s, e, n = bbox["west"], bbox["south"], bbox["east"], bbox["north"]
    else:
        w, s, e, n = bbox

    # Overpass bbox ordering: south, west, north, east
    header = f"[out:json][timeout:{_OVERPASS_TIMEOUT}];\n"
    bbox_header = f"[out:json][timeout:{_OVERPASS_TIMEOUT}][bbox:{s},{w},{n},{e}];\n"
    if header not in base_query:
        raise RuntimeError(f"Expected header {header!r} not found in base query for {zone_type}")
    query = base_query.replace(header, bbox_header, 1)
    # When a bounding box is supplied, the nationwide area filter is redundant and causes severe
    # Overpass server-side latency / HTTP 504 timeouts. Strip it only for scoped queries.
    query = query.replace('area["ISO3166-1"="IN"]->.india;\n', "")
    query = query.replace("(area.india)", "")
    if 'area["ISO3166-1"="IN"]' in query or "(area.india)" in query:
        raise RuntimeError(
            f"Failed to strip area filter from scoped query template for zone_type={zone_type}"
        )
    return query


def fetch_and_upsert_zones(
    db: Session,
    bbox: tuple[float, float, float, float] | dict[str, float] | None = None,
) -> int:
    """Fetch OSM landuse polygons for all three zone types and upsert into the DB.

    Upserts by osm_id -- never wipes and reinserts the whole table.  Returns
    the total number of Zone rows inserted or updated.

    Raises on unrecoverable Overpass failures after all retries are exhausted.

    Args:
        db:   SQLAlchemy session; caller is responsible for commit/rollback.
        bbox: Optional (west, south, east, north) tuple or dict to scope
              the fetch to a bounding box. When omitted, defaults to all of India.
    """
    _RAW_DIR.mkdir(parents=True, exist_ok=True)
    _PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    total = 0
    label_suffix = "_bbox" if bbox else ""
    for zone_type in _ZONE_QUERIES:
        query = _build_zone_query(zone_type, bbox=bbox)
        logger.info("Fetching Overpass data for zone_type=%s", zone_type)
        raw_data = _fetch_overpass(query, label=f"{zone_type}{label_suffix}")
        _write_raw_json(raw_data, label=f"zones_{zone_type}{label_suffix}")

        features = _parse_overpass_to_features(raw_data)
        logger.info(
            "Parsed %d polygon features for zone_type=%s", len(features), zone_type
        )

        _write_processed_geojson(features, label=f"zones_{zone_type}{label_suffix}")

        for feat in features:
            upsert_zone(db, feat, zone_type)
            total += 1

    logger.info("Zone upsert complete -- %d features processed across all types.", total)
    return total


def _build_admin_query(
    level: str,
    bbox: tuple[float, float, float, float] | dict[str, float] | None = None,
) -> str:
    """Return the Overpass QL query string for admin level, optionally scoped by bbox."""
    base_query = _ADMIN_QUERIES[level]
    if bbox is None:
        return base_query

    if isinstance(bbox, dict):
        w, s, e, n = bbox["west"], bbox["south"], bbox["east"], bbox["north"]
    else:
        w, s, e, n = bbox

    header = f"[out:json][timeout:{_OVERPASS_TIMEOUT}];\n"
    bbox_header = f"[out:json][timeout:{_OVERPASS_TIMEOUT}][bbox:{s},{w},{n},{e}];\n"
    if header not in base_query:
        raise RuntimeError(f"Expected header {header!r} not found in base query for admin level={level}")
    query = base_query.replace(header, bbox_header, 1)
    query = query.replace('area["ISO3166-1"="IN"]->.india;\n', "")
    query = query.replace("(area.india)", "")
    if 'area["ISO3166-1"="IN"]' in query or "(area.india)" in query:
        raise RuntimeError(
            f"Failed to strip area filter from scoped query template for admin level={level}"
        )
    return query


def fetch_and_cache_admin_boundaries(
    bbox: tuple[float, float, float, float] | dict[str, float] | None = None,
) -> None:
    """Fetch OSM administrative boundary polygons (states + districts) for India
    and write them to data/processed/admin_boundaries.geojson.

    Used by geocode.py for local point-in-polygon resolution of state/district
    names -- never re-fetched live in a request path (RULES.md s6).
    NOT written to the zones table; does NOT create Zone records.

    Raises on unrecoverable Overpass failures after all retries are exhausted.

    Args:
        bbox: Optional (west, south, east, north) tuple or dict to scope
              admin boundary fetching to a bounding box. When omitted, defaults to all of India.
    """
    _RAW_DIR.mkdir(parents=True, exist_ok=True)
    _PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    all_features: list[dict] = []
    label_suffix = "_bbox" if bbox else ""
    for level in _ADMIN_QUERIES:
        query = _build_admin_query(level, bbox=bbox)
        logger.info("Fetching Overpass admin boundaries for level=%s", level)
        raw_data = _fetch_overpass(query, label=f"admin_{level}{label_suffix}")
        _write_raw_json(raw_data, label=f"admin_{level}{label_suffix}")

        features = _parse_overpass_to_features(
            raw_data, extra_props={"admin_level": level}
        )
        logger.info(
            "Parsed %d admin boundary features for level=%s", len(features), level
        )
        all_features.extend(features)

    if not all_features:
        logger.warning("No admin boundary features parsed; skipping GeoJSON write.")
        return

    geojson_doc = {"type": "FeatureCollection", "features": all_features}
    ADMIN_BOUNDARIES_PATH.write_text(
        json.dumps(geojson_doc, ensure_ascii=False), encoding="utf-8"
    )
    logger.info(
        "Admin boundaries written to %s (%d features).",
        ADMIN_BOUNDARIES_PATH,
        len(all_features),
    )


def upsert_zone(db: Session, feature: dict, zone_type: str) -> Zone:
    """Insert a new Zone row or update geometry/name for an existing one by osm_id.

    osm_id is the stable OSM identifier used as the upsert key so that
    refreshes never wipe and reinsert the whole table (data-model.md s Zone).

    Args:
        db:        SQLAlchemy session; caller commits.
        feature:   GeoJSON-like Feature dict with 'properties' and 'geometry'.
        zone_type: One of 'industrial' | 'forest' | 'farmland'.

    Returns:
        The inserted or updated Zone ORM object (not yet committed).
    """
    props = feature.get("properties", {})
    osm_id: str | None = props.get("osm_id")
    name: str | None = props.get("name") or None
    geometry_wkt: str = _geometry_to_wkt(feature["geometry"])

    existing: Zone | None = None
    if osm_id is not None:
        existing = db.query(Zone).filter(Zone.osm_id == osm_id).first()

    if existing is not None:
        existing.geometry = geometry_wkt
        existing.name = name
        logger.debug("Updated Zone osm_id=%s zone_type=%s", osm_id, zone_type)
        return existing

    zone = Zone(
        osm_id=osm_id,
        zone_type=zone_type,
        name=name,
        geometry=geometry_wkt,
        source="osm",
    )
    db.add(zone)
    logger.debug("Inserted Zone osm_id=%s zone_type=%s", osm_id, zone_type)
    return zone


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_overpass(query: str, label: str) -> dict:
    """POST a query to Overpass and return the parsed JSON response.

    Retries up to _MAX_RETRIES times with exponential back-off on timeout or
    rate-limit (HTTP 429 / 504).  Raises requests.RequestException after all
    retries are exhausted.

    Args:
        query: The full Overpass QL query string.
        label: A short identifier used in log messages.
    """
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info(
                "Overpass request attempt %d/%d for %s", attempt, _MAX_RETRIES, label
            )
            user_agent = settings.NOMINATIM_USER_AGENT or "SIH26162-FireDetection/1.0"
            response = requests.post(
                _OVERPASS_URL,
                data={"data": query},
                timeout=_OVERPASS_TIMEOUT + 30,
                headers={"User-Agent": user_agent, "Accept-Charset": "utf-8"},
            )
        except requests.Timeout:
            logger.warning(
                "Overpass timeout on attempt %d/%d for %s.", attempt, _MAX_RETRIES, label
            )
            _backoff(attempt)
            continue
        except requests.RequestException as exc:
            logger.error("Overpass network error for %s: %s", label, exc)
            _backoff(attempt)
            continue

        if response.status_code in (429, 504):
            logger.warning(
                "Overpass returned HTTP %s (rate-limit/gateway timeout) for %s, "
                "attempt %d/%d.",
                response.status_code,
                label,
                attempt,
                _MAX_RETRIES,
            )
            _backoff(attempt)
            continue

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            logger.error(
                "Overpass HTTP error for %s: %s -- %s",
                label,
                exc,
                response.text[:200],
            )
            raise

        try:
            return response.json()
        except ValueError as exc:
            logger.error(
                "Failed to parse Overpass JSON for %s: %s. "
                "Response text (first 200): %s",
                label,
                exc,
                response.text[:200],
            )
            raise

    raise requests.RequestException(
        f"Overpass request for '{label}' failed after {_MAX_RETRIES} attempts."
    )


def _backoff(attempt: int) -> None:
    """Sleep for an exponentially increasing duration between retry attempts."""
    delay = _RETRY_BACKOFF_BASE_S * (2 ** (attempt - 1))
    logger.info("Backing off for %ds before next Overpass attempt.", delay)
    time.sleep(delay)


def _parse_overpass_to_features(
    raw_data: dict, extra_props: dict | None = None
) -> list[dict]:
    """Convert a raw Overpass JSON response to a list of GeoJSON-like Feature dicts.

    Only closed ways and relations with a resolvable polygon geometry are
    included -- open ways (e.g. road segments) are silently skipped.

    Args:
        raw_data:    Parsed Overpass JSON as returned by _fetch_overpass.
        extra_props: Optional extra key-value pairs merged into each feature's
                     properties (e.g. {'admin_level': 'states'}).

    Returns:
        List of GeoJSON-like Feature dicts, each with 'type', 'geometry',
        and 'properties' (including 'osm_id', 'osm_type', 'name').
    """
    extra_props = extra_props or {}
    elements: list[dict] = raw_data.get("elements", [])

    # Build a node_id -> (lon, lat) lookup for assembling way geometries.
    nodes: dict[int, tuple[float, float]] = {}
    for el in elements:
        if el.get("type") == "node" and "lat" in el and "lon" in el:
            nodes[el["id"]] = (el["lon"], el["lat"])

    features: list[dict] = []

    for el in elements:
        el_type = el.get("type")
        osm_id = f"{el_type}/{el['id']}"
        tags: dict = el.get("tags", {})
        name: str | None = tags.get("name")

        geometry: dict | None = None

        if el_type == "way":
            coords = [nodes[nid] for nid in el.get("nodes", []) if nid in nodes]
            if len(coords) >= 4 and coords[0] == coords[-1]:
                geometry = {"type": "Polygon", "coordinates": [coords]}

        elif el_type == "relation":
            outer_coords = _assemble_relation_ring(el, nodes)
            if outer_coords and len(outer_coords) >= 4:
                geometry = {"type": "Polygon", "coordinates": [outer_coords]}

        if geometry is None:
            continue

        try:
            geom_obj = shape(geometry)
            if not geom_obj.is_valid or geom_obj.is_empty:
                logger.debug("Skipping invalid/empty geometry for %s", osm_id)
                continue
        except Exception:  # noqa: BLE001
            logger.debug("Skipping unparseable geometry for %s", osm_id)
            continue

        props = {"osm_id": osm_id, "osm_type": el_type, "name": name}
        props.update(extra_props)

        features.append(
            {"type": "Feature", "geometry": geometry, "properties": props}
        )

    return features


def _assemble_relation_ring(
    relation: dict, nodes: dict[int, tuple[float, float]]
) -> list[tuple[float, float]]:
    """Assemble the outer ring of a relation from its outer-role member ways.

    Returns an empty list if the ring cannot be assembled.  This is a
    best-effort linear assembly -- sufficient for the classification
    spatial-join use case (RULES.md s4: prefer obviously-correct over clever).
    """
    outer_ways: list[list[tuple[float, float]]] = []
    for member in relation.get("members", []):
        if member.get("type") != "way" or member.get("role") != "outer":
            continue
        way_nodes = member.get("geometry", [])
        if way_nodes:
            coords = [(n["lon"], n["lat"]) for n in way_nodes if "lon" in n]
        else:
            coords = [nodes[nid] for nid in member.get("nodes", []) if nid in nodes]

        if len(coords) >= 2:
            outer_ways.append(coords)

    if not outer_ways:
        return []

    ring: list[tuple[float, float]] = list(outer_ways[0])
    remaining = outer_ways[1:]

    for _ in range(len(remaining) * 2):
        if not remaining:
            break
        last = ring[-1]
        for i, seg in enumerate(remaining):
            if seg[0] == last:
                ring.extend(seg[1:])
                remaining.pop(i)
                break
            elif seg[-1] == last:
                ring.extend(reversed(seg[:-1]))
                remaining.pop(i)
                break

    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])

    return ring


def _geometry_to_wkt(geometry: dict) -> str:
    """Convert a GeoJSON geometry dict to WKT via shapely."""
    return shape(geometry).wkt


def _write_raw_json(data: dict, label: str) -> None:
    """Write the untouched Overpass JSON response to data/raw/ (RULES.md s6)."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = _RAW_DIR / f"osm_{label}_{timestamp}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    logger.debug("Raw Overpass response written to %s", path)


def _write_processed_geojson(features: list[dict], label: str) -> None:
    """Write normalised GeoJSON features to data/processed/ (RULES.md s6)."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = _PROCESSED_DIR / f"osm_{label}_{timestamp}.geojson"
    geojson_doc = {"type": "FeatureCollection", "features": features}
    path.write_text(json.dumps(geojson_doc, ensure_ascii=False), encoding="utf-8")
    logger.debug("Processed GeoJSON written to %s", path)
