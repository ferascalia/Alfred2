"""Tests for alfred/services/import_contacts.py — CSV + XLSX parsing."""
import io
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alfred.services.import_contacts import (
    build_duplicate_comparison,
    build_grouped_preview,
    build_import_report,
    check_duplicates,
    execute_import,
    merge_contact,
    parse_and_validate,
    parse_xlsx,
    replace_contact,
)


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


# ---------------------------------------------------------------------------
# TestCheckDuplicates — Task 3
# ---------------------------------------------------------------------------

class TestCheckDuplicates:

    @pytest.mark.asyncio
    async def test_separates_clean_and_duplicates(self) -> None:
        rows = [
            {"display_name": "João Silva", "cadence_days": 15},
            {"display_name": "Maria Santos", "cadence_days": 30},
            {"display_name": "Pedro Costa", "cadence_days": 15},
        ]
        existing_match = {"id": "abc-123", "display_name": "João Silva", "company": "BTG"}

        async def mock_find_similar(user_id: str, display_name: str) -> list[dict]:
            if display_name == "João Silva":
                return [existing_match]
            return []

        with patch(
            "alfred.services.import_contacts.find_similar_contacts",
            side_effect=mock_find_similar,
        ):
            clean, duplicates = await check_duplicates("user-1", rows)

        assert len(clean) == 2
        assert len(duplicates) == 1
        dup = duplicates[0]
        assert dup["csv_row"]["display_name"] == "João Silva"
        assert dup["existing"]["id"] == "abc-123"
        assert dup["existing"]["display_name"] == "João Silva"

    @pytest.mark.asyncio
    async def test_all_clean(self) -> None:
        rows = [{"display_name": "Alice Braga", "cadence_days": 15}]

        with patch(
            "alfred.services.import_contacts.find_similar_contacts",
            new=AsyncMock(return_value=[]),
        ):
            clean, duplicates = await check_duplicates("user-1", rows)

        assert len(clean) == 1
        assert len(duplicates) == 0


# ---------------------------------------------------------------------------
# TestBuildGroupedPreview — Task 3
# ---------------------------------------------------------------------------

class TestBuildGroupedPreview:

    def test_clean_only(self) -> None:
        clean = [{"display_name": "Alice Braga", "cadence_days": 15, "company": "Acme"}]
        duplicates: list[dict] = []
        result = build_grouped_preview(clean, duplicates)
        assert "1 contato" in result
        assert "Alice Braga" in result
        assert "⚠️" not in result

    def test_with_duplicates(self) -> None:
        clean = [{"display_name": "Pedro Costa", "cadence_days": 15}]
        duplicates = [
            {
                "csv_row": {"display_name": "João Silva", "cadence_days": 15},
                "existing": {"id": "abc-123", "display_name": "João Silva (existente)", "company": "BTG"},
            }
        ]
        result = build_grouped_preview(clean, duplicates)
        assert "✅" in result
        assert "⚠️" in result
        assert "Pedro Costa" in result
        assert "João Silva" in result


# ---------------------------------------------------------------------------
# TestBuildDuplicateComparison — Task 3
# ---------------------------------------------------------------------------

class TestBuildDuplicateComparison:

    def test_shows_index_and_names(self) -> None:
        dup = {
            "csv_row": {"display_name": "João Silva", "cadence_days": 15, "company": "Nova Empresa"},
            "existing": {"id": "abc-123", "display_name": "João Silva", "company": "Empresa Antiga"},
        }
        result = build_duplicate_comparison(dup, index=1, total=3)
        assert "1/3" in result
        assert "João Silva" in result
        assert "Nova Empresa" in result
        assert "Empresa Antiga" in result


# ---------------------------------------------------------------------------
# TestMergeContact — Task 4
# ---------------------------------------------------------------------------

class TestMergeContact:

    @pytest.mark.asyncio
    async def test_fills_empty_fields_only(self) -> None:
        existing_data = {
            "id": "existing-id",
            "display_name": "João Silva",
            "company": "BTG",
            "role": None,
        }
        csv_row = {
            "display_name": "João Silva",
            "company": "Empresa X",
            "role": "CEO",
            "cadence_days": 15,
        }

        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value.data = existing_data
        mock_db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [existing_data]

        with patch("alfred.services.import_contacts.get_db", return_value=mock_db):
            await merge_contact("user-1", "existing-id", csv_row)

        update_call_args = mock_db.table.return_value.update.call_args
        updated_fields = update_call_args[0][0]

        # role should be filled (was None)
        assert updated_fields.get("role") == "CEO"
        # company should NOT be overwritten (already filled in existing)
        assert "company" not in updated_fields


# ---------------------------------------------------------------------------
# TestReplaceContact — Task 4
# ---------------------------------------------------------------------------

class TestReplaceContact:

    @pytest.mark.asyncio
    async def test_overwrites_all_fields(self) -> None:
        existing_data = {
            "id": "existing-id",
            "display_name": "João Silva",
            "company": "BTG",
            "role": "Analista",
        }
        csv_row = {
            "display_name": "João Silva",
            "company": "Empresa X",
            "role": "CEO",
            "cadence_days": 15,
        }

        mock_db = MagicMock()
        mock_db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [existing_data]

        with patch("alfred.services.import_contacts.get_db", return_value=mock_db):
            await replace_contact("user-1", "existing-id", csv_row)

        update_call_args = mock_db.table.return_value.update.call_args
        updated_fields = update_call_args[0][0]

        # Both company and role from CSV should be present
        assert updated_fields.get("company") == "Empresa X"
        assert updated_fields.get("role") == "CEO"


# ---------------------------------------------------------------------------
# TestExecuteImport — Task 4
# ---------------------------------------------------------------------------

class TestExecuteImport:

    @pytest.mark.asyncio
    async def test_creates_clean_and_applies_decisions(self) -> None:
        clean_rows = [{"display_name": "Alice Braga", "cadence_days": 15}]
        duplicates = [
            {
                "csv_row": {"display_name": "João Silva", "cadence_days": 15},
                "existing": {"id": "existing-1", "display_name": "João Silva", "company": "BTG"},
                "decision": "skip",
            },
            {
                "csv_row": {"display_name": "Maria Souza", "cadence_days": 30},
                "existing": {"id": "existing-2", "display_name": "Maria Souza", "company": None},
                "decision": "import_new",
            },
        ]
        decisions = {}  # decisions embedded in duplicates list

        with patch(
            "alfred.services.import_contacts.create_contact_confirmed",
            new=AsyncMock(return_value="ok"),
        ):
            result = await execute_import("user-1", clean_rows, duplicates, decisions)

        # Alice (clean) + Maria (import_new) = 2 created; João (skip) = 1 skipped
        assert result["created"] == 2
        assert result["skipped"] == 1
        assert result["merged"] == 0
        assert result["replaced"] == 0


# ---------------------------------------------------------------------------
# TestBuildImportReport — Task 4
# ---------------------------------------------------------------------------

class TestBuildImportReport:

    def test_report_has_all_counts(self) -> None:
        result = {"created": 5, "skipped": 2, "merged": 1, "replaced": 0, "merged_details": []}
        report = build_import_report(result)
        assert "5" in report
        assert "2" in report
        assert "1" in report
        # MarkdownV2 escaping: ! → \!
        assert r"\!" in report or "!" in report
