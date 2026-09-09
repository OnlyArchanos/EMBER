"""
Router for health check and runtime data mode inspection (GET /api/health).
Exposes whether the backend is operating in seed or live mode.
"""

from fastapi import APIRouter

from app.config import settings
from app.schemas import HealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
def get_health() -> HealthOut:
    """Return backend liveness and current DATA_MODE dynamically from settings."""
    return HealthOut(status="ok", mode=settings.DATA_MODE)
