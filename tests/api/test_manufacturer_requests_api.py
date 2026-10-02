"""Tests for the "Yeu cau them hang moi" (request a new manufacturer)
intake endpoints -- tracked entirely in the DataCrawler_New_brand Google Sheet, no
database (see api/routes/manufacturer_requests.py).

`probe_manufacturer_website` (the auto-recon step) and `GenericAIAdapter`
(both where `/preview` uses it directly, and where `resolve_manufacturer`
picks it up for the real sync `/approve` kicks off) are monkeypatched in
every test: a real one would make real HTTP requests to whatever website a
user submits, and hit a real Ollama server.
"""
from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient

import api.routes.manufacturer_requests as manufacturer_requests_module
import core.manufacturer_resolution as manufacturer_resolution_module
from core.models.product import RawProduct
from main import app
from services.admin_sheets import NewBrandStatus


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
    # /preview calls GenericAIAdapter directly from this module...
    monkeypatch.setattr(manufacturer_requests_module, "GenericAIAdapter", FakeAiAdapter)
    # ...but /approve's actual sync goes through resolve_manufacturer(),
    # which imports GenericAIAdapter into its own module namespace.
    monkeypatch.setattr(manufacturer_resolution_module, "GenericAIAdapter", FakeAiAdapter)


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
    assert body["id"] == "yealink"
    assert body["name"] == "Yealink"
    assert body["website_url"] == "https://yealink.com"
    assert body["status"] == NewBrandStatus.PENDING
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
        json={"status": NewBrandStatus.CRAWLING, "notes": "Adapter under review"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == NewBrandStatus.CRAWLING
    assert body["notes"] == "Adapter under review"


def test_update_status_rejects_invalid_status(client: TestClient):
    created = client.post(
        "/api/manufacturer-requests", json={"name": "Extron", "website_url": "extron.com"}
    ).json()
    response = client.patch(f"/api/manufacturer-requests/{created['id']}", json={"status": "bogus"})
    assert response.status_code == 400


def test_update_status_unknown_id_returns_404(client: TestClient):
    response = client.patch(
        "/api/manufacturer-requests/does-not-exist", json={"status": NewBrandStatus.DONE}
    )
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


def test_preview_does_not_register_the_manufacturer(client: TestClient, fake_spreadsheet):
    created = client.post(
        "/api/manufacturer-requests", json={"name": "AI Not Registered Co", "website_url": "example.com"}
    ).json()

    client.post(f"/api/manufacturer-requests/{created['id']}/preview")

    # Preview must not write DataCrawler_System_Config or create a product sheet tab.
    assert "ai-not-registered-co" not in [ws.title for ws in fake_spreadsheet.worksheets()]


def test_preview_unknown_request_returns_404(client: TestClient):
    response = client.post("/api/manufacturer-requests/does-not-exist/preview")
    assert response.status_code == 404


def _rows_of(fake_spreadsheet, tab: str) -> list[dict[str, str]]:
    values = fake_spreadsheet.worksheet(tab).get_all_values()
    header, body = values[0], values[1:]
    return [dict(zip(header, row)) for row in body]


def test_approve_records_website_and_completes_sync(client: TestClient, fake_spreadsheet):
    created = client.post(
        "/api/manufacturer-requests", json={"name": "AI Approve Co", "website_url": "example.com"}
    ).json()

    response = client.post(f"/api/manufacturer-requests/{created['id']}/approve")

    assert response.status_code == 202
    body = response.json()
    assert body["manufacturer_key"] == "ai-approve-co"
    job_id = body["job_id"]

    status = client.get(f"/api/sync/status/{job_id}").json()
    assert status["status"] in ("completed", "completed_with_warnings")
    assert status["total"] == 2
    assert status["success"] == 2

    # DataCrawler_System_Config durably knows this brand's website from here on...
    slugs = {row["Slug"] for row in _rows_of(fake_spreadsheet, "DataCrawler_System_Config")}
    assert "ai-approve-co" in slugs

    # ...so the DataCrawler_New_brand row is gone once onboarding finished.
    remaining = client.get("/api/manufacturer-requests").json()
    assert all(r["id"] != "ai-approve-co" for r in remaining)


def test_approve_unknown_request_returns_404(client: TestClient):
    response = client.post("/api/manufacturer-requests/does-not-exist/approve")
    assert response.status_code == 404
