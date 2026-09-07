"""
Tests for app.services.firms_client.

Covers fetch_csv URL formation (default all-India vs bbox scoping)
and normalise_firms_frame.
"""

from unittest.mock import MagicMock, patch
import pytest

from app.services.firms_client import (
    FIRMS_BASE,
    FIRMS_AREA_BASE,
    fetch_csv,
    fetch_and_ingest,
    normalise_firms_frame,
)


class TestFetchCsvBbox:
    @patch("app.services.firms_client.requests.get")
    def test_default_country_url(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
        mock_get.return_value = mock_resp

        fetch_csv("snpp", "VIIRS_SNPP_NRT", 1)

        mock_get.assert_called_once()
        called_url = mock_get.call_args[0][0]
        assert "/api/country/csv/" in called_url
        assert "/IND/1" in called_url

    @patch("app.services.firms_client.requests.get")
    def test_bbox_tuple_url(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
        mock_get.return_value = mock_resp

        # west=68.0, south=19.9, east=74.5, north=24.8
        bbox = (68.0, 19.9, 74.5, 24.8)
        fetch_csv("snpp", "VIIRS_SNPP_NRT", 1, bbox=bbox)

        mock_get.assert_called_once()
        called_url = mock_get.call_args[0][0]
        assert "/api/area/csv/" in called_url
        assert "/68.0,19.9,74.5,24.8/1" in called_url

    @patch("app.services.firms_client.requests.get")
    def test_bbox_dict_url(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
        mock_get.return_value = mock_resp

        bbox = {"west": 68.0, "south": 19.9, "east": 74.5, "north": 24.8}
        fetch_csv("noaa20", "VIIRS_NOAA20_NRT", 2, date_str="2026-08-01", bbox=bbox)

        mock_get.assert_called_once()
        called_url = mock_get.call_args[0][0]
        assert "/api/area/csv/" in called_url
        assert "/68.0,19.9,74.5,24.8/2/2026-08-01" in called_url
