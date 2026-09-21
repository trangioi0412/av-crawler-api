"""Test-wide setup.

This service has no database -- Google Sheets is its only persistence
layer (see services/google_sheets.py and services/admin_sheets.py). Tests
never touch the real spreadsheet: every test gets a `fake_spreadsheet`
(tests/fake_sheets.py) in its place, via an autouse fixture that
monkeypatches the one function (`open_spreadsheet`) both sheets modules
call to connect.

GOOGLE_SPREADSHEET_ID / GOOGLE_SHEETS_CREDENTIALS_FILE are still set to
dummy values (before `core.config` is imported anywhere) so the app's own
"is Sheets configured?" checks pass -- it's `open_spreadsheet` that's faked,
not the configuration.
"""
from __future__ import annotations

import os

os.environ["GOOGLE_SPREADSHEET_ID"] = "test-spreadsheet-id"
os.environ["GOOGLE_SHEETS_CREDENTIALS_FILE"] = "test-credentials.json"
os.environ.setdefault("LOG_LEVEL", "WARNING")

import pytest  # noqa: E402

from tests.fake_sheets import FakeSpreadsheet  # noqa: E402


@pytest.fixture(autouse=True)
def fake_spreadsheet(monkeypatch) -> FakeSpreadsheet:
    spreadsheet = FakeSpreadsheet()

    def _fake_open_spreadsheet(credentials_path, spreadsheet_id):
        return spreadsheet

    # Both modules did `from services.sheets_client import open_spreadsheet`,
    # which binds their own local name -- patching services.sheets_client
    # alone would not affect those already-imported references.
    monkeypatch.setattr("services.google_sheets.open_spreadsheet", _fake_open_spreadsheet)
    monkeypatch.setattr("services.admin_sheets.open_spreadsheet", _fake_open_spreadsheet)

    return spreadsheet


@pytest.fixture(autouse=True)
def _reset_job_store():
    """`services.job_store` keeps an in-memory dict module-level (by
    design -- see its docstring) so it survives across requests within one
    process. Tests must not leak job state into each other.
    """
    import services.job_store as job_store_module

    job_store_module._jobs.clear()
    yield
    job_store_module._jobs.clear()
