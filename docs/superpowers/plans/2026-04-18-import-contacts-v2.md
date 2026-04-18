# Import de Contatos v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Alfred's contact import to support Excel files, detect duplicates with a grouped preview, and let users choose per-duplicate actions (skip/import/merge/replace) via Telegram inline buttons.

**Architecture:** Rename `import_csv.py` → `import_contacts.py`, add `openpyxl` for Excel parsing, split duplicate detection from import execution, and manage review state in `context.user_data`. The existing validation pipeline is preserved and extended.

**Tech Stack:** Python 3.12, python-telegram-bot v21, openpyxl (read-only), Supabase, pytest

**Spec:** `docs/superpowers/specs/2026-04-18-import-contacts-v2-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `alfred/services/import_contacts.py` | Create (replaces `import_csv.py`) | Parsing, validation, duplicate detection, merge/replace logic, import execution |
| `alfred/services/import_csv.py` | Delete | Replaced by `import_contacts.py` |
| `alfred/bot/keyboards.py` | Modify | Add `import_preview_keyboard()` and `duplicate_review_keyboard()` |
| `alfred/bot/handlers.py` | Modify | Accept `.xlsx`, new callback routing for grouped preview + individual review |
| `alfred/bot/app.py` | Modify | Add `.xlsx` filter to document handler |
| `pyproject.toml` | Modify | Add `openpyxl` dependency |
| `tests/test_import_contacts.py` | Create | Tests for parsing, validation, duplicate detection, merge, replace, execute |
| `tests/test_keyboards.py` | Create | Tests for new keyboard factories |

---

## Task 1: Add openpyxl dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add openpyxl to dependencies**

In `pyproject.toml`, add `"openpyxl>=3.1"` to the `dependencies` list:

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "python-telegram-bot[webhooks]>=21.0",
    "anthropic>=0.40",
    "voyageai>=0.3",
    "supabase>=2.10",
    "pydantic-settings>=2.7",
    "structlog>=24.4",
    "httpx>=0.27",
    "groq>=0.11",
    "dateparser>=1.4.0",
    "openpyxl>=3.1",
]
```

- [ ] **Step 2: Install dependencies**

Run: `uv sync`
Expected: openpyxl installed successfully

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add openpyxl for Excel import support"
```

---

## Task 2: Create import_contacts.py with parsing + validation

**Files:**
- Create: `alfred/services/import_contacts.py`
- Delete: `alfred/services/import_csv.py`
- Create: `tests/test_import_contacts.py`

- [ ] **Step 1: Write failing tests for CSV parsing (preserve existing behavior)**

```python
# tests/test_import_contacts.py
import pytest


class TestParseAndValidate:
    def test_valid_csv_returns_rows(self) -> None:
        from alfred.services.import_contacts import parse_and_validate

        csv_bytes = (
            "display_name,company,role,cadence_days\n"
            "João Silva,Empresa X,CEO,15\n"
            "Maria Santos,Empresa Y,Diretora,30\n"
        ).encode("utf-8-sig")

        rows, errors = parse_and_validate(csv_bytes)
        assert len(rows) == 2
        assert errors == []
        assert rows[0]["display_name"] == "João Silva"
        assert rows[0]["cadence_days"] == 15

    def test_missing_display_name_returns_error(self) -> None:
        from alfred.services.import_contacts import parse_and_validate

        csv_bytes = "display_name,company\n,Empresa X\n".encode("utf-8-sig")
        rows, errors = parse_and_validate(csv_bytes)
        assert len(errors) == 1
        assert "display_name" in errors[0]

    def test_invalid_cadence_days_returns_error(self) -> None:
        from alfred.services.import_contacts import parse_and_validate

        csv_bytes = "display_name,cadence_days\nJoão,999\n".encode("utf-8-sig")
        rows, errors = parse_and_validate(csv_bytes)
        assert len(errors) == 1
        assert "365" in errors[0]

    def test_pipe_separated_tags(self) -> None:
        from alfred.services.import_contacts import parse_and_validate

        csv_bytes = "display_name,tags\nJoão,cliente|vip|amigo\n".encode("utf-8-sig")
        rows, errors = parse_and_validate(csv_bytes)
        assert rows[0]["tags"] == ["cliente", "vip", "amigo"]

    def test_max_rows_exceeded(self) -> None:
        from alfred.services.import_contacts import parse_and_validate

        header = "display_name\n"
        data = "".join(f"Contato {i}\n" for i in range(101))
        csv_bytes = (header + data).encode("utf-8-sig")
        rows, errors = parse_and_validate(csv_bytes)
        assert len(errors) == 1
        assert "100" in errors[0]

    def test_empty_csv(self) -> None:
        from alfred.services.import_contacts import parse_and_validate

        rows, errors = parse_and_validate(b"")
        assert len(errors) == 1
        assert "vazio" in errors[0].lower() or "empty" in errors[0].lower()
```

- [ ] **Step 2: Write failing tests for Excel parsing**

```python
# append to tests/test_import_contacts.py
from unittest.mock import MagicMock, patch


