from __future__ import annotations

from core.models.product import CanonicalProduct
from core.pipeline.deduplicator import DedupAction, Deduplicator


def make_product(dedup_key: str) -> CanonicalProduct:
    return CanonicalProduct(
        manufacturer="hdcvt",
        source_url="https://x/1",
        name="Widget",
        dedup_key=dedup_key,
    )


def test_new_key_is_create():
    decision = Deduplicator().resolve(make_product("hdcvt:model:a"), existing_ids_by_key={})
    assert decision.action == DedupAction.CREATE


def test_known_key_is_update():
    decision = Deduplicator().resolve(
        make_product("hdcvt:model:a"), existing_ids_by_key={"hdcvt:model:a": 42}
    )
    assert decision.action == DedupAction.UPDATE
    assert decision.existing_product_id == 42


def test_repeated_key_within_same_run_is_skipped():
    dedup = Deduplicator()
    first = dedup.resolve(make_product("hdcvt:model:a"), existing_ids_by_key={})
    second = dedup.resolve(make_product("hdcvt:model:a"), existing_ids_by_key={})

    assert first.action == DedupAction.CREATE
    assert second.action == DedupAction.SKIP_DUPLICATE_IN_RUN
