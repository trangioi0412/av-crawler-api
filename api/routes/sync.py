"""Generic sync endpoints.

Deliberately NOT `/api/sync/hdcvt`, `/api/sync/yealink`, etc. -- one route
takes `manufacturer` as a request field and resolves it through the same
registry the engine uses, so a new manufacturer needs no new route.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session
from fastapi import Depends

from api.schemas import SyncAcceptedResponse, SyncRequest, SyncStatusResponse
from core.engine import sync_manufacturer_data
from core.logging import get_logger
from core.registry import registry
from db.database import get_db, session_scope
from db.repository import SyncJobRepository

logger = get_logger(__name__)
router = APIRouter(prefix="/sync", tags=["sync"])


def _run_sync_job(job_id: str, manufacturer: str, mode: str) -> None:
    sync_manufacturer_data(manufacturer=manufacturer, mode=mode, job_id=job_id)


@router.post("/manufacturer", response_model=SyncAcceptedResponse, status_code=202)
def start_sync(request: SyncRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> SyncAcceptedResponse:
    manufacturer_key = request.manufacturer.strip().lower()
    if not registry.is_registered(manufacturer_key):
        known = ", ".join(sorted(c.key for c in registry.list_manufacturers())) or "(none registered)"
        raise HTTPException(status_code=400, detail=f"Unknown manufacturer '{request.manufacturer}'. Known: {known}")

    job_id = uuid.uuid4().hex
    SyncJobRepository(db).create(job_id=job_id, manufacturer=manufacturer_key, mode=request.mode)
    db.commit()

    background_tasks.add_task(_run_sync_job, job_id, manufacturer_key, request.mode)

    return SyncAcceptedResponse(job_id=job_id, status="queued", manufacturer=manufacturer_key)


@router.get("/status/{job_id}", response_model=SyncStatusResponse)
def get_sync_status(job_id: str, db: Session = Depends(get_db)) -> SyncStatusResponse:
    job = SyncJobRepository(db).get(job_id)
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
def list_recent_jobs(manufacturer: str | None = None, db: Session = Depends(get_db)) -> list[SyncStatusResponse]:
    jobs = SyncJobRepository(db).list_recent(manufacturer=manufacturer)
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