class TestParseXlsx:
    def _make_xlsx(self, headers: list[str], rows: list[list]) -> bytes:
        """Helper to create an in-memory .xlsx file."""
        from io import BytesIO

        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(headers)
        for row in rows:
            ws.append(row)
        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_valid_xlsx_returns_rows(self) -> None:
        from alfred.services.import_contacts import parse_xlsx

        xlsx_bytes = self._make_xlsx(
            ["display_name", "company", "cadence_days"],
            [["João Silva", "Empresa X", 15], ["Maria Santos", "Empresa Y", 30]],
        )
        rows, errors = parse_xlsx(xlsx_bytes)
        assert len(rows) == 2
        assert errors == []
        assert rows[0]["display_name"] == "João Silva"
        assert rows[0]["cadence_days"] == 15

    def test_xlsx_missing_display_name_column(self) -> None:
        from alfred.services.import_contacts import parse_xlsx

        xlsx_bytes = self._make_xlsx(["company", "role"], [["Empresa X", "CEO"]])
        rows, errors = parse_xlsx(xlsx_bytes)
        assert len(errors) == 1
        assert "display_name" in errors[0]

    def test_xlsx_empty_display_name_row(self) -> None:
        from alfred.services.import_contacts import parse_xlsx

        xlsx_bytes = self._make_xlsx(
            ["display_name", "company"],
            [["", "Empresa X"]],
        )
        rows, errors = parse_xlsx(xlsx_bytes)
        assert len(errors) == 1

    def test_xlsx_max_rows_exceeded(self) -> None:
        from alfred.services.import_contacts import parse_xlsx

        xlsx_bytes = self._make_xlsx(
            ["display_name"],
            [[f"Contato {i}"] for i in range(101)],
        )
        rows, errors = parse_xlsx(xlsx_bytes)
        assert len(errors) == 1
        assert "100" in errors[0]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_import_contacts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'alfred.services.import_contacts'`

- [ ] **Step 4: Create import_contacts.py with CSV + XLSX parsing**

Copy `alfred/services/import_csv.py` to `alfred/services/import_contacts.py`, then add `parse_xlsx()`:

```python
"""Bulk contact import via CSV and Excel."""
import csv
import io
from typing import Any

import httpx
import structlog

from alfred.config import settings

log = structlog.get_logger()

VALID_COLUMNS = {"display_name", "company", "role", "cadence_days", "relationship_type", "tags", "how_we_met"}
REQUIRED_COLUMNS = {"display_name"}
VALID_RELATIONSHIP_TYPES = {"friend", "professional", "family", "other"}
MAX_ROWS = 100


def build_template_csv() -> bytes:
    """Generate a template CSV with one example row."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["display_name", "company", "role", "cadence_days", "relationship_type", "tags", "how_we_met"])
    writer.writerow(["João Silva", "Empresa X", "CEO", "15", "professional", "cliente|vip", "Evento Tech 2024"])
    writer.writerow(["Maria Santos", "Empresa Y", "Diretora", "30", "friend", "amiga", ""])
    return output.getvalue().encode("utf-8-sig")


def _validate_rows(raw_rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate parsed rows (shared between CSV and XLSX)."""
    errors: list[str] = []
    rows: list[dict[str, Any]] = []

    for i, raw_row in enumerate(raw_rows, start=2):
        row = {k.strip().lower(): (str(v).strip() if v else "") for k, v in raw_row.items() if k}

        display_name = row.get("display_name", "")
        if not display_name:
            errors.append(f"Linha {i}: display_name é obrigatório e não pode estar vazio.")
            continue

        cadence_days = 15
        cadence_raw = row.get("cadence_days", "")
        if cadence_raw:
            try:
                cadence_days = int(float(cadence_raw))
                if not (1 <= cadence_days <= 365):
                    errors.append(
                        f"Linha {i} ({display_name}): cadence_days deve ser entre 1 e 365, recebeu '{cadence_raw}'."
                    )
                    continue
            except ValueError:
                errors.append(
                    f"Linha {i} ({display_name}): cadence_days deve ser um número inteiro, recebeu '{cadence_raw}'."
                )
                continue

        relationship_type: str | None = row.get("relationship_type") or None
        if relationship_type and relationship_type not in VALID_RELATIONSHIP_TYPES:
            errors.append(
                f"Linha {i} ({display_name}): relationship_type inválido '{relationship_type}'. "
                f"Válidos: {', '.join(sorted(VALID_RELATIONSHIP_TYPES))}."
            )
            continue

        tags_raw = row.get("tags", "")
        tags = [t.strip() for t in tags_raw.split("|") if t.strip()] if tags_raw else []

        contact: dict[str, Any] = {"display_name": display_name, "cadence_days": cadence_days}
        if row.get("company"):
            contact["company"] = row["company"]
        if row.get("role"):
            contact["role"] = row["role"]
        if relationship_type:
            contact["relationship_type"] = relationship_type
        if tags:
            contact["tags"] = tags
        if row.get("how_we_met"):
            contact["how_we_met"] = row["how_we_met"]

        rows.append(contact)

    return rows, errors


def _validate_columns(fieldnames: set[str]) -> list[str]:
    """Check column names, return errors."""
    errors: list[str] = []
    unknown = fieldnames - VALID_COLUMNS
    if unknown:
        errors.append(
            f"Coluna(s) inválida(s): {', '.join(sorted(unknown))}. "
            f"Válidas: {', '.join(sorted(VALID_COLUMNS))}."
        )
    missing = REQUIRED_COLUMNS - fieldnames
    if missing:
        errors.append(f"Coluna obrigatória ausente: {', '.join(sorted(missing))}.")
    return errors


