"""Downloads each product's sheet images to a local `Data/` folder.

Google Sheets is this service's only persistence layer (see
`google_sheets.py`); the "image" column holds newline-separated image
URLs per product (`CanonicalProduct.image_urls`). This pulls those URLs
down to disk into `Data/<manufacturer>/` -- one subfolder per brand sheet
tab so two brands can't collide on the same product title -- named per
`core.image_naming.build_image_filename`.

Re-running is cheap: a file already on disk under its deterministic name
is left alone rather than re-downloaded (see `skipped_existing`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import requests

from core.image_naming import build_image_filename
from core.logging import get_logger
from services.google_sheets import GoogleSheetsExporter

logger = get_logger(__name__)

_TIMEOUT_SECONDS = 20.0
_CHUNK_SIZE = 65536


@dataclass
class ImageDownloadResult:
    manufacturer: str
    products_with_images: int = 0
    downloaded: int = 0
    skipped_existing: int = 0
    skipped_no_title: int = 0
    failed: list[str] = field(default_factory=list)  # "<url>: <error>"


def _row_image_urls(row: dict[str, str]) -> list[str]:
    raw = row.get("image") or ""
    return [line.strip() for line in raw.splitlines() if line.strip()]


def download_manufacturer_images(
    exporter: GoogleSheetsExporter,
    manufacturer: str,
    data_dir: Path,
    *,
    ca_bundle_path: str | None = None,
) -> ImageDownloadResult:
    """Reads every row of `manufacturer`'s sheet tab and downloads its
    "image" column URLs into `data_dir/<manufacturer>/`.

    `ca_bundle_path`: same idea as `CrawlHttpClient`'s param of the same
    name (see `manufacturers/eizo/ca_bundle.py`) -- a manufacturer whose
    image host sends an incomplete TLS chain needs a CA bundle beyond
    certifi's default, or every download fails with
    "SSLCertVerificationError: unable to get local issuer certificate"
    even though the sync adapter's own `CrawlHttpClient` (which already
    gets this fix via the manufacturer's `ManufacturerConfig`) works fine.
    """
    result = ImageDownloadResult(manufacturer=manufacturer)
    dest_dir = data_dir / manufacturer
    dest_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    if ca_bundle_path:
        session.verify = ca_bundle_path
    try:
        for row in exporter.get_rows(manufacturer):
            urls = _row_image_urls(row)
            if not urls:
                continue
            result.products_with_images += 1

            title = (row.get("Title") or row.get("product (item)") or "").strip()
            if not title:
                result.skipped_no_title += len(urls)
                logger.warning("Skipping %d image(s) with no Title/product (item) to name them from", len(urls))
                continue

            for index, url in enumerate(urls):
                # Guess the filename from the URL alone first, so a file
                # already on disk (the common re-run case) is skipped
                # without spending a request on it at all.
                provisional_path = dest_dir / build_image_filename(title, index, url)
                if provisional_path.exists():
                    result.skipped_existing += 1
                    continue

                try:
                    response = session.get(url, timeout=_TIMEOUT_SECONDS, stream=True)
                    response.raise_for_status()
                except requests.RequestException as exc:
                    result.failed.append(f"{url}: {exc}")
                    continue

                # Only differs from `provisional_path` when the URL itself
                # had no recognizable image extension (content-type fills
                # that gap once we actually have a response).
                dest_path = dest_dir / build_image_filename(title, index, url, content_type=response.headers.get("content-type"))
                if dest_path.exists():
                    result.skipped_existing += 1
                    response.close()
                    continue

                try:
                    with open(dest_path, "wb") as f:
                        for chunk in response.iter_content(_CHUNK_SIZE):
                            f.write(chunk)
                    result.downloaded += 1
                except OSError as exc:
                    result.failed.append(f"{url}: {exc}")
                finally:
                    response.close()
    finally:
        session.close()

    return result
