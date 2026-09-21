"""FastAPI application entry point.

Run with:  uvicorn main:app --reload --port 8000
(from inside this project's root, with the virtualenv active)
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import catalog, health, manufacturer_requests, sync
from core.config import settings
from core.logging import configure_logging, get_logger

# Import manufacturers package so every code-based adapter (e.g. hdcvt)
# self-registers before the API starts serving requests. Manufacturers
# onboarded through "Yeu cau them hang moi" don't need this -- they're
# resolved dynamically from the System_Config sheet on every request (see
# core/manufacturer_resolution.py), so unlike before there is nothing to
# restore into an in-memory registry after a restart.
import manufacturers  # noqa: F401

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.registry import registry

    logger.info("Code-registered manufacturers: %s", [c.key for c in registry.list_manufacturers()])
    if not settings.google_spreadsheet_id:
        logger.warning(
            "GOOGLE_SPREADSHEET_ID is not set -- Google Sheets is this service's only persistence layer, "
            "so syncing will fail until it's configured (see .env.example)."
        )
    yield


app = FastAPI(title="Manufacturer Data Sync Engine", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(sync.router, prefix=settings.api_prefix)
app.include_router(catalog.router, prefix=settings.api_prefix)
app.include_router(manufacturer_requests.router, prefix=settings.api_prefix)