def parse_and_validate(csv_bytes: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse and validate CSV bytes. Returns (rows, errors)."""
    try:
        text = csv_bytes.decode("utf-8-sig").strip()
    except UnicodeDecodeError:
        try:
            text = csv_bytes.decode("latin-1").strip()
        except UnicodeDecodeError:
            return [], ["Não foi possível ler o arquivo. Certifique-se que está salvo em UTF-8."]

    if not text:
        return [], ["Arquivo CSV vazio."]

    reader = csv.DictReader(io.StringIO(text))

    if not reader.fieldnames:
        return [], ["CSV não tem cabeçalho."]

    fieldnames_lower = {f.strip().lower() for f in reader.fieldnames}
    col_errors = _validate_columns(fieldnames_lower)
    if col_errors:
        return [], col_errors

    raw_rows = list(reader)
    if not raw_rows:
        return [], ["CSV não tem dados além do cabeçalho."]
    if len(raw_rows) > MAX_ROWS:
        return [], [f"Máximo de {MAX_ROWS} contatos por importação. Seu arquivo tem {len(raw_rows)} linhas."]

    return _validate_rows(raw_rows)


def parse_xlsx(xlsx_bytes: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse and validate Excel (.xlsx) bytes. Returns (rows, errors)."""
    from io import BytesIO

    from openpyxl import load_workbook

    try:
        wb = load_workbook(BytesIO(xlsx_bytes), read_only=True, data_only=True)
    except Exception:
        return [], ["Não foi possível ler o arquivo Excel. Verifique se é um .xlsx válido."]

    ws = wb.active
    if ws is None:
        return [], ["Planilha Excel vazia."]

    all_rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not all_rows:
        return [], ["Planilha Excel vazia."]

    header_row = all_rows[0]
    fieldnames = [str(h).strip().lower() for h in header_row if h is not None]

    if not fieldnames:
        return [], ["Planilha não tem cabeçalho."]

    col_errors = _validate_columns(set(fieldnames))
    if col_errors:
        return [], col_errors

    data_rows = all_rows[1:]
    if not data_rows:
        return [], ["Planilha não tem dados além do cabeçalho."]
    if len(data_rows) > MAX_ROWS:
        return [], [f"Máximo de {MAX_ROWS} contatos por importação. Seu arquivo tem {len(data_rows)} linhas."]

    raw_rows: list[dict[str, str]] = []
    for row_tuple in data_rows:
        row_dict: dict[str, str] = {}
        for col_idx, col_name in enumerate(fieldnames):
            val = row_tuple[col_idx] if col_idx < len(row_tuple) else None
            row_dict[col_name] = str(val).strip() if val is not None else ""
        raw_rows.append(row_dict)

    return _validate_rows(raw_rows)


async def download_file(file_id: str) -> bytes:
    """Download a file from Telegram by file_id."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/getFile",
            params={"file_id": file_id},
        )
        resp.raise_for_status()
        file_path = resp.json()["result"]["file_path"]

        file_resp = await client.get(
            f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{file_path}",
        )
        file_resp.raise_for_status()
        return file_resp.content
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_import_contacts.py -v`
Expected: All tests PASS

- [ ] **Step 6: Delete old import_csv.py**

```bash
rm alfred/services/import_csv.py
```

- [ ] **Step 7: Commit**

```bash
git add alfred/services/import_contacts.py alfred/services/import_csv.py tests/test_import_contacts.py
git commit -m "feat: import_contacts module with CSV + Excel parsing"
```

---

## Task 3: Duplicate detection + grouped preview

**Files:**
- Modify: `alfred/services/import_contacts.py`
- Modify: `tests/test_import_contacts.py`

- [ ] **Step 1: Write failing tests for check_duplicates**

```python
# append to tests/test_import_contacts.py
from unittest.mock import AsyncMock, MagicMock, patch


class TestCheckDuplicates:
    @pytest.mark.asyncio
    async def test_separates_clean_and_duplicates(self) -> None:
        from alfred.services.import_contacts import check_duplicates

        rows = [
            {"display_name": "João Silva", "company": "X"},
            {"display_name": "Maria Santos", "company": "Y"},
            {"display_name": "Pedro Lima", "company": "Z"},
        ]

        async def fake_find(user_id: str, display_name: str, threshold: float = 0.75) -> list[dict]:
            if display_name == "João Silva":
                return [{"id": "existing-1", "display_name": "João Silva", "company": "BTG"}]
            return []

        with patch("alfred.services.import_contacts.find_similar_contacts", side_effect=fake_find):
            clean, dupes = await check_duplicates(user_id="u1", rows=rows)

        assert len(clean) == 2
        assert len(dupes) == 1
        assert dupes[0]["csv_row"]["display_name"] == "João Silva"
        assert dupes[0]["existing"]["id"] == "existing-1"

    @pytest.mark.asyncio
    async def test_all_clean(self) -> None:
        from alfred.services.import_contacts import check_duplicates

        rows = [{"display_name": "Novo Contato", "company": "X"}]

        with patch(
            "alfred.services.import_contacts.find_similar_contacts",
            AsyncMock(return_value=[]),
        ):
            clean, dupes = await check_duplicates(user_id="u1", rows=rows)

        assert len(clean) == 1
        assert len(dupes) == 0
```

- [ ] **Step 2: Write failing tests for build_grouped_preview**

```python
# append to tests/test_import_contacts.py
class TestBuildGroupedPreview:
    def test_clean_only(self) -> None:
        from alfred.services.import_contacts import build_grouped_preview

        clean = [{"display_name": "Ana", "company": "X", "cadence_days": 15}]
        result = build_grouped_preview(clean, [])
        assert "1 contato" in result
        assert "Ana" in result
        assert "⚠️" not in result

    def test_with_duplicates(self) -> None:
        from alfred.services.import_contacts import build_grouped_preview

        clean = [{"display_name": "Ana", "cadence_days": 15}]
        dupes = [
            {
                "csv_row": {"display_name": "João", "company": "X"},
                "existing": {"display_name": "João Silva", "company": "BTG"},
            }
        ]
        result = build_grouped_preview(clean, dupes)
        assert "✅" in result
        assert "⚠️" in result
        assert "João" in result
        assert "BTG" in result
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_import_contacts.py::TestCheckDuplicates tests/test_import_contacts.py::TestBuildGroupedPreview -v`
Expected: FAIL — functions not defined

- [ ] **Step 4: Implement check_duplicates and build_grouped_preview**

Append to `alfred/services/import_contacts.py`:

```python
async def check_duplicates(
    user_id: str,
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Separate rows into clean (no match) and duplicates (with existing match).

    Returns (clean_rows, duplicates) where each duplicate is:
        {"csv_row": {...}, "existing": {"id": ..., "display_name": ..., "company": ...}}
    """
    from alfred.services.contacts import find_similar_contacts

    clean: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []

    for row in rows:
        similar = await find_similar_contacts(user_id=user_id, display_name=row["display_name"])
        if similar:
            duplicates.append({"csv_row": row, "existing": similar[0]})
        else:
            clean.append(row)

    return clean, duplicates


def build_grouped_preview(
    clean: list[dict[str, Any]],
    duplicates: list[dict[str, Any]],
) -> str:
    """Build grouped preview: clean contacts + duplicates."""
    total = len(clean) + len(duplicates)
    s = "s" if total != 1 else ""
    lines = [f"📋 Arquivo válido — {total} contato{s} encontrado{s}:\n"]

    if clean:
        sc = "s" if len(clean) != 1 else ""
        lines.append(f"✅ *{len(clean)} contato{sc} novo{sc}:*")
        for c in clean[:10]:
            parts = []
            if c.get("company"):
                parts.append(c["company"])
            if c.get("role"):
                parts.append(c["role"])
            parts.append(f"{c.get('cadence_days', 15)}d")
            lines.append(f"• {c['display_name']} — {' · '.join(parts)}")
        if len(clean) > 10:
            lines.append(f"_...e mais {len(clean) - 10} contatos_")
        lines.append("")

    if duplicates:
        sd = "s" if len(duplicates) != 1 else ""
        lines.append(f"⚠️ *{len(duplicates)} já existe{'' if len(duplicates) == 1 else 'm'} na sua base:*")
        for d in duplicates:
            csv_name = d["csv_row"]["display_name"]
            csv_company = d["csv_row"].get("company", "sem empresa")
            ex_name = d["existing"]["display_name"]
            ex_company = d["existing"].get("company") or "sem empresa"
            lines.append(f"• {csv_name} (CSV: {csv_company}) → já existe ({ex_name}, {ex_company})")
        lines.append("")

    return "\n".join(lines)


def build_duplicate_comparison(dup: dict[str, Any], index: int, total: int) -> str:
    """Build side-by-side comparison for individual duplicate review."""
    csv_row = dup["csv_row"]
    existing = dup["existing"]

    lines = [f"📊 *Duplicata {index + 1}/{total}* — {csv_row['display_name']}\n"]

    lines.append("📄 *Dados do arquivo:*")
    for field in ["company", "role", "cadence_days", "relationship_type", "tags", "how_we_met"]:
        val = csv_row.get(field)
        if val:
            label = field.replace("_", " ").title()
            if isinstance(val, list):
                val = ", ".join(val)
            lines.append(f"  {label}: {val}")

    lines.append("")
    lines.append("👤 *Contato existente:*")
    for field in ["company", "role", "cadence_days", "relationship_type", "tags", "how_we_met"]:
        val = existing.get(field)
        if val:
            label = field.replace("_", " ").title()
            if isinstance(val, list):
                val = ", ".join(val)
            lines.append(f"  {label}: {val}")

    return "\n".join(lines)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_import_contacts.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add alfred/services/import_contacts.py tests/test_import_contacts.py
git commit -m "feat: duplicate detection and grouped preview for import"
```

---

## Task 4: Merge, replace, and execute_import

**Files:**
- Modify: `alfred/services/import_contacts.py`
- Modify: `tests/test_import_contacts.py`

- [ ] **Step 1: Write failing tests for merge_contact**

```python
# append to tests/test_import_contacts.py
class TestMergeContact:
    @pytest.mark.asyncio
    async def test_fills_empty_fields_only(self) -> None:
        from alfred.services.import_contacts import merge_contact

        existing = {"id": "c-1", "display_name": "João", "company": "BTG", "role": None, "tags": []}
        fake_db = MagicMock()
        fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=existing)
        fake_db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock()

        with patch("alfred.services.import_contacts.get_db", return_value=fake_db):
            result = await merge_contact(
                user_id="u1",
                existing_id="c-1",
                csv_row={"display_name": "João Silva", "company": "Empresa X", "role": "CEO", "tags": ["vip"]},
            )

        update_call = fake_db.table.return_value.update.call_args[0][0]
        assert update_call["role"] == "CEO"
        assert update_call["tags"] == ["vip"]
        assert "company" not in update_call  # BTG already filled, keep it
        assert "mesclado" in result.lower() or "Mesclado" in result


