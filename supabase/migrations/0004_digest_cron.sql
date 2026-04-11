-- Alfred — Weekly Digest via pg_cron
-- Dispara toda segunda-feira às 11h UTC (8h BRT)

-- ─────────────────────────────────────────
-- DIGEST SCAN FUNCTION
-- Called by pg_cron weekly on Mondays
-- ─────────────────────────────────────────
create or replace function digest_scan()
returns void language plpgsql as $$
declare
    railway_url text := current_setting('app.railway_digest_url', true);
    jobs_secret text := current_setting('app.jobs_secret', true);
    rec record;
begin
    -- Fire digest for every user that has at least one active contact
    for rec in
        select distinct u.id as user_id
        from users u
        join contacts c on c.user_id = u.id
        where c.status = 'active'
    loop
        perform net.http_post(
            url := railway_url,
            headers := jsonb_build_object(
                'Content-Type', 'application/json',
                'X-Jobs-Secret', jobs_secret
            ),
            body := jsonb_build_object('user_id', rec.user_id)
        );
    end loop;
end;
$$;

-- ─────────────────────────────────────────
-- SCHEDULE: Monday and Thursday at 11:00 UTC (08:00 BRT)
-- ─────────────────────────────────────────
select cron.schedule(
    'alfred-digest-weekly',
    '0 11 * * 1,4',
    'select digest_scan()'
);

-- ─────────────────────────────────────────
-- RUNTIME CONFIG — set via Supabase dashboard:
-- Settings → Database → Configuration → Custom
-- app.railway_digest_url = 'https://alfred-production-e9cb.up.railway.app/jobs/digest'
-- (app.jobs_secret already set from migration 0003)
-- ─────────────────────────────────────────
