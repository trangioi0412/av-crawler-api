"""Intake endpoints for "Yeu cau them hang moi" (request a new manufacturer)
-- lets someone submit a name/website from the admin UI without needing to
write any code.

Tracked entirely in the New_brand Google Sheet (see
`services/admin_sheets.py::NewBrandStore`) -- there is no database. A
row's lifecycle:

    Cho duyet (submitted) -> Duyet (approved) -> Dang cao du lieu (crawling)
        -> Da cao xong (done) -- row deleted right after, since
           System_Config (not New_brand) is the durable record of this
           brand's website from here on.

    -> Loi cao du lieu (error) if the sync itself failed -- the row is left
       in place so a human can investigate/retry, rather than silently
       disappearing.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api.schemas import (
    AiApproveResponse,
    AiPreviewProduct,
    AiPreviewResponse,
    ManufacturerRequestIn,
    ManufacturerRequestOut,
    ManufacturerRequestStatusIn,
)
from core.config import settings
from core.engine import sync_manufacturer_data
from core.logging import get_logger
from core.manufacturer_resolution import build_ai_config
from core.models.job import JobStatus
from core.registry import registry
from manufacturers.generic_ai.adapter import GenericAIAdapter
from services import job_store
from services.admin_sheets import NewBrandStatus, NewBrandStore, SystemConfigStore, open_admin_spreadsheet
from services.recon import probe_manufacturer_website

logger = get_logger(__name__)
router = APIRouter(prefix="/manufacturer-requests", tags=["manufacturer-requests"])

_PREVIEW_SAMPLE_SIZE = 3


def _normalize_website_url(raw: str) -> str:
    value = raw.strip()
    if not value.lower().startswith(("http://", "https://")):
        value = f"https://{value}"
    return value


def _new_brand_store() -> NewBrandStore:
    if not settings.google_spreadsheet_id or not settings.google_sheets_credentials_path:
        raise HTTPException(status_code=400, detail="Google Sheets (GOOGLE_SPREADSHEET_ID) is not configured")
    spreadsheet = open_admin_spreadsheet(settings.google_sheets_credentials_path, settings.google_spreadsheet_id)
    return NewBrandStore(spreadsheet)


def _system_config_store() -> SystemConfigStore:
    spreadsheet = open_admin_spreadsheet(settings.google_sheets_credentials_path, settings.google_spreadsheet_id)
    return SystemConfigStore(spreadsheet)


def _row_to_out(row: dict[str, str]) -> ManufacturerRequestOut:
    return ManufacturerRequestOut(
        id=row["Slug"],
        name=row.get("Tên hãng", ""),
        website_url=row.get("Website") or None,
        status=row.get("Trạng thái", ""),
        notes=row.get("Ghi chú") or None,
        created_at=row.get("Ngày gửi", ""),
        updated_at=row.get("Cập nhật lúc", ""),
    )


@router.post("", response_model=ManufacturerRequestOut, status_code=201)
def create_manufacturer_request(payload: ManufacturerRequestIn) -> ManufacturerRequestOut:
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

    row = _new_brand_store().create(name=name, website_url=website_url, notes=notes)
    return _row_to_out(row)


@router.get("", response_model=list[ManufacturerRequestOut])
def list_manufacturer_requests(status: str | None = None) -> list[ManufacturerRequestOut]:
    rows = _new_brand_store().list(status=status)
    return [_row_to_out(r) for r in rows]


@router.patch("/{slug}", response_model=ManufacturerRequestOut)
def update_manufacturer_request_status(slug: str, payload: ManufacturerRequestStatusIn) -> ManufacturerRequestOut:
    if payload.status not in NewBrandStatus.ALL:
        raise HTTPException(status_code=400, detail=f"status must be one of {NewBrandStatus.ALL}")
    store = _new_brand_store()
    if store.get(slug) is None:
        raise HTTPException(status_code=404, detail=f"Manufacturer request '{slug}' not found")
    row = store.update_status(slug, payload.status, payload.notes)
    return _row_to_out(row)


@router.post("/{slug}/preview", response_model=AiPreviewResponse)
def preview_manufacturer_request(slug: str) -> AiPreviewResponse:
    """Runs the AI-assisted adapter against a handful of real pages from
    the request's website and returns what it extracted, WITHOUT touching
    New_brand, System_Config, or the product sheet -- purely for a human
    to eyeball accuracy before approving (see `/approve`).
    """
    row = _new_brand_store().get(slug)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Manufacturer request '{slug}' not found")
    website_url = row.get("Website")
    if not website_url:
        raise HTTPException(status_code=400, detail="This request has no website_url to crawl")

    config = build_ai_config(slug, row.get("Tên hãng") or slug, website_url)
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

        return AiPreviewResponse(manufacturer_key=slug, checked_urls=len(urls), products=products)
    finally:
        adapter.http.close()


def _run_new_brand_sync_job(slug: str, job_id: str) -> None:
    store = _new_brand_store()
    store.update_status(slug, NewBrandStatus.CRAWLING)

    result = sync_manufacturer_data(manufacturer=slug, mode="full", job_id=job_id)

    if result.status in (JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_WARNINGS) and result.success > 0:
        # The brand's own product sheet tab now exists (upsert_rows creates
        # it on first write) -- System_Config already has the durable
        # website record (written at approval time, below), so this
        # request no longer needs to sit in the intake queue.
        store.update_status(slug, NewBrandStatus.DONE)
        store.delete(slug)
    else:
        store.update_status(
            slug, NewBrandStatus.ERROR, notes=result.error or "Sync thất bại hoặc không tìm được sản phẩm nào."
        )


@router.post("/{slug}/approve", response_model=AiApproveResponse, status_code=202)
def approve_manufacturer_request(slug: str, background_tasks: BackgroundTasks) -> AiApproveResponse:
    """Confirms the AI preview looked good enough: records this
    manufacturer's website in System_Config (the durable record from here
    on) and kicks off a full sync. New_brand's status walks
    Duyet -> Dang cao du lieu -> Da cao xong (row deleted) exactly as
    described at the top of this file.
    """
    new_brand = _new_brand_store()
    row = new_brand.get(slug)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Manufacturer request '{slug}' not found")
    website_url = row.get("Website")
    if not website_url:
        raise HTTPException(status_code=400, detail="This request has no website_url to crawl")

    name = row.get("Tên hãng") or slug
    _system_config_store().set_manufacturer(slug, name, website_url)
    new_brand.update_status(slug, NewBrandStatus.APPROVED, notes=(row.get("Ghi chú") or "") + "\n\n-> Đã duyệt, chuẩn bị đồng bộ.")

    job_id = uuid.uuid4().hex
    job_store.create(job_id=job_id, manufacturer=slug, mode="full")

    background_tasks.add_task(_run_new_brand_sync_job, slug, job_id)

    return AiApproveResponse(manufacturer_key=slug, job_id=job_id, status="queued")