class TestReplaceContact:
    @pytest.mark.asyncio
    async def test_overwrites_all_fields(self) -> None:
        from alfred.services.import_contacts import replace_contact

        fake_db = MagicMock()
        fake_db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock()

        with patch("alfred.services.import_contacts.get_db", return_value=fake_db):
            result = await replace_contact(
                user_id="u1",
                existing_id="c-1",
                csv_row={"display_name": "João", "company": "Nova Empresa", "role": "CTO"},
            )

        update_call = fake_db.table.return_value.update.call_args[0][0]
        assert update_call["company"] == "Nova Empresa"
        assert update_call["role"] == "CTO"
        assert "substituído" in result.lower() or "Substituído" in result
```

- [ ] **Step 2: Write failing tests for execute_import**

```python
# append to tests/test_import_contacts.py
class TestExecuteImport:
    @pytest.mark.asyncio
    async def test_creates_clean_and_applies_decisions(self) -> None:
        from alfred.services.import_contacts import execute_import

        clean_rows = [{"display_name": "Ana", "company": "X"}]
        duplicates = [
            {"csv_row": {"display_name": "João", "company": "Y"}, "existing": {"id": "c-1", "display_name": "João"}},
            {"csv_row": {"display_name": "Maria", "company": "Z"}, "existing": {"id": "c-2", "display_name": "Maria"}},
        ]
        decisions = {0: "skip", 1: "import_new"}

        with (
            patch("alfred.services.import_contacts.create_contact_confirmed", AsyncMock(return_value="ok")) as mock_create,
            patch("alfred.services.import_contacts.merge_contact", AsyncMock(return_value="ok")),
            patch("alfred.services.import_contacts.replace_contact", AsyncMock(return_value="ok")),
        ):
            result = await execute_import("u1", clean_rows, duplicates, decisions)

        assert result["created"] == 2  # Ana + Maria (import_new)
        assert result["skipped"] == 1
        assert result["merged"] == 0
        assert result["replaced"] == 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_import_contacts.py::TestMergeContact tests/test_import_contacts.py::TestReplaceContact tests/test_import_contacts.py::TestExecuteImport -v`
Expected: FAIL

- [ ] **Step 4: Implement merge_contact, replace_contact, execute_import**

Append to `alfred/services/import_contacts.py`:

```python
from alfred.db.client import get_db


