"""Deterministic deduplication.

Identity strategy (documented here since it drives persistence behavior):
  1. `manufacturer + normalized model/SKU` when a model or SKU was scraped --
     this is the closest thing to a stable manufacturer-assigned identifier.
  2. `manufacturer + sha1(normalized name + source_url)` when no model/SKU
     is available, so products are still deduplicated consistently across
     re-syncs without relying on product *name* alone (copy edits on the
     manufacturer's site would otherwise create duplicate rows).

The actual key is computed once, in `Normalizer.build_dedup_key`, and stored
on `CanonicalProduct.dedup_key`. This module only decides what to *do* with
a given key: create a new record, update an existing one, or skip a
duplicate seen earlier in the same crawl (e.g. a product listed under two
categories).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.models.product import CanonicalProduct


class DedupAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    SKIP_DUPLICATE_IN_RUN = "skip_duplicate_in_run"


@dataclass
class DedupDecision:
    action: DedupAction
    dedup_key: str
    existing_product_id: int | None = None


class Deduplicator:
    """One instance per sync run -- it tracks keys seen so far in *this*
    crawl in addition to consulting the pre-existing DB index, so duplicate
    listings within a single sync are caught too.
    """

    def __init__(self) -> None:
        self._seen_in_run: set[str] = set()

    def resolve(self, product: CanonicalProduct, existing_ids_by_key: dict[str, int]) -> DedupDecision:
        key = product.dedup_key
        if key in self._seen_in_run:
            return DedupDecision(action=DedupAction.SKIP_DUPLICATE_IN_RUN, dedup_key=key)
        self._seen_in_run.add(key)

        existing_id = existing_ids_by_key.get(key)
        if existing_id is not None:
            return DedupDecision(action=DedupAction.UPDATE, dedup_key=key, existing_product_id=existing_id)
        return DedupDecision(action=DedupAction.CREATE, dedup_key=key)
