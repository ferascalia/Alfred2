"""Bulk contact import via CSV."""
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
    # utf-8-sig adds BOM so Excel opens correctly without encoding issues
    return output.getvalue().encode("utf-8-sig")


def parse_and_validate(csv_bytes: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse and validate CSV bytes.

    Returns (rows, errors). If errors is non-empty, do not import.
    """
    errors: list[str] = []

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

    unknown = fieldnames_lower - VALID_COLUMNS
    if unknown:
        errors.append(
            f"Coluna(s) inválida(s): {', '.join(sorted(unknown))}. "
            f"Válidas: {', '.join(sorted(VALID_COLUMNS))}."
        )

    missing = REQUIRED_COLUMNS - fieldnames_lower
    if missing:
        errors.append(f"Coluna obrigatória ausente: {', '.join(sorted(missing))}.")

    if errors:
        return [], errors

    row_list = list(reader)

    if not row_list:
        return [], ["CSV não tem dados além do cabeçalho."]

    if len(row_list) > MAX_ROWS:
        return [], [f"Máximo de {MAX_ROWS} contatos por importação. Seu arquivo tem {len(row_list)} linhas."]

    rows: list[dict[str, Any]] = []
    for i, raw_row in enumerate(row_list, start=2):  # line 1 = header
        row = {k.strip().lower(): (v.strip() if v else "") for k, v in raw_row.items() if k}

        display_name = row.get("display_name", "")
        if not display_name:
            errors.append(f"Linha {i}: display_name é obrigatório e não pode estar vazio.")
            continue

        # Validate cadence_days
        cadence_days = 15
        cadence_raw = row.get("cadence_days", "")
        if cadence_raw:
            try:
                cadence_days = int(cadence_raw)
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

        # Validate relationship_type
        relationship_type: str | None = row.get("relationship_type") or None
        if relationship_type and relationship_type not in VALID_RELATIONSHIP_TYPES:
            errors.append(
                f"Linha {i} ({display_name}): relationship_type inválido '{relationship_type}'. "
                f"Válidos: {', '.join(sorted(VALID_RELATIONSHIP_TYPES))}."
            )
            continue

        # Parse pipe-separated tags
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


def build_preview(rows: list[dict[str, Any]]) -> str:
    n = len(rows)
    s = "s" if n != 1 else ""
    lines = [f"📋 *CSV válido — {n} contato{s} encontrado{s}:*\n"]

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


async def download_csv(file_id: str) -> bytes:
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