async def merge_contact(user_id: str, existing_id: str, csv_row: dict[str, Any]) -> str:
    """Update existing contact: fill empty fields with CSV data, keep existing values."""
    db = get_db()
    existing = (
        db.table("contacts")
        .select("*")
        .eq("id", existing_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    ).data

    mergeable_fields = ["company", "role", "relationship_type", "how_we_met", "tags"]
    updates: dict[str, Any] = {}

    for field in mergeable_fields:
        existing_val = existing.get(field)
        csv_val = csv_row.get(field)
        if csv_val and not existing_val:
            updates[field] = csv_val

    if csv_row.get("cadence_days") and not existing.get("cadence_days"):
        updates["cadence_days"] = csv_row["cadence_days"]

    if updates:
        db.table("contacts").update(updates).eq("id", existing_id).eq("user_id", user_id).execute()
        fields_str = ", ".join(updates.keys())
        log.info("import.merged", user_id=user_id, contact_id=existing_id, fields=fields_str)
        return f"Mesclado: {existing['display_name']} — campos atualizados: {fields_str}"

    return f"Mesclado: {existing['display_name']} — nenhum campo novo para atualizar"


async def replace_contact(user_id: str, existing_id: str, csv_row: dict[str, Any]) -> str:
    """Overwrite existing contact fields with CSV data."""
    db = get_db()
    replaceable_fields = ["display_name", "company", "role", "cadence_days", "relationship_type", "tags", "how_we_met"]
    updates: dict[str, Any] = {}

    for field in replaceable_fields:
        if field in csv_row:
            updates[field] = csv_row[field]

    if updates:
        db.table("contacts").update(updates).eq("id", existing_id).eq("user_id", user_id).execute()

    log.info("import.replaced", user_id=user_id, contact_id=existing_id)
    return f"Substituído: campos de {csv_row['display_name']} sobrescritos"


async def execute_import(
    user_id: str,
    clean_rows: list[dict[str, Any]],
    duplicates: list[dict[str, Any]],
    decisions: dict[int, str],
) -> dict[str, Any]:
    """Execute full import: create clean contacts + apply duplicate decisions.

    Returns {"created": N, "skipped": N, "merged": N, "replaced": N, "merged_details": [...]}
    """
    from alfred.services.contacts import create_contact_confirmed

    created = 0
    skipped = 0
    merged = 0
    replaced = 0
    merged_details: list[str] = []

    for row in clean_rows:
        await create_contact_confirmed(user_id=user_id, **row)
        created += 1

    for idx, dup in enumerate(duplicates):
        action = decisions.get(idx, "skip")
        csv_row = dup["csv_row"]
        existing_id = dup["existing"]["id"]

        if action == "skip":
            skipped += 1
        elif action == "import_new":
            await create_contact_confirmed(user_id=user_id, **csv_row)
            created += 1
        elif action == "merge":
            result = await merge_contact(user_id=user_id, existing_id=existing_id, csv_row=csv_row)
            merged += 1
            merged_details.append(result)
        elif action == "replace":
            await replace_contact(user_id=user_id, existing_id=existing_id, csv_row=csv_row)
            replaced += 1

    log.info(
        "import.completed",
        user_id=user_id,
        created=created,
        skipped=skipped,
        merged=merged,
        replaced=replaced,
    )
    return {
        "created": created,
        "skipped": skipped,
        "merged": merged,
        "replaced": replaced,
        "merged_details": merged_details,
    }


def build_import_report(result: dict[str, Any]) -> str:
    """Build final import report message."""
    lines = ["✅ *Importação concluída\\!*\n"]

    sc = "s" if result["created"] != 1 else ""
    lines.append(f"• {result['created']} contato{sc} criado{sc}")

    if result["skipped"]:
        ss = "s" if result["skipped"] != 1 else ""
        lines.append(f"• {result['skipped']} duplicata{ss} pulado{ss}")

    if result["merged"]:
        sm = "s" if result["merged"] != 1 else ""
        lines.append(f"• {result['merged']} mesclado{sm}")
        for detail in result.get("merged_details", []):
            lines.append(f"  ↳ {detail}")

    if result["replaced"]:
        sr = "s" if result["replaced"] != 1 else ""
        lines.append(f"• {result['replaced']} substituído{sr}")

    return "\n".join(lines)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_import_contacts.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add alfred/services/import_contacts.py tests/test_import_contacts.py
git commit -m "feat: merge, replace, and execute_import for contact import v2"
```

---

## Task 5: New keyboard factories

**Files:**
- Modify: `alfred/bot/keyboards.py`
- Create: `tests/test_keyboards.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_keyboards.py

def test_import_preview_keyboard_has_three_buttons() -> None:
    from alfred.bot.keyboards import import_preview_keyboard

    kb = import_preview_keyboard("user-123")
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert len(buttons) == 3
    assert any("import:clean_and_skip:" in btn.callback_data for btn in buttons)
    assert any("import:import_all:" in btn.callback_data for btn in buttons)
    assert any("import:review:" in btn.callback_data for btn in buttons)


def test_import_preview_keyboard_no_duplicates() -> None:
    from alfred.bot.keyboards import import_preview_keyboard

    kb = import_preview_keyboard("user-123", has_duplicates=False)
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert len(buttons) == 2
    assert any("import:confirm_all:" in btn.callback_data for btn in buttons)
    assert any("import:cancel" in btn.callback_data for btn in buttons)


def test_duplicate_review_keyboard_has_four_buttons() -> None:
    from alfred.bot.keyboards import duplicate_review_keyboard

    kb = duplicate_review_keyboard("user-123", 0)
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert len(buttons) == 4
    assert any("dup_skip" in btn.callback_data for btn in buttons)
    assert any("dup_new" in btn.callback_data for btn in buttons)
    assert any("dup_merge" in btn.callback_data for btn in buttons)
    assert any("dup_replace" in btn.callback_data for btn in buttons)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_keyboards.py -v`
Expected: FAIL

- [ ] **Step 3: Implement new keyboard factories**

Add to `alfred/bot/keyboards.py`:

```python
def import_preview_keyboard(user_id: str, has_duplicates: bool = True) -> InlineKeyboardMarkup:
    """Grouped preview keyboard: 3 options when duplicates exist, 2 when clean."""
    if has_duplicates:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Importar novos + Pular duplicatas", callback_data=f"import:clean_and_skip:{user_id}")],
            [InlineKeyboardButton("📥 Importar todos como novos", callback_data=f"import:import_all:{user_id}")],
            [InlineKeyboardButton("🔍 Revisar duplicatas um a um", callback_data=f"import:review:{user_id}")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirmar importação", callback_data=f"import:confirm_all:{user_id}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="import:cancel")],
    ])


