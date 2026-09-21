"""Pydantic request/response models for the public API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ManufacturerOut(BaseModel):
    key: str
    display_name: str
    base_url: str


class SyncRequest(BaseModel):
    manufacturer: str = Field(..., description="Manufacturer key, e.g. 'hdcvt' or a slugified brand name")
    mode: str = Field("full", description="'full' (default). 'incremental' is reserved for future use.")


class SyncAcceptedResponse(BaseModel):
    success: bool = True
    job_id: str
    status: str
    manufacturer: str


class SyncAllAcceptedResponse(BaseModel):
    success: bool = True
    jobs: list[SyncAcceptedResponse]
    skipped: list[str] = Field(
        default_factory=list,
        description="Brand sheet names with no known crawl source (no code adapter, no System_Config website)",
    )


class SyncStatusResponse(BaseModel):
    job_id: str
    manufacturer: str
    mode: str
    status: str
    total: int
    processed: int
    success: int
    failed: int
    skipped: int
    progress: float
    error: str | None = None
    warnings: list[str] = []
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class ManufacturerRequestIn(BaseModel):
    name: str = Field(..., min_length=1, description="Manufacturer name, e.g. 'Yealink'")
    website_url: str = Field(..., min_length=1, description="Manufacturer's official website, e.g. 'yealink.com'")


class ManufacturerRequestStatusIn(BaseModel):
    status: str = Field(..., description="One of the New_brand status values, see admin_sheets.NewBrandStatus")
    notes: str | None = None


class ManufacturerRequestOut(BaseModel):
    """Mirrors one row of the New_brand sheet. `id` is a slug of the brand
    name (Sheets rows have no database auto-increment id), stable across
    the whole request lifecycle -- it's also the manufacturer key the
    brand is synced under once approved.
    """

    id: str
    name: str
    website_url: str | None
    status: str
    notes: str | None
    created_at: str
    updated_at: str


class AiPreviewProduct(BaseModel):
    source_url: str
    ok: bool
    name: str | None = None
    model: str | None = None
    category: str | None = None
    description: str | None = None
    features: list[str] = []
    specifications: dict = {}
    image_urls: list[str] = []
    error: str | None = None


class AiPreviewResponse(BaseModel):
    manufacturer_key: str
    checked_urls: int
    products: list[AiPreviewProduct]


class AiApproveResponse(BaseModel):
    success: bool = True
    manufacturer_key: str
    job_id: str
    status: str
