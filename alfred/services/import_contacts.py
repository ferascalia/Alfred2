"""Bulk contact import via CSV or XLSX."""
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


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

def build_template_csv() -> bytes:
    """Generate a template CSV with one example row."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["display_name", "company", "role", "cadence_days", "relationship_type", "tags", "how_we_met"])
    writer.writerow(["João Silva", "Empresa X", "CEO", "15", "professional", "cliente|vip", "Evento Tech 2024"])
    writer.writerow(["Maria Santos", "Empresa Y", "Diretora", "30", "friend", "amiga", ""])
    # utf-8-sig adds BOM so Excel opens correctly without encoding issues
    return output.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------------------
# Shared validation helpers
# ---------------------------------------------------------------------------

def _validate_columns(fieldnames: set[str]) -> list[str]:
    """Validate column names; return list of error strings (empty = ok)."""
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


def _validate_rows(raw_rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate and coerce a list of raw string-valued dicts into contact dicts.

    Returns (rows, errors). Uses ``int(float(...))`` for cadence_days so that
    Excel numeric cells (which arrive as floats) are handled correctly.
    """
    errors: list[str] = []
    rows: list[dict[str, Any]] = []

    if not raw_rows:
        return [], ["Arquivo não tem dados além do cabeçalho."]

    if len(raw_rows) > MAX_ROWS:
        return [], [
            f"Máximo de {MAX_ROWS} contatos por importação. "
            f"Seu arquivo tem {len(raw_rows)} linhas."
        ]

    for i, raw_row in enumerate(raw_rows, start=2):  # line/row 1 = header
        display_name = raw_row.get("display_name", "")
        if not display_name:
            errors.append(f"Linha {i}: display_name é obrigatório e não pode estar vazio.")
            continue

        # Validate cadence_days
        cadence_days = 15
        cadence_raw = raw_row.get("cadence_days", "")
        if cadence_raw:
            try:
                # int(float(...)) handles cells that Excel stores as floats (e.g. "30.0")
                cadence_days = int(float(cadence_raw))
                if not (1 <= cadence_days <= 365):
                    errors.append(
                        f"Linha {i} ({display_name}): cadence_days deve ser entre 1 e 365, "
                        f"recebeu '{cadence_raw}'."
                    )
                    continue
            except ValueError:
                errors.append(
                    f"Linha {i} ({display_name}): cadence_days deve ser um número inteiro, "
                    f"recebeu '{cadence_raw}'."
                )
                continue

        # Validate relationship_type
        relationship_type: str | None = raw_row.get("relationship_type") or None
        if relationship_type and relationship_type not in VALID_RELATIONSHIP_TYPES:
            errors.append(
                f"Linha {i} ({display_name}): relationship_type inválido '{relationship_type}'. "
                f"Válidos: {', '.join(sorted(VALID_RELATIONSHIP_TYPES))}."
            )
            continue

        # Parse pipe-separated tags
        tags_raw = raw_row.get("tags", "")
        tags = [t.strip() for t in tags_raw.split("|") if t.strip()] if tags_raw else []

        contact: dict[str, Any] = {"display_name": display_name, "cadence_days": cadence_days}
        if raw_row.get("company"):
            contact["company"] = raw_row["company"]
        if raw_row.get("role"):
            contact["role"] = raw_row["role"]
        if relationship_type:
            contact["relationship_type"] = relationship_type
        if tags:
            contact["tags"] = tags
        if raw_row.get("how_we_met"):
            contact["how_we_met"] = raw_row["how_we_met"]

        rows.append(contact)

    return rows, errors


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def parse_and_validate(csv_bytes: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse and validate CSV bytes.

    Returns (rows, errors). If errors is non-empty, do not import.
    """
    # Attempt decoding (handle BOM and latin-1 fallback)
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

    # Normalise keys and values to lowercase stripped strings
    normalised: list[dict[str, str]] = [
        {k.strip().lower(): (v.strip() if v else "") for k, v in row.items() if k}
        for row in raw_rows
    ]

    return _validate_rows(normalised)


# ---------------------------------------------------------------------------
# XLSX parsing
# ---------------------------------------------------------------------------

def parse_xlsx(xlsx_bytes: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse and validate XLSX bytes.

    Returns (rows, errors). If errors is non-empty, do not import.
    """
    try:
        from openpyxl import load_workbook
    except ImportError:
        return [], ["openpyxl não está instalado. Execute: pip install openpyxl"]

    try:
        wb = load_workbook(filename=io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        return [], [f"Não foi possível abrir o arquivo Excel: {exc}"]

    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)

    # First row = headers
    try:
        header_row = next(rows_iter)
    except StopIteration:
        return [], ["Arquivo Excel vazio."]

    fieldnames = [str(h).strip().lower() if h is not None else "" for h in header_row]
    fieldnames_set = set(fieldnames) - {""}

    col_errors = _validate_columns(fieldnames_set)
    if col_errors:
        return [], col_errors

    # Build normalised dicts from remaining rows
    normalised: list[dict[str, str]] = []
    for row in rows_iter:
        # Skip completely empty rows
        if all(cell is None for cell in row):
            continue
        row_dict: dict[str, str] = {}
        for col_name, cell_val in zip(fieldnames, row):
            if not col_name:
                continue
            if cell_val is None:
                row_dict[col_name] = ""
            else:
                row_dict[col_name] = str(cell_val).strip()
        normalised.append(row_dict)

    wb.close()

    return _validate_rows(normalised)


# ---------------------------------------------------------------------------
# Preview helper
# ---------------------------------------------------------------------------

def build_preview(rows: list[dict[str, Any]]) -> str:
    n = len(rows)
    s = "s" if n != 1 else ""
    lines = [f"📋 *Arquivo válido — {n} contato{s} encontrado{s}:*\n"]

    for c in rows[:10]:
        parts = []
        if c.get("company"):
            parts.append(c["company"])
        if c.get("role"):
            parts.append(c["role"])
        if c.get("relationship_type"):
            parts.append(c["relationship_type"])
        parts.append(f"{c.get('cadence_days', 15)}d")
        lines.append(f"• {c['display_name']} — {' · '.join(parts)}")

    if n > 10:
        lines.append(f"_...e mais {n - 10} contatos_")

    lines.append("\nConfirma a importação?")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Download helper
# ---------------------------------------------------------------------------

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


# Backwards-compat alias
download_csv = download_file


# ---------------------------------------------------------------------------
# Bulk import
# ---------------------------------------------------------------------------

async def bulk_import(user_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Create contacts, skipping duplicates (via find_similar_contacts).

    Returns {"created": N, "skipped": [names]}.
    """
    from alfred.services.contacts import create_contact_confirmed, find_similar_contacts

    created = 0
    skipped: list[str] = []

    for contact in rows:
        name = contact["display_name"]
        similar = await find_similar_contacts(user_id=user_id, display_name=name)
        if similar:
            log.info("import.skipped_duplicate", user_id=user_id, display_name=name)
            skipped.append(name)
            continue
        await create_contact_confirmed(user_id=user_id, **contact)
        created += 1

    log.info("import.completed", user_id=user_id, created=created, skipped=len(skipped))
    return {"created": created, "skipped": skipped}
