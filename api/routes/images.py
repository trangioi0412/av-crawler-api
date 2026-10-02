"""Downloads a manufacturer's sheet images to a local `Data/` folder.

Separate from `sync.py` -- this doesn't crawl anything, it just pulls the
image URLs already sitting in the "image" column of that manufacturer's
Google Sheets tab (see `services/google_sheets.py`) down onto disk, into
`Data/<manufacturer>/` at the project root.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.schemas import ImageDownloadResponse
from core.config import BASE_DIR, settings
from core.registry import registry
from services.google_sheets import GoogleSheetsExporter
from services.image_downloader import download_manufacturer_images

router = APIRouter(prefix="/images", tags=["images"])

DATA_DIR = BASE_DIR / "Data"


@router.post("/download", response_model=ImageDownloadResponse)
def download_images(manufacturer: str) -> ImageDownloadResponse:
    if not settings.google_spreadsheet_id or not settings.google_sheets_credentials_path:
        raise HTTPException(status_code=400, detail="Google Sheets (GOOGLE_SPREADSHEET_ID) is not configured")

    manufacturer_key = manufacturer.strip().lower()

    # A code-registered manufacturer (e.g. eizo) may need a non-default CA
    # bundle for its own image host -- see services/image_downloader.py's
    # docstring on `ca_bundle_path`. Sheet-only manufacturers with no code
    # adapter have no config to look up, which is fine: they also have no
    # known reason to need one.
    ca_bundle_path = registry.get_config(manufacturer_key).ca_bundle_path if registry.is_registered(manufacturer_key) else None

    exporter = GoogleSheetsExporter(settings.google_sheets_credentials_path, settings.google_spreadsheet_id)
    result = download_manufacturer_images(exporter, manufacturer_key, DATA_DIR, ca_bundle_path=ca_bundle_path)

    return ImageDownloadResponse(
        manufacturer=result.manufacturer,
        products_with_images=result.products_with_images,
        downloaded=result.downloaded,
        skipped_existing=result.skipped_existing,
        skipped_no_title=result.skipped_no_title,
        failed=result.failed,
    )
