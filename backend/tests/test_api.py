"""
Comprehensive tests for the prototype API routers (Phase 5).
Covers health, zones, fires, flags, stats, main lifespan, and error handling.
"""

import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import DataMode, settings
from app.database import Base, get_db
from app.main import app, lifespan
from app.models import FireDetection, FlaggedCase, PersistentSource, Zone

# In-memory test SQLite database engine with StaticPool for thread-safe test isolation
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=test_engine
)


@pytest.fixture(autouse=True)
def setup_test_db():
    """Create fresh database schema for each test function and tear down after."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture()
def db_session():
    """Yield an active test database session."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session: Session):
    """
    TestClient with get_db overridden to use test database session.
    Also patches app.main.SessionLocal during lifespan so startup pipeline
    runs against the test database.
    """

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with patch("app.main.SessionLocal", TestingSessionLocal):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
    app.dependency_overrides.clear()


# ===========================================================================
# 1. Health Router Tests
# ===========================================================================


class TestHealthRouter:
    def test_health_ok_and_live_mode(self, client: TestClient):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["mode"] == settings.DATA_MODE.value

    def test_health_reflects_changed_mode(self, client: TestClient):
        original_mode = settings.DATA_MODE
        try:
            settings.DATA_MODE = DataMode.live
            response = client.get("/api/health")
            assert response.status_code == 200
            assert response.json()["mode"] == "live"
        finally:
            settings.DATA_MODE = original_mode


# ===========================================================================
# 2. Zones Router Tests
# ===========================================================================