def duplicate_review_keyboard(user_id: str, index: int) -> InlineKeyboardMarkup:
    """4 action buttons for reviewing a single duplicate."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏭ Pular", callback_data=f"import:dup_skip:{user_id}:{index}"),
            InlineKeyboardButton("➕ Importar novo", callback_data=f"import:dup_new:{user_id}:{index}"),
        ],
        [
            InlineKeyboardButton("🔀 Mesclar", callback_data=f"import:dup_merge:{user_id}:{index}"),
            InlineKeyboardButton("🔄 Substituir", callback_data=f"import:dup_replace:{user_id}:{index}"),
        ],
    ])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_keyboards.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add alfred/bot/keyboards.py tests/test_keyboards.py
git commit -m "feat: import preview and duplicate review keyboards"
```

---

## Task 6: Update handlers + app.py for full import v2 flow

**Files:**
- Modify: `alfred/bot/handlers.py`
- Modify: `alfred/bot/app.py`

- [ ] **Step 1: Update app.py to accept .xlsx files**

In `alfred/bot/app.py`, change the document handler filter:

```python
# Before:
app.add_handler(MessageHandler(filters.Document.FileExtension("csv"), import_document_handler))

# After:
app.add_handler(MessageHandler(
    filters.Document.FileExtension("csv") | filters.Document.FileExtension("xlsx"),
    import_document_handler,
))
```

- [ ] **Step 2: Update import_document_handler in handlers.py**

Replace the existing `import_document_handler` function. Update all imports from `import_csv` to `import_contacts`. The new handler detects format, runs duplicate check, and shows grouped preview:

```python
async def import_document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle CSV/XLSX file upload — validate, detect duplicates, show grouped preview."""
    if not update.effective_user or not update.message or not update.message.document:
        return
    from alfred.bot.keyboards import import_preview_keyboard
    from alfred.services.import_contacts import (
        build_grouped_preview,
        check_duplicates,
        download_file,
        parse_and_validate,
        parse_xlsx,
    )

    tg_user = update.effective_user
    doc = update.message.document
    file_name = (doc.file_name or "").lower()

    log.info("import.file_received", telegram_id=tg_user.id, file_name=file_name)

    try:
        file_bytes = await download_file(doc.file_id)
    except Exception:
        log.exception("import.download_failed")
        await update.message.reply_text("Não consegui baixar o arquivo. Tente novamente.")
        return

    if file_name.endswith(".xlsx"):
        rows, errors = parse_xlsx(file_bytes)
    else:
        rows, errors = parse_and_validate(file_bytes)

    if errors:
        error_text = "❌ *Erros encontrados no arquivo:*\n\n" + "\n".join(f"• {e}" for e in errors)
        await update.message.reply_text(error_text, parse_mode="Markdown")
        return

    db = get_db()
    user_result = db.table("users").select("id").eq("telegram_id", tg_user.id).single().execute()
    if not user_result.data:
        await update.message.reply_text("Use /start primeiro para se registrar.")
        return
    user_id = user_result.data["id"]

    clean, duplicates = await check_duplicates(user_id=user_id, rows=rows)

    context.user_data[f"import:{user_id}"] = {
        "clean_rows": clean,
        "duplicates": duplicates,
        "decisions": {},
        "current_review_index": 0,
    }

    preview = build_grouped_preview(clean, duplicates)
    has_duplicates = len(duplicates) > 0
    keyboard = import_preview_keyboard(user_id, has_duplicates=has_duplicates)

    await update.message.reply_text(preview, parse_mode="Markdown", reply_markup=keyboard)
