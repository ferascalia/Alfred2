-- Alfred — Timed follow-ups (per-minute scan)
-- Allows users to set follow-ups with a specific time (e.g., "remind me at 5PM").
-- Adds a second pg_cron job that runs every minute for timed reminders.
-- The existing daily 08:00 UTC nudge_scan is untouched for cadence nudges.

-- ─────────────────────────────────────────
-- 1. New column: time_specific
-- ─────────────────────────────────────────
alter table contacts add column if not exists time_specific boolean default false;

-- ─────────────────────────────────────────
-- 2. Update nudge_scan() to skip timed reminders
-- ─────────────────────────────────────────
create or replace function nudge_scan()
returns void language plpgsql as $$
declare
    railway_url text := current_setting('app.railway_nudge_url', true);
    jobs_secret text := current_setting('app.jobs_secret', true);
    rec record;
begin
    for rec in
        select c.id as contact_id
        from contacts c
        where c.status = 'active'
          and c.next_nudge_at is not null
          and c.next_nudge_at <= now()
          and (c.time_specific is not true)
    loop
        perform net.http_post(
            url := railway_url,
            headers := jsonb_build_object(
                'Content-Type', 'application/json',
                'X-Jobs-Secret', jobs_secret
            ),
            body := jsonb_build_object('contact_id', rec.contact_id)
        );
    end loop;
end;
$$;

-- ─────────────────────────────────────────
-- 3. New function: timed_nudge_scan()
--    Atomic UPDATE…RETURNING prevents duplicate firing.
-- ─────────────────────────────────────────
create or replace function timed_nudge_scan()
returns void language plpgsql as $$
declare
    railway_url text := current_setting('app.railway_nudge_url', true);
    jobs_secret text := current_setting('app.jobs_secret', true);
    rec record;
begin
    for rec in
        update contacts
        set next_nudge_at = null,
            time_specific = false
        where status = 'active'
          and time_specific = true
          and next_nudge_at is not null
          and next_nudge_at <= now()
        returning id as contact_id
    loop
        perform net.http_post(
            url := railway_url,
            headers := jsonb_build_object(
                'Content-Type', 'application/json',
                'X-Jobs-Secret', jobs_secret
            ),
            body := jsonb_build_object('contact_id', rec.contact_id)
        );
    end loop;
end;
$$;

-- ─────────────────────────────────────────
-- 4. Schedule: every minute
-- ─────────────────────────────────────────
select cron.schedule(
    'alfred-timed-nudge-scan',
    '* * * * *',
    'select timed_nudge_scan()'
);
