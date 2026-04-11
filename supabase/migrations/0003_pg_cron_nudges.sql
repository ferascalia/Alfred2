-- Alfred MVP — pg_cron + pg_net nudge scheduler
-- Requires: pg_cron and pg_net extensions enabled in Supabase dashboard.

create extension if not exists "pg_cron";
create extension if not exists "pg_net";

-- ─────────────────────────────────────────
-- SEMANTIC SEARCH FUNCTIONS (pgvector)
-- ─────────────────────────────────────────

-- Search memories for a user (all contacts)
create or replace function match_memories(
    query_embedding vector(1024),
    user_id_filter uuid,
    match_count int default 5
)
returns table (
    id uuid,
    contact_id uuid,
    content text,
    kind text,
    similarity float
)
language sql stable as $$
    select
        m.id,
        m.contact_id,
        m.content,
        m.kind,
        1 - (m.embedding <=> query_embedding) as similarity
    from memories m
    where m.user_id = user_id_filter
      and m.embedding is not null
    order by m.embedding <=> query_embedding
    limit match_count;
$$;

-- Search memories for a specific contact
create or replace function match_memories_by_contact(
    query_embedding vector(1024),
    user_id_filter uuid,
    contact_id_filter uuid,
    match_count int default 5
)
returns table (
    id uuid,
    contact_id uuid,
    content text,
    kind text,
    similarity float
)
language sql stable as $$
    select
        m.id,
        m.contact_id,
        m.content,
        m.kind,
        1 - (m.embedding <=> query_embedding) as similarity
    from memories m
    where m.user_id = user_id_filter
      and m.contact_id = contact_id_filter
      and m.embedding is not null
    order by m.embedding <=> query_embedding
    limit match_count;
$$;

-- ─────────────────────────────────────────
-- NUDGE SCAN FUNCTION
-- Called by pg_cron daily at 08:00
-- ─────────────────────────────────────────
create or replace function nudge_scan()
returns void language plpgsql as $$
declare
    railway_url text := current_setting('app.railway_nudge_url', true);
    jobs_secret text := current_setting('app.jobs_secret', true);
    rec record;
begin
    -- Find all active contacts past their nudge date
    for rec in
        select c.id as contact_id
        from contacts c
        where c.status = 'active'
          and c.next_nudge_at is not null
          and c.next_nudge_at <= now()
    loop
        -- Call Railway /jobs/nudge endpoint via pg_net
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
-- SCHEDULE: daily at 08:00 UTC
-- (Adjust timezone offset for your users)
-- ─────────────────────────────────────────
select cron.schedule(
    'alfred-nudge-scan',
    '0 8 * * *',
    'select nudge_scan()'
);

-- ─────────────────────────────────────────
-- RUNTIME CONFIG (set via Supabase dashboard → Settings → Database → Configuration)
-- app.railway_nudge_url = 'https://your-app.up.railway.app/jobs/nudge'
-- app.jobs_secret = 'your_jobs_secret'
-- ─────────────────────────────────────────