```

- [ ] **Step 3: Update import_command_handler to mention xlsx**

In the existing `import_command_handler`, update the instruction text to mention Excel:

```python
# Change line mentioning "Salve como CSV" to:
"3\\. Salve como CSV ou envie a planilha Excel \\(\\.xlsx\\) direto\n"
```

- [ ] **Step 4: Replace _handle_import_callback with v2 logic**

Replace the entire `_handle_import_callback` function with the new version that handles all callback scenarios:

```python
async def _handle_import_callback(query: object, data: str) -> None:
    """Handle all import callbacks: preview actions, duplicate review decisions."""
    from telegram import CallbackQuery

    from alfred.bot.keyboards import duplicate_review_keyboard, import_preview_keyboard
    from alfred.db.client import get_db
    from alfred.services.import_contacts import (
        build_duplicate_comparison,
        build_import_report,
        execute_import,
    )

    q: CallbackQuery = query  # type: ignore[assignment]

    if data == "import:cancel":
        # Clean state for all possible user keys
        if q.from_user and hasattr(q, "bot"):
            for key in list(q.bot_data or {}):
                pass  # bot_data not used
        await q.edit_message_text("❌ Importação cancelada.")
        return

    parts = data.split(":")
    # All other actions have at least import:action:user_id
    if len(parts) < 3:
        await q.edit_message_text("Ação inválida.")
        return

    action = parts[1]
    user_id = parts[2]

    # Get import state from context — we need the context from the handler
    # Since callbacks go through callback_handler, we access user_data via the query message
    # We'll retrieve state from a module-level dict as fallback
    from alfred.bot.handlers import _get_import_state, _clear_import_state

    state = _get_import_state(user_id)
    if not state:
        await q.edit_message_text("Sessão de importação expirada. Envie o arquivo novamente.")
        return

    clean_rows = state["clean_rows"]
    duplicates = state["duplicates"]
    decisions = state["decisions"]

    if action == "confirm_all":
        # No duplicates — just import clean rows
        await q.edit_message_text("⏳ Importando contatos...")
        result = await execute_import(user_id, clean_rows, [], {})
        _clear_import_state(user_id)
        await q.edit_message_text(build_import_report(result), parse_mode="MarkdownV2")

    elif action == "clean_and_skip":
        # Import clean + skip all duplicates
        await q.edit_message_text("⏳ Importando contatos...")
        all_skip = {i: "skip" for i in range(len(duplicates))}
        result = await execute_import(user_id, clean_rows, duplicates, all_skip)
        _clear_import_state(user_id)
        await q.edit_message_text(build_import_report(result), parse_mode="MarkdownV2")

    elif action == "import_all":
        # Import everything as new
        await q.edit_message_text("⏳ Importando contatos...")
        all_new = {i: "import_new" for i in range(len(duplicates))}
        result = await execute_import(user_id, clean_rows, duplicates, all_new)
        _clear_import_state(user_id)
        await q.edit_message_text(build_import_report(result), parse_mode="MarkdownV2")

    elif action == "review":
        # Start individual review
        state["current_review_index"] = 0
        dup = duplicates[0]
        comparison = build_duplicate_comparison(dup, 0, len(duplicates))
        keyboard = duplicate_review_keyboard(user_id, 0)
        await q.edit_message_text(comparison, parse_mode="Markdown", reply_markup=keyboard)

    elif action.startswith("dup_"):
        # Individual duplicate decision
        if len(parts) < 4:
            return
        dup_action = action.replace("dup_", "")  # skip, new, merge, replace
        dup_index = int(parts[3])

        action_map = {"skip": "skip", "new": "import_new", "merge": "merge", "replace": "replace"}
        decisions[dup_index] = action_map.get(dup_action, "skip")

        next_index = dup_index + 1
        if next_index < len(duplicates):
            # Show next duplicate
            state["current_review_index"] = next_index
            dup = duplicates[next_index]
            comparison = build_duplicate_comparison(dup, next_index, len(duplicates))
            keyboard = duplicate_review_keyboard(user_id, next_index)
            await q.edit_message_text(comparison, parse_mode="Markdown", reply_markup=keyboard)
        else:
            # All reviewed — execute
            await q.edit_message_text("⏳ Importando contatos...")
            result = await execute_import(user_id, clean_rows, duplicates, decisions)
            _clear_import_state(user_id)
            await q.edit_message_text(build_import_report(result), parse_mode="MarkdownV2")
