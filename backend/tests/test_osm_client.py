"""
Tests for app.services.osm_client.

Covers the unit-testable pure functions -- geometry parsing, relation ring
assembly, and upsert behaviour.  No network calls are made; _fetch_overpass is
either not exercised or patched via monkeypatch/unittest.mock.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from shapely import wkt as shapely_wkt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.database import Base
from app.models import Zone
from app.services.osm_client import (
    _assemble_relation_ring,
    _geometry_to_wkt,
    _parse_overpass_to_features,
    fetch_and_cache_admin_boundaries,
    upsert_zone,
    ADMIN_BOUNDARIES_PATH,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_session() -> Session:
    """In-memory SQLite session for isolated upsert tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# _geometry_to_wkt
# ---------------------------------------------------------------------------

class TestGeometryToWkt:
    def test_simple_polygon_roundtrips(self) -> None:
        geometry = {
            "type": "Polygon",
            "coordinates": [[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 0.0)]],
        }
        wkt = _geometry_to_wkt(geometry)
        assert wkt.startswith("POLYGON")
        # Shapely should be able to re-parse its own WKT.
        geom_obj = shapely_wkt.loads(wkt)
        assert not geom_obj.is_empty

    def test_invalid_geometry_raises(self) -> None:
        with pytest.raises(Exception):
            _geometry_to_wkt({"type": "NotAType", "coordinates": []})


# ---------------------------------------------------------------------------
# _assemble_relation_ring
# ---------------------------------------------------------------------------

class TestAssembleRelationRing:
    def _make_relation(self, member_segments: list[list[tuple[float, float]]]) -> dict:
        """Build a fake relation dict whose outer members have inline geometry."""
        members = []
        for seg in member_segments:
            members.append({
                "type": "way",
                "role": "outer",
                "geometry": [{"lon": lon, "lat": lat} for lon, lat in seg],
            })
        return {"members": members}

    def test_single_closed_way_returns_ring(self) -> None:
        ring_coords = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
        relation = self._make_relation([ring_coords])
        result = _assemble_relation_ring(relation, nodes={})
        assert result[0] == result[-1], "Ring should be closed"
        assert len(result) >= 4

    def test_two_segments_are_chained(self) -> None:
        seg1 = [(0.0, 0.0), (1.0, 0.0)]
        seg2 = [(1.0, 0.0), (2.0, 0.0), (1.0, 1.0), (0.0, 0.0)]
        relation = self._make_relation([seg1, seg2])
        result = _assemble_relation_ring(relation, nodes={})
        assert len(result) >= 4
        assert result[0] == result[-1]

    def test_no_outer_members_returns_empty(self) -> None:
        relation = {"members": [{"type": "way", "role": "inner", "geometry": []}]}
        result = _assemble_relation_ring(relation, nodes={})
        assert result == []

    def test_empty_relation_returns_empty(self) -> None:
        result = _assemble_relation_ring({"members": []}, nodes={})
        assert result == []


# ---------------------------------------------------------------------------
# _parse_overpass_to_features
# ---------------------------------------------------------------------------

class TestParseOverpassToFeatures:
    def _closed_way(self, way_id: int, node_ids: list[int]) -> dict:
        return {"type": "way", "id": way_id, "nodes": node_ids, "tags": {"name": "TestZone"}}

    def _node(self, node_id: int, lon: float, lat: float) -> dict:
        return {"type": "node", "id": node_id, "lon": lon, "lat": lat}

    def _minimal_valid_response(self) -> dict:
        # A closed square way with 5 node refs (first == last).
        node_ids = [1, 2, 3, 4, 1]
        return {
            "elements": [
                self._node(1, 77.0, 28.0),
                self._node(2, 78.0, 28.0),
                self._node(3, 78.0, 29.0),
                self._node(4, 77.0, 29.0),
                self._closed_way(101, node_ids),
            ]
        }

    def test_closed_way_becomes_feature(self) -> None:
        raw = self._minimal_valid_response()
        features = _parse_overpass_to_features(raw)
        assert len(features) == 1
        f = features[0]
        assert f["type"] == "Feature"
        assert f["geometry"]["type"] == "Polygon"
        assert f["properties"]["osm_id"] == "way/101"
        assert f["properties"]["name"] == "TestZone"

    def test_open_way_is_skipped(self) -> None:
        """A way whose first and last node_id differ is not a closed polygon."""
        raw = {
            "elements": [
                self._node(1, 77.0, 28.0),
                self._node(2, 78.0, 28.0),
                {"type": "way", "id": 200, "nodes": [1, 2], "tags": {}},
            ]
        }
        features = _parse_overpass_to_features(raw)
        assert features == []

    def test_extra_props_are_merged(self) -> None:
        raw = self._minimal_valid_response()
        features = _parse_overpass_to_features(raw, extra_props={"admin_level": "states"})
        assert features[0]["properties"]["admin_level"] == "states"

    def test_empty_response_returns_empty_list(self) -> None:
        assert _parse_overpass_to_features({"elements": []}) == []


# ---------------------------------------------------------------------------
# upsert_zone
# ---------------------------------------------------------------------------

