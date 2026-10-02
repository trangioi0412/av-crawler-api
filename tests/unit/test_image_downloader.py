"""Unit tests for the image-download service. Never touches a real
spreadsheet or the network -- `FakeExporter` stands in for
`GoogleSheetsExporter` (only `.get_rows` is used) and `responses` mocks
the image HTTP requests.
"""
from __future__ import annotations

from pathlib import Path

import responses

from services.image_downloader import download_manufacturer_images


class FakeExporter:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self._rows = rows

    def get_rows(self, tab_name: str) -> list[dict[str, str]]:
        return self._rows


@responses.activate
def test_passes_ca_bundle_path_to_the_requests_session(tmp_path: Path, monkeypatch):
    """Regression: this service used to build its own bare
    `requests.Session()`, so a manufacturer whose image host needs the
    `ca_bundle_path` fix (see manufacturers/eizo/ca_bundle.py) had every
    download fail with SSLCertVerificationError even though the sync
    adapter's own CrawlHttpClient -- which does get this fix -- worked.
    """
    responses.add(responses.GET, "https://example.com/a.jpg", body=b"IMG-A", content_type="image/jpeg")
    exporter = FakeExporter([{"Title": "Widget", "image": "https://example.com/a.jpg"}])

    seen_verify: list[object] = []
    import requests

    original_init = requests.Session.__init__

    def spy_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        seen_verify.append(self)

    monkeypatch.setattr(requests.Session, "__init__", spy_init)

    download_manufacturer_images(exporter, "eizo", tmp_path, ca_bundle_path="/combined-ca-bundle.pem")

    assert len(seen_verify) == 1
    assert seen_verify[0].verify == "/combined-ca-bundle.pem"


@responses.activate
def test_downloads_each_image_with_windows_style_suffix(tmp_path: Path):
    responses.add(responses.GET, "https://example.com/a.jpg", body=b"IMG-A", content_type="image/jpeg")
    responses.add(responses.GET, "https://example.com/b.jpg", body=b"IMG-B", content_type="image/jpeg")

    exporter = FakeExporter(
        [{"Title": "SDVoE ( 1 0 G )", "image": "https://example.com/a.jpg\nhttps://example.com/b.jpg"}]
    )

    result = download_manufacturer_images(exporter, "hdcvt", tmp_path)

    assert result.downloaded == 2
    assert result.products_with_images == 1
    dest_dir = tmp_path / "hdcvt"
    assert (dest_dir / "Sdvoe_(_1_0_G_).jpg").read_bytes() == b"IMG-A"
    assert (dest_dir / "Sdvoe_(_1_0_G_)_(1).jpg").read_bytes() == b"IMG-B"


@responses.activate
def test_skips_rows_with_no_image_column(tmp_path: Path):
    exporter = FakeExporter([{"Title": "No Images Here", "image": ""}])

    result = download_manufacturer_images(exporter, "hdcvt", tmp_path)

    assert result.products_with_images == 0
    assert result.downloaded == 0
    assert not (tmp_path / "hdcvt").exists() or list((tmp_path / "hdcvt").iterdir()) == []


@responses.activate
def test_skips_images_with_no_title_to_name_them_from(tmp_path: Path):
    exporter = FakeExporter([{"Title": "", "product (item)": "", "image": "https://example.com/a.jpg"}])

    result = download_manufacturer_images(exporter, "hdcvt", tmp_path)

    assert result.products_with_images == 1
    assert result.skipped_no_title == 1
    assert result.downloaded == 0
    assert len(responses.calls) == 0


@responses.activate
def test_does_not_redownload_an_existing_file(tmp_path: Path):
    dest_dir = tmp_path / "hdcvt"
    dest_dir.mkdir(parents=True)
    (dest_dir / "Widget.jpg").write_bytes(b"already-here")

    exporter = FakeExporter([{"Title": "Widget", "image": "https://example.com/a.jpg"}])

    result = download_manufacturer_images(exporter, "hdcvt", tmp_path)

    assert result.skipped_existing == 1
    assert result.downloaded == 0
    assert len(responses.calls) == 0
    assert (dest_dir / "Widget.jpg").read_bytes() == b"already-here"


@responses.activate
def test_records_failed_downloads_without_aborting_the_rest(tmp_path: Path):
    responses.add(responses.GET, "https://example.com/broken.jpg", status=404)
    responses.add(responses.GET, "https://example.com/ok.jpg", body=b"IMG-OK", content_type="image/jpeg")

    exporter = FakeExporter(
        [{"Title": "Widget", "image": "https://example.com/broken.jpg\nhttps://example.com/ok.jpg"}]
    )

    result = download_manufacturer_images(exporter, "hdcvt", tmp_path)

    assert result.downloaded == 1
    assert len(result.failed) == 1
    assert "https://example.com/broken.jpg" in result.failed[0]
    assert (tmp_path / "hdcvt" / "Widget_(1).jpg").read_bytes() == b"IMG-OK"
