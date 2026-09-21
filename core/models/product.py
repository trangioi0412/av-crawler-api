"""Manufacturer-independent product data model.

Three shapes flow through the pipeline:

- `RawProduct`   -- whatever an adapter scraped, already mapped onto the
                     canonical field names (adapters are responsible for
                     translating manufacturer-specific terminology).
- `CanonicalProduct` -- output of the generic Normalizer. Same shape as
                     `RawProduct` but cleaned (trimmed text, absolute URLs,
                     de-duplicated lists) and carries a `dedup_key`.
- `ValidationResult` -- output of the generic Validator.

None of these types know anything about HDCVT, Yealink, Cisco, etc.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


@dataclass
class RawProduct:
    manufacturer: str
    source_url: str
    name: str | None = None
    model: str | None = None
    sku: str | None = None
    category: str | None = None
    subcategory: str | None = None
    description: str | None = None
    short_description: str | None = None
    image_urls: list[str] = field(default_factory=list)
    document_urls: list[str] = field(default_factory=list)
    specifications: dict[str, Any] = field(default_factory=dict)
    features: list[str] = field(default_factory=list)
    status: str = "active"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalProduct(RawProduct):
    """Same fields as RawProduct, plus a deterministic identity key."""

    brand: str | None = None
    source: str = "web_crawl"
    dedup_key: str = ""


class ValidationStatus(str, Enum):
    VALID = "VALID"
    WARNING = "WARNING"
    INVALID = "INVALID"


@dataclass
class ValidationResult:
    status: ValidationStatus
    messages: list[str] = field(default_factory=list)

    @property
    def is_persistable(self) -> bool:
        return self.status != ValidationStatus.INVALID


@dataclass
class CrawlResult:
    """Wraps one adapter.crawl() item so a single bad product can't raise
    an exception through the generator and abort the whole sync."""

    source_url: str
    raw_product: RawProduct | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.raw_product is not None
