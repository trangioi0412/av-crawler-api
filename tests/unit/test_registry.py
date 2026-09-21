from __future__ import annotations

from typing import Iterator

import pytest

from core.models.product import CrawlResult, RawProduct
from core.registry import ManufacturerRegistry, UnknownManufacturerError
from manufacturers.base import BaseManufacturerAdapter, ManufacturerConfig


class DummyAdapter(BaseManufacturerAdapter):
    def discover_product_urls(self) -> Iterator[str]:
        yield "https://example.com/product/1"

    def fetch_product(self, url: str) -> str:
        return "<html></html>"

    def parse(self, raw_content: str, source_url: str) -> RawProduct:
        return RawProduct(manufacturer="dummy", source_url=source_url, name="Widget")


def make_config(key: str = "dummy") -> ManufacturerConfig:
    return ManufacturerConfig(key=key, display_name="Dummy Inc.", base_url="https://example.com")


def test_register_and_get_returns_adapter_instance():
    registry = ManufacturerRegistry()
    registry.register("dummy", DummyAdapter, make_config())

    adapter = registry.get("dummy")

    assert isinstance(adapter, DummyAdapter)
    assert adapter.config.key == "dummy"


def test_get_is_case_insensitive():
    registry = ManufacturerRegistry()
    registry.register("dummy", DummyAdapter, make_config())

    adapter = registry.get("DUMMY")

    assert isinstance(adapter, DummyAdapter)


def test_get_unknown_manufacturer_raises_with_known_list():
    registry = ManufacturerRegistry()
    registry.register("dummy", DummyAdapter, make_config())

    with pytest.raises(UnknownManufacturerError) as exc_info:
        registry.get("does-not-exist")

    assert exc_info.value.known == ["dummy"]


def test_register_duplicate_key_raises():
    registry = ManufacturerRegistry()
    registry.register("dummy", DummyAdapter, make_config())

    with pytest.raises(ValueError):
        registry.register("dummy", DummyAdapter, make_config())


def test_list_manufacturers_returns_all_configs():
    registry = ManufacturerRegistry()
    registry.register("dummy-a", DummyAdapter, make_config("dummy-a"))
    registry.register("dummy-b", DummyAdapter, make_config("dummy-b"))

    keys = {c.key for c in registry.list_manufacturers()}

    assert keys == {"dummy-a", "dummy-b"}


def test_base_adapter_crawl_isolates_per_item_failures():
    class FlakyAdapter(BaseManufacturerAdapter):
        def discover_product_urls(self) -> Iterator[str]:
            yield "https://example.com/ok"
            yield "https://example.com/broken"

        def fetch_product(self, url: str) -> str:
            if "broken" in url:
                raise RuntimeError("boom")
            return "<html></html>"

        def parse(self, raw_content: str, source_url: str) -> RawProduct:
            return RawProduct(manufacturer="dummy", source_url=source_url, name="Widget")

    registry = ManufacturerRegistry()
    registry.register("flaky", FlakyAdapter, make_config("flaky"))
    adapter = registry.get("flaky")

    results: list[CrawlResult] = list(adapter.crawl())

    assert len(results) == 2
    assert results[0].ok is True
    assert results[1].ok is False
    assert "boom" in (results[1].error or "")
