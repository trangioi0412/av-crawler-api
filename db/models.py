"""ORM models.

`Product` is manufacturer-independent: `manufacturer` is a plain string
column (not an FK to a manufacturer table) because manufacturers are defined
in code (the registry), not as editable database rows. `specifications` and
the URL lists use JSON columns rather than dozens of per-spec columns, since
every manufacturer's spec sheet shape differs (see backend/README.md).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("dedup_key", name="uq_products_dedup_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dedup_key: Mapped[str] = mapped_column(String(160), index=True, nullable=False)

    manufacturer: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    brand: Mapped[str | None] = mapped_column(String(80), nullable=True)

    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(200), nullable=True)

    category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    subcategory: Mapped[str | None] = mapped_column(String(200), nullable=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    short_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    product_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    image_urls: Mapped[list] = mapped_column(JSON, default=list)
    document_urls: Mapped[list] = mapped_column(JSON, default=list)
    specifications: Mapped[dict] = mapped_column(JSON, default=dict)
    features: Mapped[list] = mapped_column(JSON, default=list)

    status: Mapped[str] = mapped_column(String(40), default="active")
    source: Mapped[str] = mapped_column(String(40), default="web_crawl")
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    first_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class SyncJob(Base):
    """Persisted so job status survives a service restart, and so
    `GET /api/sync/status/{job_id}` works from any request without relying
    on in-process memory.
    """

    __tablename__ = "sync_jobs"

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    manufacturer: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), default="full")

    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)

    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[float] = mapped_column(Float, default=0.0)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ManufacturerRequest(Base):
    """A user-submitted request to onboard a new manufacturer, captured via
    the admin UI's "Yêu cầu thêm hãng mới" form. Two ways this gets
    fulfilled:

    1. A developer verifies the site and writes a real adapter (see
       manufacturers/base.py and backend/README.md "Adding a new
       manufacturer"), then marks this request "done" via PATCH -- no AI
       involved, `ai_sync_enabled` stays False.
    2. The customer-facing AI path: POST .../preview runs
       `GenericManufacturerAiAdapter` against a few pages and returns a
       sample for review; POST .../approve registers that manufacturer
       (keyed by a slug of `name`) with the registry using that adapter and
       sets `ai_sync_enabled=True`, so `main.py`'s startup can re-register
       it after a restart (see `_restore_ai_manufacturers` there).
    """

    __tablename__ = "manufacturer_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    website_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_sync_enabled: Mapped[bool] = mapped_column(default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
