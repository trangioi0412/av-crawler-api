"""Tests the generic engine (`sync_manufacturer_data`) end to end against a
fake manufacturer adapter and a fake Google Sheets spreadsheet -- proving
the pipeline (crawl -> normalize -> validate -> dedupe -> transform ->
persist) works without any real manufacturer, network access, or Google
credentials, and that it stays manufacturer-agnostic.
"""
from __future__ import annotations

from typing import Iterator

import pytest

from core.engine import sync_manufacturer_data
from core.models.job import JobStatus
from core.models.product import RawProduct
from core.registry import ManufacturerRegistry, UnknownManufacturerError
from manufacturers.base import BaseManufacturerAdapter, ManufacturerConfig
from services import job_store


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
    monkeypatch.setattr("core.manufacturer_resolution.registry", reg)
    return reg


def _sheet_rows(fake_spreadsheet, tab: str = "faketest") -> list[dict[str, str]]:
    ws = fake_spreadsheet.worksheet(tab)
    values = ws.get_all_values()
    header, body = values[0], values[1:]
    return [dict(zip(header, row)) for row in body]


def test_sync_creates_products_and_isolates_failures(fake_registry, fake_spreadsheet):
    result = sync_manufacturer_data(manufacturer="faketest")

    assert result.total == 3
    assert result.success == 2
    assert result.failed == 1
    assert result.status == JobStatus.COMPLETED_WITH_WARNINGS

    models = {r["product (item)"] for r in _sheet_rows(fake_spreadsheet)}
    assert models >= {"MODEL-1", "MODEL-2"}


def test_sync_upserts_instead_of_duplicating_on_second_run(fake_registry, fake_spreadsheet):
    sync_manufacturer_data(manufacturer="faketest")
    sync_manufacturer_data(manufacturer="faketest")

    models = [r["product (item)"] for r in _sheet_rows(fake_spreadsheet) if r["product (item)"] in ("MODEL-1", "MODEL-2")]
    # Same two natural keys every run -> the sheet row is updated in place,
    # never duplicated, regardless of how many times the sync has run.
    assert models.count("MODEL-1") == 1
    assert models.count("MODEL-2") == 1


def test_sync_tracks_job_status_end_to_end(fake_registry, fake_spreadsheet):
    job_store.create(job_id="job-engine-test", manufacturer="faketest", mode="full")

    sync_manufacturer_data(manufacturer="faketest", job_id="job-engine-test")

    job = job_store.get("job-engine-test")
    assert job.status == JobStatus.COMPLETED_WITH_WARNINGS.value
    assert job.total == 3
    assert job.success == 2
    assert job.failed == 1
    assert job.progress == 100.0
    assert job.started_at is not None
    assert job.completed_at is not None


def test_sync_unknown_manufacturer_raises(fake_registry, fake_spreadsheet):
    with pytest.raises(UnknownManufacturerError):
        sync_manufacturer_data(manufacturer="does-not-exist")


def test_incremental_mode_not_yet_implemented(fake_registry, fake_spreadsheet):
    with pytest.raises(NotImplementedError):
        sync_manufacturer_data(manufacturer="faketest", mode="incremental")


def test_sync_fails_cleanly_when_google_sheets_unconfigured(fake_registry, fake_spreadsheet, monkeypatch):
    """Regression guard: Google Sheets is the only persistence layer now,
    so a missing GOOGLE_SPREADSHEET_ID must surface as a failed job with a
    clear error -- not a silent no-op (that was the old, SQLite-backed
    behavior, back when Sheets export was best-effort/supplementary).
    """
    monkeypatch.setattr("core.engine.settings.google_spreadsheet_id", "")

    result = sync_manufacturer_data(manufacturer="faketest")

    assert result.status == JobStatus.FAILED
    assert "Google Sheets" in (result.error or "")
