"""Intake endpoints for "request a new manufacturer" -- lets someone submit
a name/website from the admin UI without needing to write any code. This
does NOT register a registry adapter or trigger crawling; it just queues
the request for a developer to pick up (see
`db/models.py::ManufacturerRequest` and `backend/README.md` "Adding a new
manufacturer").
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from api.routes.sync import _run_sync_job
from api.schemas import (
    AiApproveResponse,
    AiPreviewProduct,
    AiPreviewResponse,
    ManufacturerRequestIn,
    ManufacturerRequestOut,
    ManufacturerRequestStatusIn,
)
from core.logging import get_logger
from core.registry import registry
from core.slug import slugify
from db.database import get_db
from db.repository import ManufacturerRequestRepository, SyncJobRepository
from manufacturers.base import ManufacturerConfig
from manufacturers.generic_ai.adapter import GenericAIAdapter
from services.recon import probe_manufacturer_website

logger = get_logger(__name__)
router = APIRouter(prefix="/manufacturer-requests", tags=["manufacturer-requests"])

_VALID_STATUSES = {"pending", "in_progress", "done", "rejected"}
_PREVIEW_SAMPLE_SIZE = 3


def _build_ai_config(key: str, display_name: str, base_url: str) -> ManufacturerConfig:
    return ManufacturerConfig(
        key=key,
        display_name=display_name,
        base_url=base_url,
        request_delay_seconds=1.5,
        timeout_seconds=20.0,
        max_products=200,  # bound cost: each product costs one local LLM call
    )


def _normalize_website_url(raw: str) -> str:
    value = raw.strip()
    if not value.lower().startswith(("http://", "https://")):
        value = f"https://{value}"
    return value


@router.post("", response_model=ManufacturerRequestOut, status_code=201)
def create_manufacturer_request(payload: ManufacturerRequestIn, db: Session = Depends(get_db)) -> ManufacturerRequestOut:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="'name' is required")
    if not payload.website_url.strip():
        raise HTTPException(status_code=400, detail="'website_url' is required")

    website_url = _normalize_website_url(payload.website_url)

    # Best-effort automated recon (sitemap.xml / robots.txt / static-vs-JS
    # check) so whoever picks this up starts from an answered checklist
    # instead of from scratch. Never blocks/fails request creation.
    try:
        notes = probe_manufacturer_website(website_url).to_notes()
    except Exception:  # noqa: BLE001 - recon must never fail the request submission
        logger.exception("Website recon failed for %s", website_url)
        notes = "Kiểm tra sơ bộ tự động gặp lỗi không xác định -- cần xác minh thủ công."

    request = ManufacturerRequestRepository(db).create(name=name, website_url=website_url, notes=notes)
    db.commit()
    return ManufacturerRequestOut.model_validate(request)


@router.get("", response_model=list[ManufacturerRequestOut])
def list_manufacturer_requests(status: str | None = None, db: Session = Depends(get_db)) -> list[ManufacturerRequestOut]:
    requests = ManufacturerRequestRepository(db).list(status=status)
    return [ManufacturerRequestOut.model_validate(r) for r in requests]


@router.patch("/{request_id}", response_model=ManufacturerRequestOut)
def update_manufacturer_request_status(
    request_id: int, payload: ManufacturerRequestStatusIn, db: Session = Depends(get_db)
) -> ManufacturerRequestOut:
    if payload.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(_VALID_STATUSES)}")
    try:
        request = ManufacturerRequestRepository(db).update_status(request_id, payload.status, payload.notes)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Manufacturer request {request_id} not found")
    db.commit()
    return ManufacturerRequestOut.model_validate(request)


@router.post("/{request_id}/preview", response_model=AiPreviewResponse)
def preview_manufacturer_request(request_id: int, db: Session = Depends(get_db)) -> AiPreviewResponse:
    """Runs the AI-assisted adapter against a handful of real pages from
    the request's website and returns what it extracted, WITHOUT touching
    the product database or Google Sheets -- purely for a human to eyeball
    accuracy before approving (see `/approve`).
    """
    request = ManufacturerRequestRepository(db).get(request_id)
    if request is None:
        raise HTTPException(status_code=404, detail=f"Manufacturer request {request_id} not found")
    if not request.website_url:
        raise HTTPException(status_code=400, detail="This request has no website_url to crawl")

    key = slugify(request.name)
    config = _build_ai_config(key, request.name, request.website_url)
    adapter = registry.get_ad_hoc(GenericAIAdapter, config)

    try:
        urls = list(adapter.discover_product_urls())[:_PREVIEW_SAMPLE_SIZE]
        if not urls:
            raise HTTPException(
                status_code=422,
                detail="Không tìm được URL sản phẩm nào để thử -- có thể website chặn crawl hoặc cấu trúc quá khác biệt.",
            )

        products: list[AiPreviewProduct] = []
        for result in adapter.crawl_urls(urls):
            if result.ok:
                p = result.raw_product
                products.append(
                    AiPreviewProduct(
                        source_url=result.source_url,
                        ok=True,
                        name=p.name,
                        model=p.model,
                        category=p.category,
                        description=p.description,
                        features=p.features,
                        specifications=p.specifications,
                        image_urls=p.image_urls,
                    )
                )
            else:
                products.append(AiPreviewProduct(source_url=result.source_url, ok=False, error=result.error))

        return AiPreviewResponse(manufacturer_key=key, checked_urls=len(urls), products=products)
    finally:
        adapter.http.close()


@router.post("/{request_id}/approve", response_model=AiApproveResponse, status_code=202)
def approve_manufacturer_request(
    request_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> AiApproveResponse:
    """Confirms the AI preview looked good enough: registers this
    manufacturer (AI-assisted adapter, keyed by a slug of its name) and
    kicks off a full sync the same way `/api/sync/manufacturer` does. From
    here on it behaves like any other registered manufacturer -- appears
    in `/api/manufacturers`, has normal sync jobs/status.
    """
    request = ManufacturerRequestRepository(db).get(request_id)
    if request is None:
        raise HTTPException(status_code=404, detail=f"Manufacturer request {request_id} not found")
    if not request.website_url:
        raise HTTPException(status_code=400, detail="This request has no website_url to crawl")

    key = slugify(request.name)
    if not registry.is_registered(key):
        registry.register(key, GenericAIAdapter, _build_ai_config(key, request.name, request.website_url))

    ManufacturerRequestRepository(db).mark_ai_approved(
        request_id, notes=(request.notes or "") + "\n\n-> Đã duyệt, đang đồng bộ bằng AI adapter."
    )

    job_id = uuid.uuid4().hex
    SyncJobRepository(db).create(job_id=job_id, manufacturer=key, mode="full")
    db.commit()

    background_tasks.add_task(_run_sync_job, job_id, key, "full")

    return AiApproveResponse(manufacturer_key=key, job_id=job_id, status="queued")
