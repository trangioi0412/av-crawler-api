"""Read-only catalog endpoints backing the Next.js admin UI (manufacturer
dropdown, product browsing). Not required by the sync engine itself.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.schemas import ManufacturerOut
from core.config import settings
from core.registry import registry
from services.admin_sheets import SystemConfigStore, list_brand_sheet_names, open_admin_spreadsheet
from services.google_sheets import GoogleSheetsExporter

router = APIRouter(tags=["catalog"])


@router.get("/manufacturers", response_model=list[ManufacturerOut])
def list_manufacturers() -> list[ManufacturerOut]:
    """Every manufacturer that can be synced: the code-registered adapters
    (e.g. hdcvt -- always listed, even before their sheet tab exists, since
    a brand's first sync is what creates that tab) plus every other brand
    sheet tab in the spreadsheet (see `admin_sheets.list_brand_sheet_names`),
    enriched with a base_url from System_Config. Falls back to just the
    code-registered adapters if Sheets isn't configured.
    """
    out: list[ManufacturerOut] = [
        ManufacturerOut(key=c.key, display_name=c.display_name, base_url=c.base_url)
        for c in registry.list_manufacturers()
    ]
    if not settings.google_spreadsheet_id or not settings.google_sheets_credentials_path:
        return out

    known_keys = {m.key for m in out}
    spreadsheet = open_admin_spreadsheet(settings.google_sheets_credentials_path, settings.google_spreadsheet_id)
    system_config = SystemConfigStore(spreadsheet)
    config_rows = {row["Slug"]: row for row in system_config.list_manufacturers()}

    for name in list_brand_sheet_names(spreadsheet):
        key = name.strip().lower()
        if key in known_keys:
            continue
        if key in config_rows:
            row = config_rows[key]
            out.append(ManufacturerOut(key=key, display_name=row.get("Tên hãng") or name, base_url=row.get("Website") or ""))
        else:
            # A sheet tab exists but nothing knows its crawl source (e.g. a
            # tab created by hand before this brand went through the
            # onboarding flow). Still listed so it's visible in the UI,
            # just not syncable until someone adds a System_Config row.
            out.append(ManufacturerOut(key=key, display_name=name, base_url=""))

    return out


@router.get("/products")
def list_products(manufacturer: str) -> list[dict[str, str]]:
    """Reads a manufacturer's product rows straight from its Google Sheets
    tab -- there is no database to query. `manufacturer` is required since
    reading every brand's tab in one call would be expensive and isn't
    needed by anything today (this endpoint isn't wired into the UI; it
    exists for manual verification).
    """
    if not settings.google_spreadsheet_id or not settings.google_sheets_credentials_path:
        raise HTTPException(status_code=400, detail="Google Sheets (GOOGLE_SPREADSHEET_ID) is not configured")

    exporter = GoogleSheetsExporter(settings.google_sheets_credentials_path, settings.google_spreadsheet_id)
    return exporter.get_rows(manufacturer.strip().lower())
