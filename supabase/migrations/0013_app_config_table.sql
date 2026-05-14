-- Alfred — Replace GUC variables with app_config table
-- Supabase managed databases don't allow ALTER DATABASE SET for custom params.
-- This table stores runtime config readable by pg_cron functions.

-- 1. Config table
CREATE TABLE IF NOT EXISTS app_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

ALTER TABLE app_config ENABLE ROW LEVEL SECURITY;

CREATE POLICY "postgres_read_config" ON app_config
    FOR SELECT TO postgres USING (true);

-- 2. Insert config values
INSERT INTO app_config (key, value) VALUES
    ('railway_nudge_url',  'https://alfred-production-e9cb.up.railway.app/jobs/nudge'),
    ('railway_digest_url', 'https://alfred-production-e9cb.up.railway.app/jobs/digest'),
    ('jobs_secret',        'alfred-jobs-secret-2024')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

-- 3. Helper function
CREATE OR REPLACE FUNCTION get_app_config(config_key TEXT)
RETURNS TEXT
LANGUAGE sql STABLE SECURITY DEFINER
AS $$
    SELECT value FROM app_config WHERE key = config_key;
$$;

-- 4. Rewrite nudge_scan() — daily cadence nudges (skip timed)
CREATE OR REPLACE FUNCTION nudge_scan()
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    railway_url text := get_app_config('railway_nudge_url');
    jobs_secret text := get_app_config('jobs_secret');
    rec record;
BEGIN
    FOR rec IN
        SELECT c.id AS contact_id
        FROM contacts c
        WHERE c.status = 'active'
          AND c.next_nudge_at IS NOT NULL
          AND c.next_nudge_at <= now()
          AND (c.time_specific IS NOT TRUE)
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

-- 5. Rewrite timed_nudge_scan() — per-minute timed follow-ups
CREATE OR REPLACE FUNCTION timed_nudge_scan()
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    railway_url text := get_app_config('railway_nudge_url');
    jobs_secret text := get_app_config('jobs_secret');
    rec record;
BEGIN
    FOR rec IN
        UPDATE contacts
        SET next_nudge_at = NULL,
            time_specific = false
        WHERE status = 'active'
          AND time_specific = true
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

-- 6. Rewrite digest_scan() — weekly digest
CREATE OR REPLACE FUNCTION digest_scan()
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    railway_url text := get_app_config('railway_digest_url');
    jobs_secret text := get_app_config('jobs_secret');
    rec record;
BEGIN
    FOR rec IN
        SELECT DISTINCT u.id AS user_id
        FROM users u
        JOIN contacts c ON c.user_id = u.id
        WHERE c.status = 'active'
    LOOP
        PERFORM net.http_post(
            url := railway_url,
            headers := jsonb_build_object(
                'Content-Type', 'application/json',
                'X-Jobs-Secret', jobs_secret
            ),
            body := jsonb_build_object('user_id', rec.user_id)
        );
    END LOOP;
END;
$$;
