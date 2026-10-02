"""Generic sync endpoints.

Deliberately NOT `/api/sync/hdcvt`, `/api/sync/yealink`, etc. -- one route
takes `manufacturer` as a request field and resolves it the same way the
engine does (see `core/manufacturer_resolution.py`), so a new manufacturer
needs no new route -- whether it's a hand-written code adapter or a brand
onboarded through DataCrawler_System_Config.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api.schemas import SyncAcceptedResponse, SyncAllAcceptedResponse, SyncRequest, SyncStatusResponse
from core.config import settings
from core.engine import sync_manufacturer_data
from core.logging import get_logger
from core.manufacturer_resolution import resolve_manufacturer
from core.registry import UnknownManufacturerError
from services import job_store
from services.admin_sheets import list_brand_sheet_names, open_admin_spreadsheet

logger = get_logger(__name__)
router = APIRouter(prefix="/sync", tags=["sync"])


def _run_sync_job(job_id: str, manufacturer: str, mode: str) -> None:
    sync_manufacturer_data(manufacturer=manufacturer, mode=mode, job_id=job_id)


def _run_sync_all(jobs: list[tuple[str, str]]) -> None:
    """Runs every (manufacturer, job_id) pair one after another -- NOT in
    parallel. Concurrent crawls would hammer the single local Ollama server
    the AI-assisted adapter uses, and defeats each adapter's own polite
    per-request delay/rate-limiting anyway.
    """
    for manufacturer, job_id in jobs:
        _run_sync_job(job_id, manufacturer, "full")


@router.post("/manufacturer", response_model=SyncAcceptedResponse, status_code=202)
def start_sync(request: SyncRequest, background_tasks: BackgroundTasks) -> SyncAcceptedResponse:
    manufacturer_key = request.manufacturer.strip().lower()
    try:
        resolve_manufacturer(manufacturer_key)
    except UnknownManufacturerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = uuid.uuid4().hex
    job_store.create(job_id=job_id, manufacturer=manufacturer_key, mode=request.mode)

    background_tasks.add_task(_run_sync_job, job_id, manufacturer_key, request.mode)

    return SyncAcceptedResponse(job_id=job_id, status="queued", manufacturer=manufacturer_key)


@router.post("/all", response_model=SyncAllAcceptedResponse, status_code=202)
def start_sync_all(background_tasks: BackgroundTasks) -> SyncAllAcceptedResponse:
    """Syncs every manufacturer that has its own sheet tab (i.e. every tab
    except the reserved admin ones -- see `admin_sheets.RESERVED_SHEET_TITLES`),
    to check each for new products. Brands with a tab but no known crawl
    source (no code adapter and no DataCrawler_System_Config website) are skipped and
    reported back, rather than failing the whole batch.
    """
    if not settings.google_spreadsheet_id or not settings.google_sheets_credentials_path:
        raise HTTPException(status_code=400, detail="Google Sheets (GOOGLE_SPREADSHEET_ID) is not configured")

    spreadsheet = open_admin_spreadsheet(settings.google_sheets_credentials_path, settings.google_spreadsheet_id)
    brand_names = list_brand_sheet_names(spreadsheet)

    jobs: list[tuple[str, str]] = []
    accepted: list[SyncAcceptedResponse] = []
    skipped: list[str] = []

    for name in brand_names:
        key = name.strip().lower()
        try:
            resolve_manufacturer(key)
        except UnknownManufacturerError:
            skipped.append(name)
            continue

        job_id = uuid.uuid4().hex
        job_store.create(job_id=job_id, manufacturer=key, mode="full")
        jobs.append((key, job_id))
        accepted.append(SyncAcceptedResponse(job_id=job_id, status="queued", manufacturer=key))

    if jobs:
        background_tasks.add_task(_run_sync_all, jobs)

    return SyncAllAcceptedResponse(jobs=accepted, skipped=skipped)


@router.get("/status/{job_id}", response_model=SyncStatusResponse)
def get_sync_status(job_id: str) -> SyncStatusResponse:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Sync job '{job_id}' not found")
    return SyncStatusResponse(
        job_id=job.job_id,
        manufacturer=job.manufacturer,
        mode=job.mode,
        status=job.status,
        total=job.total,
        processed=job.processed,
        success=job.success,
        failed=job.failed,
        skipped=job.skipped,
        progress=job.progress,
        error=job.error,
        warnings=job.warnings or [],
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
    )


@router.get("/jobs", response_model=list[SyncStatusResponse])
def list_recent_jobs(manufacturer: str | None = None) -> list[SyncStatusResponse]:
    jobs = job_store.list_recent(manufacturer=manufacturer)
    return [
        SyncStatusResponse(
            job_id=j.job_id,
            manufacturer=j.manufacturer,
            mode=j.mode,
            status=j.status,
            total=j.total,
            processed=j.processed,
            success=j.success,
            failed=j.failed,
            skipped=j.skipped,
            progress=j.progress,
            error=j.error,
            warnings=j.warnings or [],
            started_at=j.started_at,
            completed_at=j.completed_at,
            created_at=j.created_at,
        )
        for j in jobs
    ]
