"""
Application settings for the SIH26162 fire-detection backend.
All values are loaded from the environment (or backend/.env); nothing is
hardcoded here.  Import the singleton `settings` object everywhere else in
the app — do not instantiate Settings a second time.
"""

from enum import Enum
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path to backend/data/sih_fire.db and backend/.env, anchored to this
# file's location so they resolve identically regardless of working directory.
# config.py lives at backend/app/config.py → parent.parent reaches backend/.
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "sih_fire.db"
_DEFAULT_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


class DataMode(str, Enum):
    seed = "seed"
    live = "live"


class Settings(BaseSettings):
    # External API credentials — must be supplied in .env for live mode;
    # not required when DATA_MODE=seed because no live call is made.
    NASA_FIRMS_MAP_KEY: str = ""
    NOMINATIM_USER_AGENT: str = ""

    # Database — defaults to a local SQLite file under backend/data/.
    DATABASE_URL: str = f"sqlite:///{_DEFAULT_DB_PATH}"

    # Demo-mode switch (RULES.md §1, rule 3).  Safe default is "seed" so a
    # fresh checkout works fully offline without any external call succeeding.
    DATA_MODE: DataMode = DataMode.seed

    # Scheduler — how often the live ingestion job runs (ignored in seed mode).
    FETCH_INTERVAL_HOURS: int = 24

    # Logging
    LOG_LEVEL: str = "INFO"

    @model_validator(mode="after")
    def _check_live_mode_keys(self) -> "Settings":
        """Fail fast at startup if live mode is selected but required
        external-API credentials are missing."""
        if self.DATA_MODE == DataMode.live:
            if not self.NASA_FIRMS_MAP_KEY:
                raise ValueError(
                    "NASA_FIRMS_MAP_KEY must be set when DATA_MODE=live"
                )
            if not self.NOMINATIM_USER_AGENT:
                raise ValueError(
                    "NOMINATIM_USER_AGENT must be set when DATA_MODE=live"
                )
        return self

    model_config = SettingsConfigDict(
        env_file=(_DEFAULT_ENV_PATH, "backend/.env", ".env"),
        env_file_encoding="utf-8",
        # Extra env vars are silently ignored rather than raising an error,
        # which makes adding future settings non-breaking.
        extra="ignore",
    )


settings = Settings()
