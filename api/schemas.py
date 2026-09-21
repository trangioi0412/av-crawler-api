"""Pydantic request/response models for the public API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ManufacturerOut(BaseModel):
    key: str
    display_name: str
    base_url: str


class SyncRequest(BaseModel):
    manufacturer: str = Field(..., description="Registry key, e.g. 'hdcvt'")
    mode: str = Field("full", description="'full' (default). 'incremental' is reserved for future use.")


class SyncAcceptedResponse(BaseModel):
    success: bool = True
    job_id: str
    status: str
    manufacturer: str


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


class ProductOut(BaseModel):
    id: int
    manufacturer: str
    brand: str | None
    name: str | None
    model: str | None
    sku: str | None
    category: str | None
    subcategory: str | None
    description: str | None
    short_description: str | None
    product_url: str | None
    image_urls: list[str]
    document_urls: list[str]
    specifications: dict
    features: list[str]
    status: str
    source: str
    source_url: str | None
    last_synced_at: datetime

    model_config = {"from_attributes": True}


class ManufacturerRequestIn(BaseModel):
    name: str = Field(..., min_length=1, description="Manufacturer name, e.g. 'Yealink'")
    website_url: str = Field(..., min_length=1, description="Manufacturer's official website, e.g. 'yealink.com'")


class ManufacturerRequestStatusIn(BaseModel):
    status: str = Field(..., description="One of: pending, in_progress, done, rejected")
    notes: str | None = None


class ManufacturerRequestOut(BaseModel):
    id: int
    name: str
    website_url: str | None
    status: str
    notes: str | None
    ai_sync_enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


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
