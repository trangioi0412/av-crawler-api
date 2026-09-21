"""Admin/config sheets that replace what used to be SQLite tables:

  - New_brand     -- intake queue for "Yeu cau them hang moi" (replaces the
                      old `manufacturer_requests` table). One row per
                      request; deleted once the brand has been fully synced
                      for the first time (see NewBrandStatus).
  - System_Config -- durable "brand key -> website" lookup. New_brand rows
                      are transient (deleted once done), so this is where a
                      brand's crawl source lives permanently, for every
                      future re-sync.
  - Sync_logs     -- durable history of sync job runs (replaces the old
                      `sync_jobs` table). Live/in-progress status is served
                      from `services.job_store`'s in-memory state instead --
                      this sheet only gets written at job start and job end
                      (never per-item) to stay well under Google Sheets API
                      rate limits.

These are small, low-row-count sheets (a handful of pending requests, one
row per known brand, recent job history), so a simple "read the whole sheet,
find the row" strategy is fine -- unlike the per-brand product tabs in
`google_sheets.py`, which can have hundreds of rows and use a proper
natural-key index.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import gspread

from core.logging import get_logger
from core.slug import slugify
from services.sheets_client import open_spreadsheet

logger = get_logger(__name__)

# Sheet tab names that are never treated as a manufacturer's product catalog
# when listing "which brands should we sync" (see list_brand_sheet_names).
RESERVED_SHEET_TITLES = {
    "new_brand",
    "product_new",
    "product_delete",
    "sync_logs",
    "system_config",
}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def list_brand_sheet_names(spreadsheet: gspread.Spreadsheet) -> list[str]:
    """Every worksheet tab that represents a manufacturer's product catalog
    -- i.e. every tab except the reserved admin/system ones above.
    """
    return [
        ws.title
        for ws in spreadsheet.worksheets()
        if ws.title.strip().lower() not in RESERVED_SHEET_TITLES
    ]


class SheetRowStore:
    """Generic CRUD over a worksheet treated as a simple table: one header
    row plus one row per record, keyed by `key_column`. Used for the small
    admin sheets above -- NOT for per-manufacturer product tabs, which use
    `GoogleSheetsExporter`'s natural-key upsert instead (those can have
    hundreds of rows and need a real index).
    """

    def __init__(self, spreadsheet: gspread.Spreadsheet, tab_name: str, headers: list[str], key_column: str) -> None:
        self._spreadsheet = spreadsheet
        self._tab_name = tab_name
        self._headers = headers
        self._key_column = key_column

    def _worksheet(self) -> gspread.Worksheet:
        try:
            return self._spreadsheet.worksheet(self._tab_name)
        except gspread.WorksheetNotFound:
            logger.info("Creating new Google Sheets tab '%s'", self._tab_name)
            worksheet = self._spreadsheet.add_worksheet(title=self._tab_name, rows=1000, cols=len(self._headers))
            worksheet.update([self._headers], "A1")
            return worksheet

    def _all_values(self) -> tuple[gspread.Worksheet, list[str], list[list[str]]]:
        ws = self._worksheet()
        values = ws.get_all_values()
        header = values[0] if values else self._headers
        body = values[1:] if values else []
        return ws, header, body

    def list(self) -> list[dict[str, str]]:
        _, header, body = self._all_values()
        return [dict(zip(header, row + [""] * (len(header) - len(row)))) for row in body]

    def get(self, key: str) -> dict[str, str] | None:
        for row in self.list():
            if row.get(self._key_column) == key:
                return row
        return None

    def _find_row_number(self, header: list[str], body: list[list[str]], key: str) -> int | None:
        if self._key_column not in header:
            return None
        key_idx = header.index(self._key_column)
        for i, row in enumerate(body, start=2):  # row 1 is the header
            if len(row) > key_idx and row[key_idx] == key:
                return i
        return None

    def upsert(self, row: dict[str, str]) -> dict[str, str]:
        key = row[self._key_column]
        ws, header, body = self._all_values()
        row_number = self._find_row_number(header, body, key)
        ordered = [str(row.get(h, "")) for h in self._headers]
        if row_number is not None:
            ws.update([ordered], f"A{row_number}", value_input_option="USER_ENTERED")
        else:
            ws.append_row(ordered, value_input_option="USER_ENTERED")
        return row

    def update(self, key: str, **fields: str) -> dict[str, str]:
        existing = self.get(key)
        if existing is None:
            raise ValueError(f"Row with {self._key_column}='{key}' not found in '{self._tab_name}'")
        existing.update({k: ("" if v is None else str(v)) for k, v in fields.items()})
        return self.upsert(existing)

    def delete(self, key: str) -> None:
        ws, header, body = self._all_values()
        row_number = self._find_row_number(header, body, key)
        if row_number is not None:
            ws.delete_rows(row_number)


class NewBrandStatus:
    PENDING = "Chờ duyệt"
    APPROVED = "Duyệt"
    CRAWLING = "Đang cào dữ liệu"
    DONE = "Đã cào xong"
    ERROR = "Lỗi cào dữ liệu"
    REJECTED = "Từ chối"

    ALL = (PENDING, APPROVED, CRAWLING, DONE, ERROR, REJECTED)


NEW_BRAND_HEADERS = ["Slug", "Tên hãng", "Website", "Trạng thái", "Ghi chú", "Ngày gửi", "Cập nhật lúc"]


class NewBrandStore:
    """The 'Yeu cau them hang moi' intake queue. Keyed by a slug of the
    brand name (see core.slug.slugify) since Sheets rows have no database
    auto-increment id.
    """

    def __init__(self, spreadsheet: gspread.Spreadsheet) -> None:
        self._store = SheetRowStore(spreadsheet, "New_brand", NEW_BRAND_HEADERS, "Slug")

    def create(self, *, name: str, website_url: str, notes: str | None = None) -> dict[str, str]:
        slug = slugify(name)
        now = _utcnow_iso()
        row = {
            "Slug": slug,
            "Tên hãng": name,
            "Website": website_url,
            "Trạng thái": NewBrandStatus.PENDING,
            "Ghi chú": notes or "",
            "Ngày gửi": now,
            "Cập nhật lúc": now,
        }
        return self._store.upsert(row)

    def list(self, *, status: str | None = None) -> list[dict[str, str]]:
        rows = self._store.list()
        if status:
            rows = [r for r in rows if r.get("Trạng thái") == status]
        return rows

    def get(self, slug: str) -> dict[str, str] | None:
        return self._store.get(slug)

    def update_status(self, slug: str, status: str, notes: str | None = None) -> dict[str, str]:
        fields: dict[str, str] = {"Trạng thái": status, "Cập nhật lúc": _utcnow_iso()}
        if notes is not None:
            fields["Ghi chú"] = notes
        return self._store.update(slug, **fields)

    def delete(self, slug: str) -> None:
        self._store.delete(slug)


SYSTEM_CONFIG_HEADERS = ["Slug", "Tên hãng", "Website", "Cập nhật lúc"]


class SystemConfigStore:
    """Durable 'brand key -> crawl source' lookup, so a re-sync of an
    already-onboarded brand (whose New_brand row is long gone) still knows
    which website to crawl.
    """

    def __init__(self, spreadsheet: gspread.Spreadsheet) -> None:
        self._store = SheetRowStore(spreadsheet, "System_Config", SYSTEM_CONFIG_HEADERS, "Slug")

    def set_manufacturer(self, slug: str, name: str, website_url: str) -> dict[str, str]:
        return self._store.upsert(
            {"Slug": slug, "Tên hãng": name, "Website": website_url, "Cập nhật lúc": _utcnow_iso()}
        )

    def get_manufacturer(self, slug: str) -> dict[str, str] | None:
        return self._store.get(slug)

    def list_manufacturers(self) -> list[dict[str, str]]:
        return self._store.list()


SYNC_LOGS_HEADERS = [
    "Job ID", "Hãng", "Chế độ", "Trạng thái", "Tổng", "Đã xử lý", "Thành công",
    "Lỗi", "Bỏ qua", "Tiến độ (%)", "Chi tiết lỗi", "Bắt đầu lúc", "Hoàn tất lúc", "Tạo lúc",
]


class SyncLogsStore:
    """Durable history of sync job runs. Written at job start and job end
    only (never per-item) -- see `services/job_store.py` for the in-memory
    state that serves live progress polling during a run.
    """

    def __init__(self, spreadsheet: gspread.Spreadsheet) -> None:
        self._store = SheetRowStore(spreadsheet, "Sync_logs", SYNC_LOGS_HEADERS, "Job ID")

    def create(self, job_id: str, manufacturer: str, mode: str) -> dict[str, str]:
        now = _utcnow_iso()
        return self._store.upsert(
            {
                "Job ID": job_id,
                "Hãng": manufacturer,
                "Chế độ": mode,
                "Trạng thái": "queued",
                "Tổng": "0",
                "Đã xử lý": "0",
                "Thành công": "0",
                "Lỗi": "0",
                "Bỏ qua": "0",
                "Tiến độ (%)": "0",
                "Chi tiết lỗi": "",
                "Bắt đầu lúc": "",
                "Hoàn tất lúc": "",
                "Tạo lúc": now,
            }
        )

    def update(self, job_id: str, **fields: object) -> dict[str, str]:
        return self._store.update(job_id, **{k: v for k, v in fields.items()})

    def get(self, job_id: str) -> dict[str, str] | None:
        return self._store.get(job_id)

    def list_recent(self, *, manufacturer: str | None = None, limit: int = 20) -> list[dict[str, str]]:
        rows = self._store.list()
        if manufacturer:
            rows = [r for r in rows if r.get("Hãng") == manufacturer]
        rows.sort(key=lambda r: r.get("Tạo lúc") or "", reverse=True)
        return rows[:limit]


def open_admin_spreadsheet(credentials_path: Path, spreadsheet_id: str) -> gspread.Spreadsheet:
    return open_spreadsheet(credentials_path, spreadsheet_id)
