"""FastAPI application entry point.

Run with:  uvicorn main:app --reload --port 8000
(from inside this project's root, with the virtualenv active)
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import catalog, health, images, manufacturer_requests, sync
from core.config import settings
from core.logging import configure_logging, get_logger

# Import manufacturers package so every code-based adapter (e.g. hdcvt)
# self-registers before the API starts serving requests. Manufacturers
# onboarded through "Yeu cau them hang moi" don't need this -- they're
# resolved dynamically from the DataCrawler_System_Config sheet on every request (see
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

@app.exception_handler(FileNotFoundError)
async def missing_credentials_handler(request: Request, exc: FileNotFoundError) -> JSONResponse:
    # `services.sheets_client.open_spreadsheet` raises this when the
    # service-account key configured by GOOGLE_SHEETS_CREDENTIALS_FILE isn't
    # on disk. Every route touching Sheets hits the same failure mode, so
    # one handler here beats a try/except in each of them -- and turns
    # Starlette's default plain-text 500 into JSON callers can actually
    # parse and act on.
    logger.error("Google Sheets credentials file missing: %s", exc)
    return JSONResponse(status_code=503, content={"detail": str(exc)})


app.include_router(health.router)
app.include_router(sync.router, prefix=settings.api_prefix)
app.include_router(catalog.router, prefix=settings.api_prefix)
app.include_router(manufacturer_requests.router, prefix=settings.api_prefix)
app.include_router(images.router, prefix=settings.api_prefix)
