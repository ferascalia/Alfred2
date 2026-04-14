-- 0005: Drop unused tables + weekday cadence scheduling

-- ─────────────────────────────────────────
-- DROP UNUSED TABLES
-- Tabelas que existem no banco mas nunca são referenciadas no código Python.
-- scheduled_followups dropar primeiro (tem FK para tenants).
-- ─────────────────────────────────────────
DROP TABLE IF EXISTS scheduled_followups CASCADE;
DROP TABLE IF EXISTS agent_memory CASCADE;
DROP TABLE IF EXISTS companies CASCADE;
DROP TABLE IF EXISTS contact_context CASCADE;
DROP TABLE IF EXISTS message_drafts CASCADE;
DROP TABLE IF EXISTS interaction_summaries CASCADE;
DROP TABLE IF EXISTS tenants CASCADE;

-- ─────────────────────────────────────────
-- WEEKDAY CADENCE
-- nudge_weekday: 0=Segunda … 6=Domingo (NULL = usa cadence_days)
-- ─────────────────────────────────────────
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS nudge_weekday SMALLINT
    CHECK (nudge_weekday BETWEEN 0 AND 6);

-- ─────────────────────────────────────────
-- UPDATE STORED PROCEDURE
-- Quando nudge_weekday está definido, next_nudge_at é calculado como
-- a próxima ocorrência daquele dia da semana após a interação.
-- Quando NULL, comportamento original (cadence_days).
-- ─────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_contact_after_interaction(
    p_contact_id uuid,
    p_happened_at timestamptz
)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    v_cadence        int;
    v_nudge_weekday  smallint;
    v_pg_target      int;
    v_current_dow    int;
    v_days_until     int;
    v_next_nudge     timestamptz;
BEGIN
    SELECT cadence_days, nudge_weekday
    INTO v_cadence, v_nudge_weekday
    FROM contacts WHERE id = p_contact_id;

    IF v_nudge_weekday IS NOT NULL THEN
        -- Nossa convenção: 0=Seg…6=Dom
        -- PG EXTRACT(DOW):  0=Dom, 1=Seg…6=Sab
        -- Conversão: pg_dow = (our_weekday + 1) % 7
        v_pg_target   := (v_nudge_weekday + 1) % 7;
        v_current_dow := EXTRACT(DOW FROM p_happened_at)::int;
        v_days_until  := (v_pg_target - v_current_dow + 7) % 7;
        IF v_days_until = 0 THEN v_days_until := 7; END IF;
        v_next_nudge  := date_trunc('day', p_happened_at) + (v_days_until || ' days')::interval;
    ELSE
        -- Comportamento original
        v_next_nudge := date_trunc('day', p_happened_at + (v_cadence || ' days')::interval);
    END IF;

    UPDATE contacts
    SET
        last_interaction_at = p_happened_at,
        next_nudge_at       = v_next_nudge
    WHERE id = p_contact_id;
END;
$$;
