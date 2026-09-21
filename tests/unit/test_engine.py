"""Tests the generic engine (`sync_manufacturer_data`) end to end against a
fake manufacturer adapter -- proving the pipeline (crawl -> normalize ->
validate -> dedupe -> transform -> persist) works without any real
manufacturer or network access, and that it stays manufacturer-agnostic.
"""
from __future__ import annotations

from typing import Iterator

import pytest

from core.engine import sync_manufacturer_data
from core.models.job import JobStatus
from core.models.product import RawProduct
from core.registry import ManufacturerRegistry, UnknownManufacturerError
from db.database import session_scope
from db.repository import ProductRepository, SyncJobRepository
from manufacturers.base import BaseManufacturerAdapter, ManufacturerConfig


class FakeAdapter(BaseManufacturerAdapter):
    """2 good products + 1 that fails to fetch, to exercise per-item error
    isolation without touching a real website."""

    def discover_product_urls(self) -> Iterator[str]:
        yield "https://example.com/1"
        yield "https://example.com/2"
        yield "https://example.com/broken"

    def fetch_product(self, url: str) -> str:
        if "broken" in url:
            raise RuntimeError("simulated network failure")
        return url

    def parse(self, raw_content: str, source_url: str) -> RawProduct:
        idx = source_url.rsplit("/", 1)[-1]
        return RawProduct(
            manufacturer="faketest",
            source_url=source_url,
            name=f"Widget {idx}",
            model=f"MODEL-{idx}",
            category="Widgets",
            image_urls=["https://example.com/img.png"],
            specifications={"Color": "Black"},
        )


@pytest.fixture()
def fake_registry(monkeypatch):
    reg = ManufacturerRegistry()
    config = ManufacturerConfig(
        key="faketest",
        display_name="Fake Test Co",
        base_url="https://example.com",
        request_delay_seconds=0,
    )
    reg.register("faketest", FakeAdapter, config)
    monkeypatch.setattr("core.engine.registry", reg)
    return reg


def test_sync_creates_products_and_isolates_failures(fake_registry):
    result = sync_manufacturer_data(manufacturer="faketest")

    assert result.total == 3
    assert result.success == 2
    assert result.failed == 1
    assert result.status == JobStatus.COMPLETED_WITH_WARNINGS

    with session_scope() as session:
        products = ProductRepository(session).list_products(manufacturer="faketest")
        assert {p.model for p in products} >= {"MODEL-1", "MODEL-2"}


def test_sync_upserts_instead_of_duplicating_on_second_run(fake_registry):
    sync_manufacturer_data(manufacturer="faketest")
    sync_manufacturer_data(manufacturer="faketest")

    with session_scope() as session:
        products = ProductRepository(session).list_products(manufacturer="faketest", limit=1000)
        models = [p.model for p in products if p.model in ("MODEL-1", "MODEL-2")]
        # Same two dedup keys every run -> never duplicated, regardless of
        # how many times the sync has run across the test session.
        assert models.count("MODEL-1") == 1
        assert models.count("MODEL-2") == 1


def test_sync_tracks_job_status_end_to_end(fake_registry):
    with session_scope() as session:
        SyncJobRepository(session).create(job_id="job-engine-test", manufacturer="faketest", mode="full")

    sync_manufacturer_data(manufacturer="faketest", job_id="job-engine-test")

    with session_scope() as session:
        job = SyncJobRepository(session).get("job-engine-test")
        assert job.status == JobStatus.COMPLETED_WITH_WARNINGS.value
        assert job.total == 3
        assert job.success == 2
        assert job.failed == 1
        assert job.progress == 100.0
        assert job.started_at is not None
        assert job.completed_at is not None


def test_sync_unknown_manufacturer_raises(fake_registry):
    with pytest.raises(UnknownManufacturerError):
        sync_manufacturer_data(manufacturer="does-not-exist")


def test_incremental_mode_not_yet_implemented(fake_registry):
    with pytest.raises(NotImplementedError):
        sync_manufacturer_data(manufacturer="faketest", mode="incremental")


def test_sync_never_touches_google_sheets_when_unconfigured(fake_registry, monkeypatch):
    """Regression test: a real test run once silently created junk tabs in
    the production Google Sheet because GOOGLE_SPREADSHEET_ID leaked in
    from backend/.env. tests/conftest.py now force-clears it to "", and this
    asserts the engine honors that by never even constructing the exporter.
    """
    import core.engine as engine_module

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("GoogleSheetsExporter must not be constructed when unconfigured")

    monkeypatch.setattr(engine_module, "GoogleSheetsExporter", _fail_if_called)
    assert not engine_module.settings.google_spreadsheet_id

    result = sync_manufacturer_data(manufacturer="faketest")

    assert result.status == JobStatus.COMPLETED_WITH_WARNINGS
