"""Tests for app.config — startup validation of live-mode credentials."""

import pytest

from app.config import DataMode, Settings


class TestLiveModeValidation:
    """Settings._check_live_mode_keys must raise when DATA_MODE=live and
    required credentials are missing, and must not raise in seed mode."""

    def test_seed_mode_accepts_empty_keys(self) -> None:
        """Seed mode works with no external API keys — this is the default
        offline-demo path (RULES.md §1, rule 3)."""
        s = Settings(
            DATA_MODE=DataMode.seed,
            NASA_FIRMS_MAP_KEY="",
            NOMINATIM_USER_AGENT="",
            _env_file=None,
        )
        assert s.DATA_MODE == DataMode.seed

    def test_live_mode_raises_without_firms_key(self) -> None:
        with pytest.raises(ValueError, match="NASA_FIRMS_MAP_KEY"):
            Settings(
                DATA_MODE=DataMode.live,
                NASA_FIRMS_MAP_KEY="",
                NOMINATIM_USER_AGENT="my-agent",
                _env_file=None,
            )

    def test_live_mode_raises_without_nominatim_agent(self) -> None:
        with pytest.raises(ValueError, match="NOMINATIM_USER_AGENT"):
            Settings(
                DATA_MODE=DataMode.live,
                NASA_FIRMS_MAP_KEY="some-key",
                NOMINATIM_USER_AGENT="",
                _env_file=None,
            )

    def test_live_mode_accepts_both_keys_set(self) -> None:
        s = Settings(
            DATA_MODE=DataMode.live,
            NASA_FIRMS_MAP_KEY="some-key",
            NOMINATIM_USER_AGENT="my-agent",
            _env_file=None,
        )
        assert s.DATA_MODE == DataMode.live
