# Timed Follow-Ups — Design Spec

**Date:** 2026-05-07  
**Status:** Draft  
**Branch:** `feat/calendar-scheduling`

---

## Context

Alfred's follow-up system currently only supports date-level scheduling. When a user says "remind me to call João at 5PM", Alfred stores `next_nudge_at` as midnight UTC on that date, and the `nudge_scan` pg_cron job runs once daily at 08:00 UTC. The reminder arrives the next morning — not at 5PM.

Real users (Felippe's friends using Alfred) need calendar-grade timed reminders: "at 5PM, remind me to do X" and have Alfred deliver at 5PM.

**Goal:** Allow users to set follow-ups with a specific time, and have Alfred deliver the reminder within ~1 minute of the target time.

---

## Approach

**Per-minute pg_cron scan** — a second, dedicated pg_cron job that runs every minute and handles only timed follow-ups. The existing daily 8AM scan for cadence-based nudges stays completely untouched.

### Why this approach

- Uses existing Supabase infrastructure (pg_cron + pg_net) — no new dependencies
- A SELECT on an indexed column returning 0 rows 99.9% of the time is sub-millisecond
- HTTP calls only happen when there's actually a reminder due
- The existing nudge pipeline (`/jobs/nudge` → Claude → Telegram) handles delivery without changes

---

## Design

### 1. Database Migration — `0012_timed_follow_ups.sql`

#### a) New column on `contacts`

```sql
ALTER TABLE contacts ADD COLUMN time_specific BOOLEAN DEFAULT FALSE;
```

Separates timed reminders (per-minute scan) from cadence nudges (daily scan).

#### b) New function: `timed_nudge_scan()`

```sql
CREATE OR REPLACE FUNCTION timed_nudge_scan()
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    railway_url text := current_setting('app.railway_nudge_url', true);
    jobs_secret text := current_setting('app.jobs_secret', true);
    rec record;
BEGIN
    -- Atomically claim due timed reminders (prevents duplicate firing)
    FOR rec IN
        UPDATE contacts
        SET next_nudge_at = NULL,
            time_specific = FALSE
        WHERE status = 'active'
          AND time_specific = TRUE
          AND next_nudge_at IS NOT NULL
          AND next_nudge_at <= now()
        RETURNING id AS contact_id
    LOOP
        PERFORM net.http_post(
            url := railway_url,
            headers := jsonb_build_object(
                'Content-Type', 'application/json',
                'X-Jobs-Secret', jobs_secret
            ),
            body := jsonb_build_object('contact_id', rec.contact_id)
        );
    END LOOP;
END;
$$;
```

Key design decision: the `UPDATE ... RETURNING` is atomic. The next minute's scan cannot pick up the same contact because `next_nudge_at` is already NULL and `time_specific` is already FALSE by the time the HTTP call fires.

#### c) Schedule: every minute

```sql
SELECT cron.schedule(
    'alfred-timed-nudge-scan',
    '* * * * *',
    'SELECT timed_nudge_scan()'
);
```

#### d) Modify existing `nudge_scan()` to exclude timed reminders

```sql
CREATE OR REPLACE FUNCTION nudge_scan() ...
    -- Add to WHERE clause:
    AND (time_specific IS NOT TRUE)
```

This prevents the daily 8AM scan from firing a reminder that's scheduled for 5PM.

### 2. Tool Schema — Add `time` to `set_follow_up`

File: `alfred/agent/tools/schemas.py`

Add to SET_FOLLOW_UP_SCHEMA's `input_schema.properties`:

```python
"time": {
    "type": "string",
    "description": (
        "Horário específico para o lembrete no formato 24h (ex: '17:00', '09:30'). "
        "Opcional. Quando informado, Alfred envia o lembrete no horário exato. "
        "Quando omitido, o lembrete é enviado no scan das 8h da manhã."
    ),
}
```

`required` stays `["contact_id", "date"]` — time is optional.

### 3. Service — Timezone-aware timestamp storage

File: `alfred/services/contacts.py` — `set_follow_up()`

When `time` parameter is provided:

1. **Look up user timezone** from `users.timezone` (default: `America/Sao_Paulo`)
2. **Parse date + time** in user's local timezone using `zoneinfo.ZoneInfo` (Python stdlib)
3. **Convert to UTC** for storage in `next_nudge_at`
4. **Set `time_specific = TRUE`** in the update payload

When `time` is NOT provided: existing behavior unchanged (midnight UTC, `time_specific = FALSE`).

```python
from zoneinfo import ZoneInfo
from datetime import datetime, date as date_type

async def set_follow_up(
    user_id: str, contact_id: str, date: str,
    note: str | None = None, time: str | None = None,
) -> str:
    parsed_date = date_type.fromisoformat(date)

    if time:
        # Look up user timezone
        user_row = db.table("users").select("timezone").eq("id", user_id).single().execute()
        tz = ZoneInfo(user_row.data.get("timezone", "America/Sao_Paulo"))

        hour, minute = map(int, time.split(":"))
        local_dt = datetime(parsed_date.year, parsed_date.month, parsed_date.day, hour, minute, tzinfo=tz)
        utc_dt = local_dt.astimezone(ZoneInfo("UTC"))

        next_nudge_at = utc_dt.isoformat()
        update_data = {"next_nudge_at": next_nudge_at, "follow_up_note": note, "time_specific": True}
    else:
        # Existing behavior — midnight UTC
        next_nudge_at = f"{parsed_date.isoformat()}T00:00:00+00:00"
        update_data = {"next_nudge_at": next_nudge_at, "follow_up_note": note, "time_specific": False}

    db.table("contacts").update(update_data).eq("id", contact_id).eq("user_id", user_id).execute()
```

### 4. Dispatch — No changes needed

`dispatch.py` already uses `**tool_input` for `set_follow_up`, so the new `time` parameter passes through automatically.

### 5. Agent Prompt — Time awareness

File: `alfred/agent/prompt_sections.py`

Add guidance to PROMPT_ACTION or PROMPT_DATE_CONFIRM:

```
## Follow-ups com horário
Quando o usuário mencionar um horário específico ("às 17h", "at 5PM", "depois do almoço às 14h"),
use o parâmetro `time` no formato 24h (ex: "17:00", "14:00").
Se o usuário diz um horário sem data, use a data de hoje — ou amanhã se o horário já passou.
Inclua o horário na mensagem de confirmação:
"📅 Follow-up com {nome} em {DD/MM/AAAA} às {HH:MM}"
```

### 6. Date Confirmation Guardrail — No changes needed

`date_confirmation.py` checks for `Confirmando:` prefix + a date pattern (`DD/MM` or `YYYY-MM-DD`). Adding a time after the date (e.g., "15/05/2026 às 17:00") doesn't interfere with the regex.

### 7. Nudge Delivery — No changes needed

`process_nudge()` in `alfred/jobs/nudge.py` already handles `follow_up_note` with `nudge_type = "scheduled"` and displays "📌 Follow-up agendado". Timed reminders flow through this exact same pipeline.

---

## Files Modified

| File | Change |
|------|--------|
| `supabase/migrations/0012_timed_follow_ups.sql` | **New** — column, function, cron schedule |
| `alfred/agent/tools/schemas.py` | Add `time` property to SET_FOLLOW_UP_SCHEMA |
| `alfred/services/contacts.py` | Add `time` param, timezone conversion, `time_specific` flag |
| `alfred/agent/prompt_sections.py` | Add time-awareness guidance |
| `tests/test_timed_follow_ups.py` | **New** — test timezone conversion, time parsing, service behavior |

## Files NOT Modified

| File | Why |
|------|-----|
| `alfred/jobs/nudge.py` | Already handles scheduled follow-ups |
| `alfred/main.py` | No new endpoints |
| `alfred/bot/handlers.py` | No UX changes |
| `alfred/bot/keyboards.py` | Same nudge keyboard |
| `alfred/services/nudges.py` | Same action handling |
| `alfred/agent/tools/dispatch.py` | Uses `**tool_input`, time passes through |
| `alfred/agent/guardrails/date_confirmation.py` | Regex still matches |

---

## User Experience Flow

1. **User:** "Alfred, me lembra de ligar pro João às 17h"
2. **Agent:** Identifies contact João, detects time "17:00", infers today's date
3. **Agent response:** "Confirmando:\n📅 Follow-up com João em 07/05/2026 às 17:00\nMotivo: ligar pro João"
4. **User clicks ✅** → guardrail approves → `set_follow_up(contact_id, "2026-05-07", note="ligar pro João", time="17:00")`
5. **Service:** Converts 17:00 BRT → 20:00 UTC, stores in `next_nudge_at`, sets `time_specific = TRUE`
6. **At 20:00 UTC (17:00 BRT):** `timed_nudge_scan()` picks it up, fires `/jobs/nudge`
7. **process_nudge:** Generates personalized "📌 Follow-up agendado" message with draft, sends to Telegram

---

## Edge Cases

| Case | Behavior |
|------|----------|
| Time already passed today | Agent should infer tomorrow (prompt guidance) |
| User says "after lunch" without exact time | Agent asks for specific time |
| User sets follow-up with date only (no time) | Existing behavior — midnight UTC, daily scan |
| User snoozes a timed nudge | Snooze handler already sets `next_nudge_at` + 7 days; `time_specific` resets to FALSE (reverts to daily scan) |
| Railway is down when scan fires | pg_net HTTP call fails silently; `next_nudge_at` was already cleared — nudge is lost. Acceptable for MVP; future: add retry queue |

---

## Verification

1. **Unit tests:** time parsing, timezone conversion (BRT → UTC), `time_specific` flag setting
2. **Migration test:** Apply migration, verify `timed_nudge_scan()` function exists, verify cron schedule
3. **Integration test (local):**
   - Set a follow-up with time via agent
   - Verify `contacts.next_nudge_at` has correct UTC timestamp
   - Verify `contacts.time_specific = TRUE`
4. **End-to-end test (Railway):**
   - Set a timed follow-up via Telegram
   - Wait for the target time
   - Confirm nudge arrives within ~1 minute
5. **Regression:** Verify daily 8AM nudges still work for cadence-based contacts (no `time_specific` flag)

---

## Future Considerations (NOT in this spec)

- **Recurring timed reminders** — "every Monday at 9AM" (combines cadence + time)
- **Retry on failure** — if pg_net call fails, re-queue the nudge
- **User timezone changes** — recalculate pending timed nudges if timezone updates
