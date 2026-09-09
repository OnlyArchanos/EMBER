"""
Main FastAPI application entrypoint for the SIH26162 fire-detection backend.
Mounts routers, coordinates startup inference loading and data processing,
and configures global exception handling.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.database import SessionLocal
from app.ml import infer
from app.routers import fires, flags, health, stats, zones
from app.services.classifier import classify_fires
from app.services.flagging import run_flagging
from app.services.persistence import run_persistence

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager.
    Coordinates model loading and initial analysis pipeline execution on startup.
    """
    # 1. infer.load_model()
    # Missing artifact file: log clearly and continue startup.
    # Malformed artifact (e.g. KeyError): propagates without being caught.
    model_loaded = False
    try:
        infer.load_model()
        model_loaded = True
    except FileNotFoundError as e:
        logger.warning(
            "Model artifact file not found; continuing startup without loaded model: %s",
            e,
        )

    # 2 & 3. Run analysis pipeline in order using SessionLocal directly.
    # classify_fires and run_persistence run unconditionally.
    # run_flagging runs only if the model was loaded; otherwise it is skipped with a warning.
    # If any executed step raises, let startup fail loudly with the full error.
    db = SessionLocal()
    try:
        classified_count = classify_fires(db)
        logger.info(
            "Startup classification completed: %d fires classified",
            classified_count,
        )

        persistent_count = run_persistence(db)
        logger.info(
            "Startup persistence completed: %d persistent sources updated",
            persistent_count,
        )

        if model_loaded:
            flags_count = run_flagging(db)
            logger.info(
                "Startup flagging completed: %d flagged cases processed",
                flags_count,
            )
        else:
            logger.warning(
                "Model artifact not loaded (FileNotFoundError); skipping run_flagging() during startup.",
            )
    except Exception as exc:
        logger.error(
            "Startup analysis pipeline failed; terminating application startup: %s",
            exc,
            exc_info=True,
        )
        raise
    finally:
        db.close()

    yield


app = FastAPI(
    title="SIH26162 Fire Detection API",
    lifespan=lifespan,
)

# CORS middleware for frontend communication: allow common local dev origins directly
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Clean JSON response on unhandled errors."""
    if isinstance(exc, (HTTPException, StarletteHTTPException)):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )
    if isinstance(exc, RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors()},
        )

    logger.exception(
        "Unhandled internal server error on %s %s: %s",
        request.method,
        request.url.path,
        exc,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# Mount routers under /api
app.include_router(health.router, prefix="/api")
app.include_router(zones.router, prefix="/api")
app.include_router(fires.router, prefix="/api")
app.include_router(flags.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
