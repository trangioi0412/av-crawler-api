"""API-level test for POST /api/images/download."""
from __future__ import annotations

from typing import Iterator

import pytest
import responses
from fastapi.testclient import TestClient

from main import app
from tests.fake_sheets import FakeSpreadsheet


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@responses.activate
def test_download_images_writes_files_and_reports_counts(client: TestClient, fake_spreadsheet: FakeSpreadsheet, tmp_path, monkeypatch):
    monkeypatch.setattr("api.routes.images.DATA_DIR", tmp_path)
    responses.add(responses.GET, "https://example.com/a.jpg", body=b"IMG-A", content_type="image/jpeg")

    fake_spreadsheet.seed_rows(
        "hdcvt",
        ["Category", "Product", "Title", "product (item)", "Series", "Main Feature", "Product Overview",
         "Technical Specifications", "image", "Brand", "Datasheet"],
        [{"Title": "Widget", "image": "https://example.com/a.jpg"}],
    )

    response = client.post("/api/images/download", params={"manufacturer": "hdcvt"})

    assert response.status_code == 200
    body = response.json()
    assert body["manufacturer"] == "hdcvt"
    assert body["downloaded"] == 1
    assert body["failed"] == []
    assert (tmp_path / "hdcvt" / "Widget.jpg").read_bytes() == b"IMG-A"


def test_download_images_passes_the_manufacturers_ca_bundle_path_when_registered(
    client: TestClient, fake_spreadsheet: FakeSpreadsheet, tmp_path, monkeypatch
):
    """Regression: eizo's image downloads used to fail with
    SSLCertVerificationError because this route never looked up eizo's
    own `ca_bundle_path` (see manufacturers/eizo/ca_bundle.py) before
    calling the downloader -- see also test_image_downloader.py's
    test_passes_ca_bundle_path_to_the_requests_session.
    """
    monkeypatch.setattr("api.routes.images.DATA_DIR", tmp_path)
    fake_spreadsheet.seed_rows("eizo", ["Title", "image"], [])

    captured: dict[str, object] = {}

    def fake_download(exporter, manufacturer, data_dir, *, ca_bundle_path=None):
        captured["manufacturer"] = manufacturer
        captured["ca_bundle_path"] = ca_bundle_path
        from services.image_downloader import ImageDownloadResult

        return ImageDownloadResult(manufacturer=manufacturer)

    monkeypatch.setattr("api.routes.images.download_manufacturer_images", fake_download)

    response = client.post("/api/images/download", params={"manufacturer": "eizo"})

    assert response.status_code == 200
    assert captured["manufacturer"] == "eizo"
    assert captured["ca_bundle_path"] is not None  # EIZO_CONFIG.ca_bundle_path, a real generated bundle file


def test_download_images_passes_no_ca_bundle_for_a_sheet_only_manufacturer(
    client: TestClient, fake_spreadsheet: FakeSpreadsheet, tmp_path, monkeypatch
):
    """A manufacturer with no code adapter (only a sheet tab) has no
    ManufacturerConfig to look up -- must not error, and must pass None.
    """
    monkeypatch.setattr("api.routes.images.DATA_DIR", tmp_path)
    fake_spreadsheet.seed_rows("vissonic-clone-not-registered", ["Title", "image"], [])

    captured: dict[str, object] = {}

    def fake_download(exporter, manufacturer, data_dir, *, ca_bundle_path=None):
        captured["ca_bundle_path"] = ca_bundle_path
        from services.image_downloader import ImageDownloadResult

        return ImageDownloadResult(manufacturer=manufacturer)

    monkeypatch.setattr("api.routes.images.download_manufacturer_images", fake_download)

    response = client.post("/api/images/download", params={"manufacturer": "vissonic-clone-not-registered"})

    assert response.status_code == 200
    assert captured["ca_bundle_path"] is None