class TestZonesRouter:
    def test_get_all_zones_bare_array(
        self, client: TestClient, db_session: Session
    ):
        z1 = Zone(
            zone_type="industrial",
            name="Plant 1",
            geometry="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        )
        z2 = Zone(
            zone_type="forest",
            name="Forest Reserve",
            geometry="POLYGON((2 2, 3 2, 3 3, 2 3, 2 2))",
        )
        db_session.add_all([z1, z2])
        db_session.commit()

        response = client.get("/api/zones")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)  # Bare array
        assert len(data) == 2
        names = {z["name"] for z in data}
        assert names == {"Plant 1", "Forest Reserve"}

    def test_filter_zones_by_type(
        self, client: TestClient, db_session: Session
    ):
        z1 = Zone(
            zone_type="industrial",
            name="Plant 1",
            geometry="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        )
        z2 = Zone(
            zone_type="forest",
            name="Forest Reserve",
            geometry="POLYGON((2 2, 3 2, 3 3, 2 3, 2 2))",
        )
        db_session.add_all([z1, z2])
        db_session.commit()

        response = client.get("/api/zones?zone_type=industrial")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["zone_type"] == "industrial"
        assert data[0]["name"] == "Plant 1"

    def test_unrecognized_zone_type_returns_empty_array(
        self, client: TestClient, db_session: Session
    ):
        z = Zone(
            zone_type="industrial",
            name="Plant 1",
            geometry="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        )
        db_session.add(z)
        db_session.commit()

        response = client.get("/api/zones?zone_type=nonexistent_zone")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert data == []


# ===========================================================================
# 3. Fires Router Tests
# ===========================================================================


class TestFiresRouter:
    def _create_fire(
        self,
        db: Session,
        fire_type: str = "wildfire",
        state: str | None = "Gujarat",
        acq_date: datetime.date = datetime.date(2025, 1, 1),
        confidence: str = "n",
        is_persistent: bool = False,
    ) -> FireDetection:
        fire = FireDetection(
            latitude=22.5,
            longitude=71.2,
            brightness=320.0,
            frp=15.0,
            acq_date=acq_date,
            acq_time="1200",
            daynight="d",
            satellite="snpp",
            confidence=confidence,
            fire_type=fire_type,
            state=state,
            district="Rajkot",
            cluster_id=None,
            is_persistent=is_persistent,
        )
        db.add(fire)
        db.commit()
        db.refresh(fire)
        return fire

    def test_fires_bare_array_and_limit_cap(
        self, client: TestClient, db_session: Session
    ):
        for i in range(5):
            self._create_fire(db_session, acq_date=datetime.date(2025, 1, i + 1))

        response = client.get("/api/fires?limit=2")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)  # Bare array, no pagination envelope
        assert len(data) == 2

    def test_pending_never_returned_in_list(
        self, client: TestClient, db_session: Session
    ):
        self._create_fire(db_session, fire_type="pending")
        classified = self._create_fire(db_session, fire_type="industrial")

        response = client.get("/api/fires")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == classified.id
        assert data[0]["fire_type"] == "industrial"

    def test_pending_filter_param_returns_empty(
        self, client: TestClient, db_session: Session
    ):
        self._create_fire(db_session, fire_type="pending")
        self._create_fire(db_session, fire_type="wildfire")

        response = client.get("/api/fires?fire_type=pending")
        assert response.status_code == 200
        assert response.json() == []

    def test_pending_detail_returns_404(
        self, client: TestClient, db_session: Session
    ):
        pending = self._create_fire(db_session, fire_type="pending")
        response = client.get(f"/api/fires/{pending.id}")
        assert response.status_code == 404
        assert response.json()["detail"] == "Fire detection not found"

    def test_fire_detail_found_and_not_found(
        self, client: TestClient, db_session: Session
    ):
        fire = self._create_fire(db_session, fire_type="agricultural")
        response = client.get(f"/api/fires/{fire.id}")
        assert response.status_code == 200
        assert response.json()["id"] == fire.id
        assert response.json()["fire_type"] == "agricultural"

        missing_resp = client.get("/api/fires/999999")
        assert missing_resp.status_code == 404

    def test_date_range_inclusive(
        self, client: TestClient, db_session: Session
    ):
        f1 = self._create_fire(db_session, acq_date=datetime.date(2025, 1, 1))
        f2 = self._create_fire(db_session, acq_date=datetime.date(2025, 1, 2))
        f3 = self._create_fire(db_session, acq_date=datetime.date(2025, 1, 3))

        # date_from and date_to inclusive on both ends
        response = client.get("/api/fires?date_from=2025-01-01&date_to=2025-01-02")
        assert response.status_code == 200
        ids = {f["id"] for f in response.json()}
        assert ids == {f1.id, f2.id}

    def test_date_from_greater_than_date_to_returns_empty(
        self, client: TestClient, db_session: Session
    ):
        self._create_fire(db_session, acq_date=datetime.date(2025, 1, 2))
        response = client.get("/api/fires?date_from=2025-01-05&date_to=2025-01-02")
        assert response.status_code == 200
        assert response.json() == []

    def test_ordinal_confidence_filtering(
        self, client: TestClient, db_session: Session
    ):
        f_low = self._create_fire(db_session, confidence="l")
        f_nom = self._create_fire(db_session, confidence="n")
        f_high = self._create_fire(db_session, confidence="h")

        # min_confidence='l' returns all three
        resp_l = client.get("/api/fires?min_confidence=l")
        assert resp_l.status_code == 200
        assert len(resp_l.json()) == 3

        # min_confidence='n' returns 'n' and 'h' (ordinal check: 'l' < 'n' < 'h')
        resp_n = client.get("/api/fires?min_confidence=n")
        assert resp_n.status_code == 200
        ids_n = {f["id"] for f in resp_n.json()}
        assert ids_n == {f_nom.id, f_high.id}

        # min_confidence='h' returns only 'h'
        resp_h = client.get("/api/fires?min_confidence=h")
        assert resp_h.status_code == 200
        ids_h = {f["id"] for f in resp_h.json()}
        assert ids_h == {f_high.id}

        # unrecognized confidence returns empty
        resp_inv = client.get("/api/fires?min_confidence=invalid")
        assert resp_inv.status_code == 200
        assert resp_inv.json() == []

    def test_is_persistent_boolean_parsing(
        self, client: TestClient, db_session: Session
    ):
        f_pers = self._create_fire(db_session, is_persistent=True)
        f_trans = self._create_fire(db_session, is_persistent=False)

        resp_true = client.get("/api/fires?is_persistent=true")
        assert resp_true.status_code == 200
        assert len(resp_true.json()) == 1
        assert resp_true.json()[0]["id"] == f_pers.id

        resp_false = client.get("/api/fires?is_persistent=false")
        assert resp_false.status_code == 200
        assert len(resp_false.json()) == 1
        assert resp_false.json()[0]["id"] == f_trans.id

    def test_state_filtering_and_null_state_handling(
        self, client: TestClient, db_session: Session
    ):
        f_guj = self._create_fire(db_session, state="Gujarat")
        f_raj = self._create_fire(db_session, state="Rajasthan")
        f_null = self._create_fire(db_session, state=None)

        # Filtered by state: exact match, NULL state excluded
        resp_guj = client.get("/api/fires?state=Gujarat")
        assert resp_guj.status_code == 200
        assert len(resp_guj.json()) == 1
        assert resp_guj.json()[0]["id"] == f_guj.id

        # Case sensitive check
        resp_case = client.get("/api/fires?state=gujarat")
        assert resp_case.status_code == 200
        assert resp_case.json() == []

        # Unfiltered: includes all, including NULL state
        resp_all = client.get("/api/fires")
        assert resp_all.status_code == 200
        assert len(resp_all.json()) == 3


# ===========================================================================
# 4. Flags Router Tests
# ===========================================================================


class TestFlagsRouter:
    def _create_flag(
        self,
        db: Session,
        status: str = "open",
        cluster_id: int = 101,
    ) -> FlaggedCase:
        ps = PersistentSource(
            cluster_id=cluster_id,
            centroid_latitude=23.0,
            centroid_longitude=72.0,
            first_seen=datetime.date(2025, 1, 1),
            last_seen=datetime.date(2025, 1, 5),
            days_active=5,
            member_count=4,
            zone_type_at_location=None,
            status="active",
        )
        db.add(ps)
        db.commit()
        db.refresh(ps)

        flag = FlaggedCase(
            persistent_source_id=ps.id,
            anomaly_score=0.88,
            nearest_zone_type="industrial",
            nearest_zone_distance_m=1250.0,
            status=status,
            case_note="Potential unmapped facility",
        )
        db.add(flag)
        db.commit()
        db.refresh(flag)
        return flag

    def test_flags_list_defaults_to_open(
        self, client: TestClient, db_session: Session
    ):
        flag_open = self._create_flag(db_session, status="open", cluster_id=1)
        flag_rev = self._create_flag(db_session, status="reviewed", cluster_id=2)

        response = client.get("/api/flags")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == flag_open.id
        assert data[0]["status"] == "open"
        # Linked PersistentSource summary embedded
        assert data[0]["persistent_source"]["id"] == flag_open.persistent_source_id
        assert data[0]["persistent_source"]["days_active"] == 5

    def test_flags_list_custom_status(
        self, client: TestClient, db_session: Session
    ):
        self._create_flag(db_session, status="open", cluster_id=1)
        flag_rev = self._create_flag(db_session, status="reviewed", cluster_id=2)

        response = client.get("/api/flags?status=reviewed")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == flag_rev.id
        assert data[0]["status"] == "reviewed"

    def test_flag_detail_with_member_detections(
        self, client: TestClient, db_session: Session
    ):
        flag = self._create_flag(db_session, status="open", cluster_id=50)

        # Seed member detections with matching cluster_id
        f1 = FireDetection(
            latitude=23.01,
            longitude=72.01,
            brightness=330.0,
            frp=20.0,
            acq_date=datetime.date(2025, 1, 1),
            acq_time="1000",
            daynight="d",
            satellite="snpp",
            confidence="n",
            fire_type="unclassified",
            state="Gujarat",
            district="Ahmedabad",
            cluster_id=50,
            is_persistent=True,
        )
        f2 = FireDetection(
            latitude=23.02,
            longitude=72.02,
            brightness=335.0,
            frp=25.0,
            acq_date=datetime.date(2025, 1, 2),
            acq_time="1010",
            daynight="d",
            satellite="snpp",
            confidence="h",
            fire_type="unclassified",
            state="Gujarat",
            district="Ahmedabad",
            cluster_id=50,
            is_persistent=True,
        )
        db_session.add_all([f1, f2])
        db_session.commit()

        response = client.get(f"/api/flags/{flag.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == flag.id
        assert data["persistent_source"]["id"] == flag.persistent_source_id
        assert len(data["member_detections"]) == 2
        member_ids = {m["id"] for m in data["member_detections"]}
        assert member_ids == {f1.id, f2.id}

    def test_flag_detail_not_found(self, client: TestClient):
        response = client.get("/api/flags/999999")
        assert response.status_code == 404
        assert response.json()["detail"] == "Flagged case not found"

    def test_flags_read_only_endpoints(self, client: TestClient):
        # PATCH and export are omitted for prototype
        resp_patch = client.patch("/api/flags/1", json={"status": "reviewed"})
        assert resp_patch.status_code in (404, 405)

        # /api/flags/export does not exist; matches /api/flags/{flag_id: int} resulting in 422
        resp_export = client.get("/api/flags/export")
        assert resp_export.status_code in (404, 405, 422)


# ===========================================================================
# 5. Stats Router Tests
# ===========================================================================


class TestStatsRouter:
    def test_empty_database_returns_all_zeros(self, client: TestClient):
        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert data == {
            "total_fires": 0,
            "by_type": {},
            "by_state": {},
            "persistent_active_count": 0,
            "persistent_ended_count": 0,
            "flagged_open_count": 0,
        }
        # Verify trend field is omitted
        assert "trend" not in data

    def test_populated_stats_and_pending_exclusion(
        self, client: TestClient, db_session: Session
    ):
        # 1 industrial (Gujarat), 1 wildfire (Rajasthan), 1 pending (Gujarat)
        f_ind = FireDetection(
            latitude=22.0,
            longitude=71.0,
            brightness=310.0,
            frp=10.0,
            acq_date=datetime.date(2025, 1, 1),
            acq_time="1000",
            daynight="d",
            satellite="snpp",
            confidence="n",
            fire_type="industrial",
            state="Gujarat",
            district="Surat",
            is_persistent=False,
        )
        f_wild = FireDetection(
            latitude=25.0,
            longitude=73.0,
            brightness=320.0,
            frp=12.0,
            acq_date=datetime.date(2025, 1, 2),
            acq_time="1000",
            daynight="d",
            satellite="snpp",
            confidence="h",
            fire_type="wildfire",
            state="Rajasthan",
            district="Udaipur",
            is_persistent=False,
        )
        f_pend = FireDetection(
            latitude=22.5,
            longitude=71.5,
            brightness=300.0,
            frp=8.0,
            acq_date=datetime.date(2025, 1, 3),
            acq_time="1000",
            daynight="d",
            satellite="snpp",
            confidence="l",
            fire_type="pending",
            state="Gujarat",
            district="Rajkot",
            is_persistent=False,
        )
        db_session.add_all([f_ind, f_wild, f_pend])

        # PersistentSources: 1 active, 1 ended
        ps1 = PersistentSource(
            cluster_id=1,
            centroid_latitude=22.0,
            centroid_longitude=71.0,
            first_seen=datetime.date(2025, 1, 1),
            last_seen=datetime.date(2025, 1, 5),
            days_active=5,
            member_count=3,
            status="active",
        )
        ps2 = PersistentSource(
            cluster_id=2,
            centroid_latitude=23.0,
            centroid_longitude=72.0,
            first_seen=datetime.date(2024, 12, 1),
            last_seen=datetime.date(2024, 12, 5),
            days_active=5,
            member_count=4,
            status="ended",
        )
        db_session.add_all([ps1, ps2])
        db_session.flush()

        # FlaggedCase: 1 open
        fc = FlaggedCase(
            persistent_source_id=ps1.id,
            anomaly_score=0.9,
            nearest_zone_type="industrial",
            nearest_zone_distance_m=800.0,
            status="open",
        )
        db_session.add(fc)
        db_session.commit()

        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_fires"] == 2  # Pending excluded!
        assert data["by_type"] == {"industrial": 1, "wildfire": 1}
        assert data["by_state"] == {"Gujarat": 1, "Rajasthan": 1}
        assert data["persistent_active_count"] == 1
        assert data["persistent_ended_count"] == 1
        assert data["flagged_open_count"] == 1
        assert "trend" not in data

    def test_stats_filters(self, client: TestClient, db_session: Session):
        f1 = FireDetection(
            latitude=22.0,
            longitude=71.0,
            brightness=310.0,
            frp=10.0,
            acq_date=datetime.date(2025, 1, 1),
            acq_time="1000",
            daynight="d",
            satellite="snpp",
            confidence="n",
            fire_type="industrial",
            state="Gujarat",
            is_persistent=False,
        )
        f2 = FireDetection(
            latitude=25.0,
            longitude=73.0,
            brightness=320.0,
            frp=12.0,
            acq_date=datetime.date(2025, 1, 2),
            acq_time="1000",
            daynight="d",
            satellite="snpp",
            confidence="h",
            fire_type="wildfire",
            state="Rajasthan",
            is_persistent=False,
        )
        db_session.add_all([f1, f2])
        db_session.commit()

        # Filter by state
        resp_state = client.get("/api/stats?state=Gujarat")
        assert resp_state.status_code == 200
        data = resp_state.json()
        assert data["total_fires"] == 1
        assert data["by_type"] == {"industrial": 1}
        assert data["by_state"] == {"Gujarat": 1}

        # Date range where date_from > date_to returns zeros for fires
        resp_inv_date = client.get("/api/stats?date_from=2025-01-05&date_to=2025-01-01")
        assert resp_inv_date.status_code == 200
        data_inv = resp_inv_date.json()
        assert data_inv["total_fires"] == 0
        assert data_inv["by_type"] == {}
        assert data_inv["by_state"] == {}


# ===========================================================================
# 6. Main Lifespan and Global Error Handling Tests
# ===========================================================================


class TestMainLifespanAndErrorHandling:
    @pytest.mark.anyio
    async def test_lifespan_model_file_not_found_continues(self):
        """Missing artifact file: log clearly and continue startup."""
        with patch("app.main.infer.load_model", side_effect=FileNotFoundError("missing artifact")):
            with patch("app.main.SessionLocal", TestingSessionLocal):
                with patch("app.main.classify_fires", return_value=0):
                    with patch("app.main.run_persistence", return_value=0):
                        with patch("app.main.run_flagging", return_value=0):
                            async with lifespan(app):
                                pass  # Startup must succeed without raising

    @pytest.mark.anyio
    async def test_lifespan_model_malformed_fails_loudly(self):
        """Malformed artifact (KeyError): propagates and terminates startup."""
        with patch("app.main.infer.load_model", side_effect=KeyError("feature_columns")):
            with pytest.raises(KeyError, match="feature_columns"):
                async with lifespan(app):
                    pass

    @pytest.mark.anyio
    async def test_lifespan_pipeline_failure_fails_loudly(self):
        """If any of classify/persistence/flagging raises, startup fails loudly."""
        with patch("app.main.infer.load_model", return_value=None):
            with patch("app.main.SessionLocal", TestingSessionLocal):
                with patch("app.main.classify_fires", side_effect=RuntimeError("pipeline failed")):
                    with pytest.raises(RuntimeError, match="pipeline failed"):
                        async with lifespan(app):
                            pass

    def test_startup_with_missing_model_skips_flagging_and_serves_fires(
        self, caplog: pytest.LogCaptureFixture
    ):
        """
        Simulate a missing model artifact (FileNotFoundError):
        - App starts successfully.
        - classify_fires and run_persistence run unconditionally.
        - run_flagging is skipped with a logged warning.
        - GET /api/fires returns the real classified data.
        - GET /api/flags is empty.
        """
        # Pre-seed DB with a zone and a pending fire
        setup_session = TestingSessionLocal()
        zone = Zone(
            zone_type="industrial",
            name="Refinery Zone",
            geometry="POLYGON((70.0 20.0, 75.0 20.0, 75.0 25.0, 70.0 25.0, 70.0 20.0))",
        )
        pending_fire = FireDetection(
            latitude=22.5,
            longitude=71.2,
            brightness=340.0,
            frp=20.0,
            acq_date=datetime.date(2025, 1, 1),
            acq_time="1100",
            daynight="d",
            satellite="snpp",
            confidence="h",
            fire_type="pending",  # Starts pending
            state="Gujarat",
            district="Jamnagar",
            is_persistent=False,
        )
        setup_session.add_all([zone, pending_fire])
        setup_session.commit()
        setup_session.close()

        def override_get_db():
            s = TestingSessionLocal()
            try:
                yield s
            finally:
                s.close()

        app.dependency_overrides[get_db] = override_get_db
        try:
            with patch(
                "app.main.infer.load_model",
                side_effect=FileNotFoundError("Mocked missing artifact.pkl"),
            ):
                with patch("app.main.SessionLocal", TestingSessionLocal):
                    with patch("app.main.run_flagging") as mock_flagging:
                        import logging

                        with caplog.at_level(logging.WARNING):
                            with TestClient(app, raise_server_exceptions=False) as c:
                                # 1. Flagging was skipped
                                mock_flagging.assert_not_called()
                                assert (
                                    "skipping run_flagging() during startup"
                                    in caplog.text
                                )

                                # 2. classify_fires ran during startup: pending fire is now classified as industrial
                                fires_resp = c.get("/api/fires")
                                assert fires_resp.status_code == 200
                                fires_data = fires_resp.json()
                                assert len(fires_data) == 1
                                assert fires_data[0]["fire_type"] == "industrial"
                                assert fires_data[0]["state"] == "Gujarat"

                                # 3. Flags endpoint returns empty list
                                flags_resp = c.get("/api/flags")
                                assert flags_resp.status_code == 200
                                assert flags_resp.json() == []
        finally:
            app.dependency_overrides.clear()

    def test_global_exception_handler_returns_clean_json(self, client: TestClient):
        """Unhandled exceptions return HTTP 500 with {"detail": "Internal server error"}."""
        # Mount a temporary route that raises an unhandled error
        error_router = APIRouter()

        @error_router.get("/test-unhandled-error")
        def raise_unhandled():
            raise ValueError("Unexpected crash")

        app.include_router(error_router)

        response = client.get("/test-unhandled-error")
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal server error"}

    def test_cors_local_dev_origins(self, client: TestClient):
        """CORS preflight from localhost:5173 returns allowed origin header."""
        resp = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
        assert resp.headers.get("access-control-allow-credentials") == "true"

