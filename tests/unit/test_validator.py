from __future__ import annotations

from core.models.product import CanonicalProduct, ValidationStatus
from core.pipeline.validator import Validator


def make_product(**overrides) -> CanonicalProduct:
    defaults = dict(
        manufacturer="hdcvt",
        source_url="https://www.hdcvt.com/p/1.html",
        name="HDBaseT Extender (70m)",
        model="HBT-E70S",
        category="Extenders",
        image_urls=["https://www.hdcvt.com/static/a.png"],
        specifications={"Power Supply": "DC 24V 1A"},
        description="A great extender.",
        dedup_key="hdcvt:model:hbte70s",
    )
    defaults.update(overrides)
    return CanonicalProduct(**defaults)


def test_fully_populated_product_is_valid():
    result = Validator().validate(make_product())
    assert result.status == ValidationStatus.VALID
    assert result.messages == []


def test_missing_name_is_invalid():
    result = Validator().validate(make_product(name=None))
    assert result.status == ValidationStatus.INVALID
    assert any("name" in m for m in result.messages)


def test_missing_model_and_sku_is_warning_not_invalid():
    # Not fatal: the Deduplicator has a name+URL hash fallback identity for
    # exactly this case, so these products must still be persistable.
    result = Validator().validate(make_product(model=None, sku=None))
    assert result.status == ValidationStatus.WARNING
    assert result.is_persistable


def test_missing_source_url_is_invalid():
    result = Validator().validate(make_product(source_url=""))
    assert result.status == ValidationStatus.INVALID


def test_missing_images_is_warning_not_invalid():
    result = Validator().validate(make_product(image_urls=[]))
    assert result.status == ValidationStatus.WARNING
    assert any("image" in m for m in result.messages)
    assert result.is_persistable


def test_invalid_product_is_not_persistable():
    result = Validator().validate(make_product(name=None))
    assert result.is_persistable is False
