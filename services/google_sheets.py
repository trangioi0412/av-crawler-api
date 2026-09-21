"""Google Sheets export -- an optional, best-effort supplementary sink for
synced products, on top of (not instead of) the SQLite database.

SQLite remains the source of truth for sync job status and deduplication;
a Sheets failure is logged and never fails the sync job (see
`core/engine.py`). Writes go to a per-manufacturer worksheet tab inside one
shared spreadsheet (`GOOGLE_SPREADSHEET_ID`), created automatically on
first use if it doesn't already exist.

Column layout and upsert identity were specified by the spreadsheet's
owner (2026-09-18) to match the existing "product_brand_avs-tek" tab and
per-brand tabs (extron, crestron, yealink, ...) already in that workbook:
  - Category            -> CanonicalProduct.category
  - Product             -> CanonicalProduct.subcategory (product line/type)
  - Title               -> CanonicalProduct.name
  - product (item)      -> CanonicalProduct.model or .sku (specific item)
  - Series              -> not available from any adapter yet; left blank
  - Main Feature         -> CanonicalProduct.features, one per line
  - Product Overview    -> CanonicalProduct.description
  - Technical Specifications -> CanonicalProduct.specifications, "Key: Value" per line
  - image               -> CanonicalProduct.image_urls, one per line
  - Brand               -> manufacturer display name (e.g. "HDCVT")
  - Datasheet           -> CanonicalProduct.document_urls, one per line

Upsert identity: existing rows are matched by `product (item)` (model/SKU)
when present, falling back to `Title` -- the same manufacturer+model-first
strategy as the Deduplicator (see `core/pipeline/deduplicator.py`), applied
here because the sheet has no hidden id column to key off of.
"""
from __future__ import annotations

from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from core.logging import get_logger
from core.models.product import CanonicalProduct

logger = get_logger(__name__)

SHEET_HEADERS = [
    "Category",
    "Product",
    "Title",
    "product (item)",
    "Series",
    "Main Feature",
    "Product Overview",
    "Technical Specifications",
    "image",
    "Brand",
    "Datasheet",
]

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def build_sheet_row(product: CanonicalProduct, *, brand_display_name: str) -> dict[str, str]:
    return {
        "Category": product.category or "",
        "Product": product.subcategory or "",
        "Title": product.name or "",
        "product (item)": product.model or product.sku or "",
        "Series": "",
        "Main Feature": "\n".join(product.features),
        "Product Overview": product.description or "",
        "Technical Specifications": "\n".join(f"{k}: {v}" for k, v in product.specifications.items()),
        "image": "\n".join(product.image_urls),
        "Brand": brand_display_name,
        "Datasheet": "\n".join(product.document_urls),
    }


def _natural_key(row: dict[str, str]) -> str:
    item = (row.get("product (item)") or "").strip().lower()
    if item:
        return f"item:{item}"
    return f"title:{(row.get('Title') or '').strip().lower()}"


class GoogleSheetsExporter:
    def __init__(self, credentials_path: Path, spreadsheet_id: str) -> None:
        if not credentials_path.exists():
            raise FileNotFoundError(
                f"Google service-account credentials file not found: {credentials_path}"
            )
        creds = Credentials.from_service_account_file(str(credentials_path), scopes=_SCOPES)
        self._client = gspread.authorize(creds)
        self._spreadsheet = self._client.open_by_key(spreadsheet_id)

    def _get_or_create_worksheet(self, tab_name: str) -> gspread.Worksheet:
        try:
            return self._spreadsheet.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            logger.info("Creating new Google Sheets tab '%s'", tab_name)
            worksheet = self._spreadsheet.add_worksheet(
                title=tab_name, rows=1000, cols=len(SHEET_HEADERS)
            )
            worksheet.update([SHEET_HEADERS], "A1")
            return worksheet

    def upsert_rows(self, tab_name: str, rows: list[dict[str, str]]) -> dict[str, int]:
        """Create-or-update rows in `tab_name`, matching existing rows by
        `_natural_key`. Returns {"created": n, "updated": n}.
        """
        if not rows:
            return {"created": 0, "updated": 0}

        worksheet = self._get_or_create_worksheet(tab_name)
        existing = worksheet.get_all_values()
        header = existing[0] if existing else SHEET_HEADERS
        body = existing[1:] if existing else []

        key_to_row_number: dict[str, int] = {}
        for idx, existing_row in enumerate(body, start=2):  # row 1 is the header
            padded = existing_row + [""] * (len(header) - len(existing_row))
            key_to_row_number[_natural_key(dict(zip(header, padded)))] = idx

        cell_updates: list[gspread.cell.Cell] = []
        row_appends: list[list[str]] = []
        created = 0
        updated = 0

        for row in rows:
            ordered_values = [row.get(h, "") for h in header]
            row_number = key_to_row_number.get(_natural_key(row))
            if row_number is not None:
                for col_idx, value in enumerate(ordered_values, start=1):
                    cell_updates.append(gspread.cell.Cell(row=row_number, col=col_idx, value=value))
                updated += 1
            else:
                row_appends.append(ordered_values)
                created += 1

        if cell_updates:
            worksheet.update_cells(cell_updates, value_input_option="USER_ENTERED")
        if row_appends:
            worksheet.append_rows(row_appends, value_input_option="USER_ENTERED")

        return {"created": created, "updated": updated}
