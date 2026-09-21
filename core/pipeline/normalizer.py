"""Generic normalization layer.

Turns a manufacturer's RawProduct (already mapped onto canonical field names
by the adapter) into a CanonicalProduct: trimmed whitespace, absolute URLs,
de-duplicated lists, and a deterministic `dedup_key`. Nothing here knows
about any specific manufacturer's HTML or terminology -- that translation
already happened in the adapter's `parse()`.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin, urlparse

from core.models.product import CanonicalProduct, RawProduct

_WHITESPACE_RE = re.compile(r"\s+")


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _WHITESPACE_RE.sub(" ", value).strip()
    return cleaned or None


def _normalize_url(url: str | None, base_url: str) -> str | None:
    if not url:
        return None
    url = url.strip()
    if not url:
        return None
    absolute = urljoin(base_url, url)
    parsed = urlparse(absolute)
    if not parsed.scheme or not parsed.netloc:
        return None
    return absolute


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _normalize_category(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    return cleaned.strip().title()


def build_dedup_key(manufacturer: str, model: str | None, name: str | None, source_url: str) -> str:
    """Deterministic identity for a product.

    Primary strategy: manufacturer + normalized model/SKU, since that's the
    closest thing to a stable manufacturer identifier across re-crawls.
    Fallback (when no model is available): manufacturer + a hash of the
    normalized name and source URL, so products without a model number are
    still deduplicated consistently across syncs instead of relying on
    product name alone (which changes with copy edits).
    """
    manufacturer_key = manufacturer.strip().lower()
    if model:
        model_key = re.sub(r"[^a-z0-9]+", "", model.strip().lower())
        if model_key:
            return f"{manufacturer_key}:model:{model_key}"

    basis = f"{(name or '').strip().lower()}|{source_url.strip().lower()}"
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]
    return f"{manufacturer_key}:hash:{digest}"


class Normalizer:
    def normalize(self, raw: RawProduct, *, base_url: str) -> CanonicalProduct:
        name = _clean_text(raw.name)
        model = _clean_text(raw.model)
        sku = _clean_text(raw.sku)

        image_urls = _dedupe_preserve_order(
            [u for u in (_normalize_url(u, base_url) for u in raw.image_urls) if u]
        )
        document_urls = _dedupe_preserve_order(
            [u for u in (_normalize_url(u, base_url) for u in raw.document_urls) if u]
        )
        product_url = _normalize_url(raw.source_url, base_url) or raw.source_url

        specifications = {
            _clean_text(k) or k: _clean_text(v) if isinstance(v, str) else v
            for k, v in raw.specifications.items()
        }

        dedup_key = build_dedup_key(raw.manufacturer, model or sku, name, raw.source_url)

        return CanonicalProduct(
            manufacturer=raw.manufacturer,
            brand=raw.manufacturer,
            source_url=product_url,
            name=name,
            model=model,
            sku=sku,
            category=_normalize_category(raw.category),
            subcategory=_normalize_category(raw.subcategory),
            description=_clean_text(raw.description),
            short_description=_clean_text(raw.short_description),
            image_urls=image_urls,
            document_urls=document_urls,
            specifications=specifications,
            features=_dedupe_preserve_order([_clean_text(f) or "" for f in raw.features]),
            status=raw.status or "active",
            source="web_crawl",
            raw=raw.raw,
            dedup_key=dedup_key,
        )
