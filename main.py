"""FastAPI application entry point.

Run with:  uvicorn main:app --reload --port 8000
(from inside the `backend/` directory, with the virtualenv active)
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import catalog, health, manufacturer_requests, sync
from core.config import settings
from core.logging import configure_logging, get_logger
from db.database import init_db

# Import manufacturers package so every adapter registers itself before the
# API starts serving requests. This is the only place that needs to know
# the package exists.
import manufacturers  # noqa: F401

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Database initialized")
    _restore_ai_manufacturers()
    logger.info("Registered manufacturers: %s", [c.key for c in _registered_manufacturers()])
    yield


def _registered_manufacturers():
    from core.registry import registry

    return registry.list_manufacturers()


def _restore_ai_manufacturers() -> None:
    """Re-registers every AI-approved manufacturer (see
    api/routes/manufacturer_requests.py `/approve`) after a restart --
    `registry` is an in-memory singleton, so without this, an AI-approved
    manufacturer would vanish from `/api/manufacturers` until someone
    re-approved its request.
    """
    from core.registry import registry
    from core.slug import slugify
    from db.database import session_scope
    from db.repository import ManufacturerRequestRepository
    from manufacturers.generic_ai.adapter import GenericAIAdapter
    from api.routes.manufacturer_requests import _build_ai_config

    with session_scope() as session:
        for request in ManufacturerRequestRepository(session).list_ai_enabled():
            key = slugify(request.name)
            if not registry.is_registered(key) and request.website_url:
                registry.register(key, GenericAIAdapter, _build_ai_config(key, request.name, request.website_url))
                logger.info("Restored AI-assisted manufacturer '%s' from a previous approval", key)


app = FastAPI(title="Manufacturer Data Sync Engine", version="0.1.0", lifespan=lifespan)

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
