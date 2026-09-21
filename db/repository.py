"""Data access layer. The sync engine talks to the database only through
this module -- it never issues SQLAlchemy queries directly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import ManufacturerRequest, Product, SyncJob


class ProductRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_dedup_index(self, manufacturer: str) -> dict[str, int]:
        """dedup_key -> product id, for every existing product of this
        manufacturer. Loaded once per sync run so the Deduplicator can
        resolve create/update decisions without a query per product.
        """
        rows = self.session.execute(
            select(Product.dedup_key, Product.id).where(Product.manufacturer == manufacturer)
        ).all()
        return {dedup_key: product_id for dedup_key, product_id in rows}

    def create(self, fields: dict[str, Any]) -> Product:
        product = Product(**fields, first_synced_at=datetime.now(timezone.utc))
        self.session.add(product)
        self.session.flush()
        return product

    def update(self, product_id: int, fields: dict[str, Any]) -> Product:
        product = self.session.get(Product, product_id)
        if product is None:
            raise ValueError(f"Product id={product_id} not found")
        for key, value in fields.items():
            setattr(product, key, value)
        self.session.flush()
        return product

    def list_products(self, *, manufacturer: str | None = None, limit: int = 100, offset: int = 0) -> list[Product]:
        stmt = select(Product).order_by(Product.id.desc()).limit(limit).offset(offset)
        if manufacturer:
            stmt = stmt.where(Product.manufacturer == manufacturer)
        return list(self.session.execute(stmt).scalars())

    def count_products(self, *, manufacturer: str | None = None) -> int:
        stmt = select(Product)
        if manufacturer:
            stmt = stmt.where(Product.manufacturer == manufacturer)
        return len(list(self.session.execute(stmt).scalars()))


class SyncJobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, job_id: str, manufacturer: str, mode: str) -> SyncJob:
        job = SyncJob(job_id=job_id, manufacturer=manufacturer, mode=mode, status="queued")
        self.session.add(job)
        self.session.flush()
        return job

    def get(self, job_id: str) -> SyncJob | None:
        return self.session.get(SyncJob, job_id)

    def update(self, job_id: str, **fields: Any) -> SyncJob:
        job = self.session.get(SyncJob, job_id)
        if job is None:
            raise ValueError(f"Sync job {job_id} not found")
        for key, value in fields.items():
            setattr(job, key, value)
        self.session.flush()
        return job

    def list_recent(self, *, manufacturer: str | None = None, limit: int = 20) -> list[SyncJob]:
        stmt = select(SyncJob).order_by(SyncJob.created_at.desc()).limit(limit)
        if manufacturer:
            stmt = stmt.where(SyncJob.manufacturer == manufacturer)
        return list(self.session.execute(stmt).scalars())


class ManufacturerRequestRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, *, name: str, website_url: str | None, notes: str | None = None) -> ManufacturerRequest:
        request = ManufacturerRequest(name=name, website_url=website_url, status="pending", notes=notes)
        self.session.add(request)
        self.session.flush()
        return request

    def get(self, request_id: int) -> ManufacturerRequest | None:
        return self.session.get(ManufacturerRequest, request_id)

    def list(self, *, status: str | None = None, limit: int = 100) -> list[ManufacturerRequest]:
        stmt = select(ManufacturerRequest).order_by(ManufacturerRequest.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(ManufacturerRequest.status == status)
        return list(self.session.execute(stmt).scalars())

    def update_status(self, request_id: int, status: str, notes: str | None = None) -> ManufacturerRequest:
        request = self.session.get(ManufacturerRequest, request_id)
        if request is None:
            raise ValueError(f"Manufacturer request id={request_id} not found")
        request.status = status
        if notes is not None:
            request.notes = notes
        self.session.flush()
        return request

    def mark_ai_approved(self, request_id: int, notes: str | None = None) -> ManufacturerRequest:
        request = self.session.get(ManufacturerRequest, request_id)
        if request is None:
            raise ValueError(f"Manufacturer request id={request_id} not found")
        request.status = "done"
        request.ai_sync_enabled = True
        if notes is not None:
            request.notes = notes
        self.session.flush()
        return request

    def list_ai_enabled(self) -> list[ManufacturerRequest]:
        stmt = select(ManufacturerRequest).where(ManufacturerRequest.ai_sync_enabled.is_(True))
        return list(self.session.execute(stmt).scalars())
