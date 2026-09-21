"""Shared Google Sheets authentication/connection helper.

Every service that talks to the spreadsheet (the per-brand product exporter
in `google_sheets.py`, and the admin sheets -- New_brand / System_Config /
Sync_logs -- in `admin_sheets.py`) opens it through this one function, so
there is exactly one place that knows how the service-account credentials
are loaded.
"""
from __future__ import annotations

from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def open_spreadsheet(credentials_path: Path, spreadsheet_id: str) -> gspread.Spreadsheet:
    if not credentials_path.exists():
        raise FileNotFoundError(
            f"Google service-account credentials file not found: {credentials_path}"
        )
    creds = Credentials.from_service_account_file(str(credentials_path), scopes=_SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(spreadsheet_id)