```

- [ ] **Step 5: Add state management helpers to handlers.py**

Add at module level in `handlers.py` (near the top, after imports):

```python
# Import state storage (keyed by user_id)
_import_states: dict[str, dict] = {}


def _get_import_state(user_id: str) -> dict | None:
    return _import_states.get(user_id)


def _set_import_state(user_id: str, state: dict) -> None:
    _import_states[user_id] = state


def _clear_import_state(user_id: str) -> None:
    _import_states.pop(user_id, None)
```

Then update `import_document_handler` to use `_set_import_state(user_id, {...})` instead of `context.user_data[f"import:{user_id}"]`.

- [ ] **Step 6: Update callback_handler routing**

The existing `callback_handler` already routes `import:` prefixed callbacks to `_handle_import_callback`. No change needed — the new callback data format (`import:clean_and_skip:...`, `import:dup_skip:...`) all start with `import:`.

- [ ] **Step 7: Update all remaining imports from import_csv to import_contacts**

Search and replace across all files:

```bash
grep -r "import_csv" alfred/ --include="*.py" -l
```

Update each file's imports from `alfred.services.import_csv` to `alfred.services.import_contacts`. Key files:
- `alfred/bot/handlers.py` — all import references
- Any other file referencing `import_csv`

- [ ] **Step 8: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS (some old import_csv tests may need path updates)

- [ ] **Step 9: Commit**

```bash
git add alfred/bot/handlers.py alfred/bot/app.py
git commit -m "feat: full import v2 flow with grouped preview and duplicate review"
```

---

## Task 7: Integration test + manual verification

**Files:**
- Modify: `tests/test_import_contacts.py`

- [ ] **Step 1: Write integration test for build_import_report**

```python
# append to tests/test_import_contacts.py
class TestBuildImportReport:
    def test_report_with_all_actions(self) -> None:
        from alfred.services.import_contacts import build_import_report

        result = {
            "created": 5,
            "skipped": 2,
            "merged": 1,
            "replaced": 1,
            "merged_details": ["Mesclado: João Silva — campos atualizados: company, role"],
        }
        report = build_import_report(result)
        assert "5 contatos" in report
        assert "2 duplicata" in report
        assert "1 mesclado" in report
        assert "1 substituído" in report
        assert "João Silva" in report

    def test_report_clean_only(self) -> None:
        from alfred.services.import_contacts import build_import_report

        result = {"created": 10, "skipped": 0, "merged": 0, "replaced": 0, "merged_details": []}
        report = build_import_report(result)
        assert "10 contatos" in report
        assert "duplicata" not in report
```

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_import_contacts.py
git commit -m "test: import report and integration tests"
```

- [ ] **Step 4: Manual verification checklist**

Test on Telegram:
1. `/import` → recebe template + instruções mencionando .xlsx
2. Upload CSV com 5 contatos novos → preview sem duplicatas → confirmar → 5 criados
3. Upload XLSX com 3 novos + 2 duplicatas → preview agrupado → "Importar novos + Pular" → 3 criados
4. Upload com duplicatas → "Revisar um a um" → Pular primeiro → Mesclar segundo → relatório correto
5. Upload CSV inválido (coluna errada) → erro claro
6. Cancelamento → "Importação cancelada"
