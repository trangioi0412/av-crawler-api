"""Generic data validation, applied identically to every manufacturer.

Classifies a CanonicalProduct as VALID, WARNING, or INVALID and returns the
reasons. INVALID products are not persisted; WARNING products are persisted
but flagged so they're easy to review later. Nothing here is manufacturer-
specific -- these are structural checks any AV product record must satisfy.
"""
from __future__ import annotations

from urllib.parse import urlparse

from core.models.product import CanonicalProduct, ValidationResult, ValidationStatus


class Validator:
    def validate(self, product: CanonicalProduct) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        if not product.manufacturer or not product.manufacturer.strip():
            errors.append("manufacturer is missing")

        if not product.name or not product.name.strip():
            errors.append("product name is missing")

        if not product.source_url or not self._is_valid_url(product.source_url):
            errors.append(f"source_url is missing or invalid: {product.source_url!r}")

        if not product.model and not product.sku:
            # Not fatal: the Deduplicator falls back to a name+source_url
            # hash identity for products with no model/SKU (see
            # `core/pipeline/deduplicator.py`), so these are still
            # persistable -- just worth flagging for review.
            warnings.append("both model and sku are missing; deduplication will use a name+URL fallback identity")

        if not product.category:
            warnings.append("category is missing")

        if not product.image_urls:
            warnings.append("no product images found")

        if not product.specifications:
            warnings.append("no specifications found")

        if product.description is None and product.short_description is None:
            warnings.append("no description found")

        if errors:
            return ValidationResult(status=ValidationStatus.INVALID, messages=errors + warnings)
        if warnings:
            return ValidationResult(status=ValidationStatus.WARNING, messages=warnings)
        return ValidationResult(status=ValidationStatus.VALID, messages=[])

    @staticmethod
    def _is_valid_url(value: str) -> bool:
        try:
            parsed = urlparse(value)
        except ValueError:
            return False
        return bool(parsed.scheme) and bool(parsed.netloc)