class TestUpsertZone:
    def _square_feature(self, osm_id: str, name: str | None = None) -> dict:
        return {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [(77.0, 28.0), (78.0, 28.0), (78.0, 29.0), (77.0, 29.0), (77.0, 28.0)]
                ],
            },
            "properties": {"osm_id": osm_id, "name": name},
        }

    def test_inserts_new_zone(self, db_session: Session) -> None:
        feat = self._square_feature("way/100", name="TestIndustrial")
        zone = upsert_zone(db_session, feat, "industrial")
        db_session.flush()

        assert zone.osm_id == "way/100"
        assert zone.zone_type == "industrial"
        assert zone.name == "TestIndustrial"
        assert zone.source == "osm"
        assert zone.geometry.startswith("POLYGON")

    def test_updates_existing_zone_by_osm_id(self, db_session: Session) -> None:
        feat = self._square_feature("way/200")
        upsert_zone(db_session, feat, "forest")
        db_session.flush()

        # Update with a different name -- should update the existing row.
        feat2 = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [(77.0, 28.0), (79.0, 28.0), (79.0, 30.0), (77.0, 30.0), (77.0, 28.0)]
                ],
            },
            "properties": {"osm_id": "way/200", "name": "UpdatedForest"},
        }
        zone2 = upsert_zone(db_session, feat2, "forest")
        db_session.flush()

        rows = db_session.query(Zone).filter(Zone.osm_id == "way/200").all()
        assert len(rows) == 1, "Should not insert a duplicate; must update the existing row"
        assert rows[0].name == "UpdatedForest"

    def test_zone_type_enum_values_accepted(self, db_session: Session) -> None:
        """All three canonical zone_type values (data-model.md) must be accepted."""
        for i, zt in enumerate(["industrial", "forest", "farmland"]):
            feat = self._square_feature(f"way/{i}")
            zone = upsert_zone(db_session, feat, zt)
            db_session.flush()
            assert zone.zone_type == zt

    def test_null_osm_id_always_inserts(self, db_session: Session) -> None:
        """Features without an osm_id (unusual but possible) are always inserted."""
        feat = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [(77.0, 28.0), (78.0, 28.0), (78.0, 29.0), (77.0, 29.0), (77.0, 28.0)]
                ],
            },
            "properties": {"osm_id": None, "name": None},
        }
        upsert_zone(db_session, feat, "industrial")
        upsert_zone(db_session, feat, "industrial")
        db_session.flush()
        count = db_session.query(Zone).filter(Zone.osm_id.is_(None)).count()
        assert count == 2


# ---------------------------------------------------------------------------
# fetch_and_cache_admin_boundaries -- file output check
# ---------------------------------------------------------------------------

class TestFetchAndCacheAdminBoundaries:
    """Patches _fetch_overpass so no network call is made."""

    def _fake_overpass_response(self) -> dict:
        """Minimal response that produces one valid polygon feature."""
        return {
            "elements": [
                {"type": "node", "id": 1, "lon": 77.0, "lat": 28.0},
                {"type": "node", "id": 2, "lon": 78.0, "lat": 28.0},
                {"type": "node", "id": 3, "lon": 78.0, "lat": 29.0},
                {"type": "node", "id": 4, "lon": 77.0, "lat": 29.0},
                {
                    "type": "relation",
                    "id": 999,
                    "tags": {"name": "TestState", "admin_level": "4"},
                    "members": [
                        {
                            "type": "way",
                            "role": "outer",
                            "geometry": [
                                {"lon": 77.0, "lat": 28.0},
                                {"lon": 78.0, "lat": 28.0},
                                {"lon": 78.0, "lat": 29.0},
                                {"lon": 77.0, "lat": 29.0},
                                {"lon": 77.0, "lat": 28.0},
                            ],
                        }
                    ],
                },
            ]
        }

    def test_writes_geojson_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.services.osm_client as osm_mod

        # Redirect the output path to tmp_path so the test is self-contained.
        monkeypatch.setattr(osm_mod, "ADMIN_BOUNDARIES_PATH", tmp_path / "admin_boundaries.geojson")
        monkeypatch.setattr(osm_mod, "_RAW_DIR", tmp_path / "raw")
        monkeypatch.setattr(osm_mod, "_PROCESSED_DIR", tmp_path / "processed")

        fake_resp = self._fake_overpass_response()
        monkeypatch.setattr(osm_mod, "_fetch_overpass", lambda query, label: fake_resp)

        osm_mod.fetch_and_cache_admin_boundaries()

        out = tmp_path / "admin_boundaries.geojson"
        assert out.exists(), "GeoJSON file must be written"

        doc = json.loads(out.read_text(encoding="utf-8"))
        assert doc["type"] == "FeatureCollection"
        # At least one feature from the two queries (states + districts both return
        # the same fake response in this test).
        assert len(doc["features"]) >= 1

    def test_no_file_written_when_no_features(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.services.osm_client as osm_mod

        monkeypatch.setattr(osm_mod, "ADMIN_BOUNDARIES_PATH", tmp_path / "admin_boundaries.geojson")
        monkeypatch.setattr(osm_mod, "_RAW_DIR", tmp_path / "raw")
        monkeypatch.setattr(osm_mod, "_PROCESSED_DIR", tmp_path / "processed")
        monkeypatch.setattr(osm_mod, "_fetch_overpass", lambda query, label: {"elements": []})

        osm_mod.fetch_and_cache_admin_boundaries()

        assert not (tmp_path / "admin_boundaries.geojson").exists()
