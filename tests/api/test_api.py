"""API-level tests for the generic endpoints: /health, POST
/api/sync/manufacturer, GET /api/sync/status/{job_id}.

Registers a fake, network-free manufacturer adapter so these tests never
call the real HDCVT website -- see `ApiTestAdapter` below. FastAPI's
TestClient runs BackgroundTasks synchronously, so a posted sync job is
already in a terminal state by the time we poll its status.
"""
from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from core.models.product import RawProduct
from core.registry import registry
from manufacturers.base import BaseManufacturerAdapter, ManufacturerConfig


class ApiTestAdapter(BaseManufacturerAdapter):
    def discover_product_urls(self) -> Iterator[str]:
        yield "https://example.com/1"

    def fetch_product(self, url: str) -> str:
        return url

    def parse(self, raw_content: str, source_url: str) -> RawProduct:
        return RawProduct(
            manufacturer="apitest",
            source_url=source_url,
            name="API Test Widget",
            model="API-1",
            category="Test",
            image_urls=["https://example.com/img.png"],
            specifications={"Color": "Blue"},
        )


if not registry.is_registered("apitest"):
    registry.register(
        "apitest",
        ApiTestAdapter,
        ManufacturerConfig(
            key="apitest",
            display_name="API Test Co",
            base_url="https://example.com",
            request_delay_seconds=0,
        ),
    )

from main import app  # noqa: E402 - import after test adapter registration


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def test_health_check(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_manufacturers_includes_hdcvt_and_test_adapter(client: TestClient):
    response = client.get("/api/manufacturers")
    assert response.status_code == 200
    keys = {m["key"] for m in response.json()}
    assert "hdcvt" in keys
    assert "apitest" in keys


def test_start_sync_unknown_manufacturer_returns_400(client: TestClient):
    response = client.post("/api/sync/manufacturer", json={"manufacturer": "does-not-exist"})
    assert response.status_code == 400


def test_start_sync_and_poll_status_reaches_terminal_state(client: TestClient):
    response = client.post("/api/sync/manufacturer", json={"manufacturer": "apitest"})
    assert response.status_code == 202
    body = response.json()
    job_id = body["job_id"]
    assert body["status"] == "queued"
    assert body["manufacturer"] == "apitest"

    status_response = client.get(f"/api/sync/status/{job_id}")
    assert status_response.status_code == 200
    status = status_response.json()
    assert status["status"] in ("completed", "completed_with_warnings", "failed")
    assert status["manufacturer"] == "apitest"
    assert status["total"] == 1


def test_sync_status_unknown_job_returns_404(client: TestClient):
    response = client.get("/api/sync/status/does-not-exist")
    assert response.status_code == 404
