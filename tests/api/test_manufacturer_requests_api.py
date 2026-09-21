"""Tests for the "request a new manufacturer" intake endpoints. These just
queue a name/website in the database -- no adapter registration or
crawling happens here.

`probe_manufacturer_website` (the auto-recon step) is monkeypatched to a
fast stub in every test: it makes real HTTP requests to whatever website a
user submits, and a test run must never depend on real, external websites
being reachable (this bit us once already with Google Sheets -- see
tests/conftest.py -- not repeating it here).
"""
from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient

import api.routes.manufacturer_requests as manufacturer_requests_module
from core.models.product import RawProduct
from core.registry import registry
from main import app


@pytest.fixture(autouse=True)
def _stub_recon(monkeypatch):
    monkeypatch.setattr(
        manufacturer_requests_module,
        "probe_manufacturer_website",
        lambda url: _StubReconResult(),
    )


class _StubReconResult:
    def to_notes(self) -> str:
        return "Kiểm tra sơ bộ tự động: (stub cho test)"


class FakeAiAdapter:
    """Stands in for GenericAIAdapter so preview/approve tests never touch
    a real website or a real Ollama server.
    """

    def __init__(self, config, http_client) -> None:
        self.config = config
        self.http = http_client

    def discover_product_urls(self):
        yield "https://example.com/products/a.html"
        yield "https://example.com/products/b.html"

    def crawl_urls(self, urls):
        from core.models.product import CrawlResult

        for i, url in enumerate(urls):
            slug = url.rsplit("/", 1)[-1]
            yield CrawlResult(
                source_url=url,
                raw_product=RawProduct(
                    manufacturer=self.config.key,
                    source_url=url,
                    name=f"Fake AI Product ({slug})",
                    model=f"FAKE-{i + 1}",
                    category="Test",
                    image_urls=["https://example.com/img.png"],
                    specifications={"Color": "Blue"},
                ),
            )


@pytest.fixture(autouse=True)
def _stub_ai_adapter(monkeypatch):
    monkeypatch.setattr(manufacturer_requests_module, "GenericAIAdapter", FakeAiAdapter)


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def test_create_request_normalizes_bare_domain_to_https(client: TestClient):
    response = client.post(
        "/api/manufacturer-requests", json={"name": "Yealink", "website_url": "yealink.com"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Yealink"
    assert body["website_url"] == "https://yealink.com"
    assert body["status"] == "pending"
    assert "Kiểm tra sơ bộ" in body["notes"]


def test_create_request_requires_website(client: TestClient):
    response = client.post("/api/manufacturer-requests", json={"name": "Some Brand"})
    assert response.status_code == 422  # pydantic: website_url is a required field


def test_create_request_rejects_blank_website(client: TestClient):
    response = client.post("/api/manufacturer-requests", json={"name": "Some Brand", "website_url": "   "})
    assert response.status_code == 400


def test_create_request_rejects_blank_name(client: TestClient):
    response = client.post(
        "/api/manufacturer-requests", json={"name": "   ", "website_url": "example.com"}
    )
    assert response.status_code == 400


def test_list_requests_includes_created_ones(client: TestClient):
    client.post("/api/manufacturer-requests", json={"name": "Logitech", "website_url": "logitech.com"})
    response = client.get("/api/manufacturer-requests")
    assert response.status_code == 200
    names = {r["name"] for r in response.json()}
    assert "Logitech" in names


def test_update_status_transitions_request(client: TestClient):
    created = client.post(
        "/api/manufacturer-requests", json={"name": "Cisco", "website_url": "cisco.com"}
    ).json()

    response = client.patch(
        f"/api/manufacturer-requests/{created['id']}",
        json={"status": "in_progress", "notes": "Adapter under review"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "in_progress"
    assert body["notes"] == "Adapter under review"


def test_update_status_rejects_invalid_status(client: TestClient):
    created = client.post(
        "/api/manufacturer-requests", json={"name": "Extron", "website_url": "extron.com"}
    ).json()
    response = client.patch(f"/api/manufacturer-requests/{created['id']}", json={"status": "bogus"})
    assert response.status_code == 400


def test_update_status_unknown_id_returns_404(client: TestClient):
    response = client.patch("/api/manufacturer-requests/999999", json={"status": "done"})
    assert response.status_code == 404


def test_preview_returns_extracted_sample_products(client: TestClient):
    created = client.post(
        "/api/manufacturer-requests", json={"name": "AI Preview Co", "website_url": "example.com"}
    ).json()

    response = client.post(f"/api/manufacturer-requests/{created['id']}/preview")

    assert response.status_code == 200
    body = response.json()
    assert body["manufacturer_key"] == "ai-preview-co"
    assert body["checked_urls"] == 2
    assert len(body["products"]) == 2
    assert body["products"][0]["ok"] is True
    assert body["products"][0]["model"] == "FAKE-1"


def test_preview_does_not_register_the_manufacturer(client: TestClient):
    created = client.post(
        "/api/manufacturer-requests", json={"name": "AI Not Registered Co", "website_url": "example.com"}
    ).json()

    client.post(f"/api/manufacturer-requests/{created['id']}/preview")

    assert registry.is_registered("ai-not-registered-co") is False


def test_preview_unknown_request_returns_404(client: TestClient):
    response = client.post("/api/manufacturer-requests/999999/preview")
    assert response.status_code == 404


def test_approve_registers_manufacturer_and_completes_sync(client: TestClient):
    created = client.post(
        "/api/manufacturer-requests", json={"name": "AI Approve Co", "website_url": "example.com"}
    ).json()

    response = client.post(f"/api/manufacturer-requests/{created['id']}/approve")

    assert response.status_code == 202
    body = response.json()
    assert body["manufacturer_key"] == "ai-approve-co"
    job_id = body["job_id"]

    assert registry.is_registered("ai-approve-co") is True

    status = client.get(f"/api/sync/status/{job_id}").json()
    assert status["status"] in ("completed", "completed_with_warnings")
    assert status["total"] == 2
    assert status["success"] == 2

    updated_request = client.get("/api/manufacturer-requests").json()
    match = next(r for r in updated_request if r["id"] == created["id"])
    assert match["status"] == "done"
    assert match["ai_sync_enabled"] is True


def test_approve_unknown_request_returns_404(client: TestClient):
    response = client.post("/api/manufacturer-requests/999999/approve")
    assert response.status_code == 404
