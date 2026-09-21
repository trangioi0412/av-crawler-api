"""Transforms a validated CanonicalProduct into a plain dict of columns
ready for persistence. Kept separate from the repository/ORM layer so the
pipeline stays testable without a database.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.models.product import CanonicalProduct


class Transformer:
    def transform(self, product: CanonicalProduct) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        return {
            "dedup_key": product.dedup_key,
            "manufacturer": product.manufacturer,
            "brand": product.brand,
            "name": product.name,
            "model": product.model,
            "sku": product.sku,
            "category": product.category,
            "subcategory": product.subcategory,
            "description": product.description,
            "short_description": product.short_description,
            "product_url": product.source_url,
            "image_urls": product.image_urls,
            "document_urls": product.document_urls,
            "specifications": product.specifications,
            "features": product.features,
            "status": product.status,
            "source": product.source,
            "source_url": product.source_url,
            "last_synced_at": now,
        }
