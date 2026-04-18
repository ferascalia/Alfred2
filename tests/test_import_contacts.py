"""Tests for alfred/services/import_contacts.py — CSV + XLSX parsing."""
import io
from typing import Any

import pytest

from alfred.services.import_contacts import parse_and_validate, parse_xlsx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_csv(rows: list[list[str]], headers: list[str] | None = None) -> bytes:
    """Build a minimal CSV in bytes."""
    import csv

    buf = io.StringIO()
    writer = csv.writer(buf)
    if headers is None:
        headers = ["display_name", "company", "role", "cadence_days", "relationship_type", "tags", "how_we_met"]
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# TestParseAndValidate — CSV
# ---------------------------------------------------------------------------

class TestParseAndValidate:

    def test_valid_csv_returns_rows(self):
        csv_bytes = _make_csv([
            ["Alice", "Acme", "CEO", "30", "professional", "cliente|vip", "Evento 2024"],
            ["Bob", "", "", "15", "friend", "amigo", ""],
        ])
        rows, errors = parse_and_validate(csv_bytes)
        assert errors == []
        assert len(rows) == 2

        alice = rows[0]
        assert alice["display_name"] == "Alice"
        assert alice["cadence_days"] == 30

        bob = rows[1]
        assert bob["display_name"] == "Bob"
        assert bob["cadence_days"] == 15

    def test_missing_display_name_returns_error(self):
        csv_bytes = _make_csv([
            ["", "Acme", "CEO", "30", "professional", "", ""],
        ])
        rows, errors = parse_and_validate(csv_bytes)
        assert rows == []
        assert any("display_name" in e for e in errors)

    def test_invalid_cadence_days_returns_error(self):
        csv_bytes = _make_csv([
            ["Alice", "", "", "999", "professional", "", ""],
        ])
        rows, errors = parse_and_validate(csv_bytes)
        assert rows == []
        assert any("cadence_days" in e for e in errors)

    def test_pipe_separated_tags(self):
        csv_bytes = _make_csv([
            ["Alice", "", "", "15", "friend", "cliente|vip|amigo", ""],
        ])
        rows, errors = parse_and_validate(csv_bytes)
        assert errors == []
        assert rows[0]["tags"] == ["cliente", "vip", "amigo"]

    def test_max_rows_exceeded(self):
        data_rows = [["Person {}".format(i), "", "", "15", "friend", "", ""] for i in range(101)]
        csv_bytes = _make_csv(data_rows)
        rows, errors = parse_and_validate(csv_bytes)
        assert rows == []
        assert any("100" in e for e in errors)

    def test_empty_csv(self):
        rows, errors = parse_and_validate(b"")
        assert rows == []
        assert errors


# ---------------------------------------------------------------------------
# TestParseXlsx — Excel parsing
# ---------------------------------------------------------------------------

class TestParseXlsx:

    def _make_xlsx(self, headers: list[str], rows: list[list[Any]]) -> bytes:
        """Create an in-memory .xlsx file using openpyxl."""
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(headers)
        for row in rows:
            ws.append(row)

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf.read()

    def test_valid_xlsx_returns_rows(self):
        xlsx_bytes = self._make_xlsx(
            ["display_name", "company", "role", "cadence_days", "relationship_type", "tags", "how_we_met"],
            [
                ["Alice", "Acme", "CEO", 30, "professional", "cliente|vip", "Evento 2024"],
                ["Bob", None, None, 15, "friend", "amigo", None],
            ],
        )
        rows, errors = parse_xlsx(xlsx_bytes)
        assert errors == []
        assert len(rows) == 2

        alice = rows[0]
        assert alice["display_name"] == "Alice"
        assert alice["cadence_days"] == 30

        bob = rows[1]
        assert bob["display_name"] == "Bob"
        assert bob["cadence_days"] == 15

    def test_xlsx_missing_display_name_column(self):
        xlsx_bytes = self._make_xlsx(
            ["company", "role", "cadence_days"],
            [["Acme", "CEO", 30]],
        )
        rows, errors = parse_xlsx(xlsx_bytes)
        assert rows == []
        assert any("display_name" in e for e in errors)

    def test_xlsx_empty_display_name_row(self):
        xlsx_bytes = self._make_xlsx(
            ["display_name", "cadence_days"],
            [["", 15]],
        )
        rows, errors = parse_xlsx(xlsx_bytes)
        assert rows == []
        assert any("display_name" in e for e in errors)

    def test_xlsx_max_rows_exceeded(self):
        data_rows = [["Person {}".format(i), 15] for i in range(101)]
        xlsx_bytes = self._make_xlsx(["display_name", "cadence_days"], data_rows)
        rows, errors = parse_xlsx(xlsx_bytes)
        assert rows == []
        assert any("100" in e for e in errors)
