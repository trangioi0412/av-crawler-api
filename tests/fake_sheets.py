"""A hand-built fake standing in for the gspread client, so the test suite
never needs real Google credentials or network access.

Implements just the subset of the gspread API this codebase actually uses
(see services/google_sheets.py and services/admin_sheets.py): worksheet
lookup/creation, whole-sheet reads, single-row updates, row appends, and
per-cell batch updates.
"""
from __future__ import annotations

import re

import gspread


class FakeWorksheet:
    def __init__(self, title: str) -> None:
        self.title = title
        self._rows: list[list[str]] = []

    def get_all_values(self) -> list[list[str]]:
        return [list(row) for row in self._rows]

    def _ensure_row(self, idx: int) -> None:
        while len(self._rows) <= idx:
            self._rows.append([])

    def update(self, values: list[list[str]], range_name: str = "A1", value_input_option: str | None = None) -> None:
        match = re.match(r"^[A-Za-z]+(\d+)$", range_name)
        start_row = int(match.group(1)) - 1 if match else 0
        for offset, row in enumerate(values):
            self._ensure_row(start_row + offset)
            self._rows[start_row + offset] = [str(v) for v in row]

    def append_row(self, values: list[str], value_input_option: str | None = None) -> None:
        self._rows.append([str(v) for v in values])

    def append_rows(self, rows: list[list[str]], value_input_option: str | None = None) -> None:
        for row in rows:
            self._rows.append([str(v) for v in row])

    def update_cells(self, cells: list["gspread.cell.Cell"], value_input_option: str | None = None) -> None:
        for cell in cells:
            row_idx, col_idx = cell.row - 1, cell.col - 1
            self._ensure_row(row_idx)
            row = self._rows[row_idx]
            while len(row) <= col_idx:
                row.append("")
            row[col_idx] = str(cell.value)

    def delete_rows(self, row_number: int) -> None:
        idx = row_number - 1
        if 0 <= idx < len(self._rows):
            del self._rows[idx]


class FakeSpreadsheet:
    def __init__(self) -> None:
        self._sheets: dict[str, FakeWorksheet] = {}

    def worksheet(self, title: str) -> FakeWorksheet:
        if title not in self._sheets:
            raise gspread.WorksheetNotFound(title)
        return self._sheets[title]

    def add_worksheet(self, title: str, rows: int = 1000, cols: int = 20) -> FakeWorksheet:
        ws = FakeWorksheet(title)
        self._sheets[title] = ws
        return ws

    def worksheets(self) -> list[FakeWorksheet]:
        return list(self._sheets.values())

    # -- test-only helpers, not part of the gspread API -------------------

    def seed_rows(self, title: str, headers: list[str], rows: list[dict[str, str]]) -> FakeWorksheet:
        """Convenience for tests: create (or reset) a tab with a header row
        plus the given records, as `SheetRowStore`/`GoogleSheetsExporter`
        would leave it after some real usage.
        """
        ws = FakeWorksheet(title)
        ws._rows = [list(headers)] + [[str(row.get(h, "")) for h in headers] for row in rows]
        self._sheets[title] = ws
        return ws
