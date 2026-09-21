"""Test-wide setup.

Points DATABASE_URL at a throwaway SQLite file *before* `core.config` (and
therefore `db.database`) is imported anywhere, so tests never touch a real
database. Session-scoped so all tests share one schema; individual tests
use unique manufacturer keys to avoid interfering with each other's rows.

Also force-disables Google Sheets export (`GOOGLE_SPREADSHEET_ID` empty) so
tests never touch the real spreadsheet -- pydantic-settings otherwise loads
whatever `backend/.env` has configured for local dev, which previously let a
test run silently create junk tabs in the real, production sheet. This
override takes priority over `.env` regardless of `os.environ.setdefault`
elsewhere, since it's set (not defaulted) before `core.config` is imported.
"""
from __future__ import annotations

import os
import tempfile

_tmp_dir = tempfile.mkdtemp(prefix="datacrawler_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_dir.replace(os.sep, '/')}/test.db"
os.environ["GOOGLE_SPREADSHEET_ID"] = ""
os.environ.setdefault("LOG_LEVEL", "WARNING")

import pytest  # noqa: E402

from db.database import init_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_test_db():
    init_db()
