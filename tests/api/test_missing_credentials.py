"""Regression test: a missing Google service-account credentials file used
to surface as Starlette's default plain-text 500 (unparsable as JSON by
any caller, including the Next.js proxy in AV_Catalog -- it saw a fetch
parse error and reported "API unreachable"). `main.py` now has a
`FileNotFoundError` handler that turns this into a JSON 503 instead.
"""
from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_missing_credentials_file_returns_json_503(client: TestClient, monkeypatch):
    def _raise_missing_file(credentials_path, spreadsheet_id):
        raise FileNotFoundError(f"Google service-account credentials file not found: {credentials_path}")

    monkeypatch.setattr("services.admin_sheets.open_spreadsheet", _raise_missing_file)

    response = client.get("/api/manufacturers")

    assert response.status_code == 503
    assert "credentials file not found" in response.json()["detail"]
