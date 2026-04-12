-- Alfred MVP — Initial Schema
-- Run order: 0001 → 0002 → 0003

-- Extensions
create extension if not exists "pgcrypto";
create extension if not exists "vector";

-- ─────────────────────────────────────────
-- USERS
-- ─────────────────────────────────────────
create table if not exists users (
    id          uuid primary key default gen_random_uuid(),
    telegram_id bigint unique not null,
    name        text not null,
    timezone    text not null default 'America/Sao_Paulo',
    locale      text not null default 'pt-BR',
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

-- ─────────────────────────────────────────
-- CONTACTS
-- ─────────────────────────────────────────
create table if not exists contacts (
    id                  uuid primary key default gen_random_uuid(),
    user_id             uuid not null references users(id) on delete cascade,
    display_name        text not null,
    aliases             text[] not null default '{}',
    tags                text[] not null default '{}',
    how_we_met          text,
    relationship_type   text check (relationship_type in ('friend','professional','family','other')),
    company             text,
    role                text,
    cadence_days        int not null default 30,
    last_interaction_at timestamptz,
    next_nudge_at       timestamptz,
    status              text not null default 'active'
                          check (status in ('active','paused','archived')),
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

create index if not exists contacts_user_id_idx on contacts(user_id);
create index if not exists contacts_next_nudge_active_idx
    on contacts(next_nudge_at) where status = 'active';

-- ─────────────────────────────────────────
-- MEMORIES
-- ─────────────────────────────────────────
create table if not exists memories (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references users(id) on delete cascade,
    contact_id  uuid references contacts(id) on delete cascade,
    content     text not null,
    kind        text not null default 'other'
                  check (kind in ('personal','professional','milestone','preference','context','other')),
    source      text not null default 'user_message',
    captured_at timestamptz not null default now(),
    embedding   vector(1024)
);

create index if not exists memories_contact_id_idx on memories(contact_id);
create index if not exists memories_user_id_idx on memories(user_id);
create index if not exists memories_embedding_hnsw_idx
    on memories using hnsw (embedding vector_cosine_ops);

-- ─────────────────────────────────────────
-- INTERACTIONS
-- ─────────────────────────────────────────
create table if not exists interactions (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references users(id) on delete cascade,
    contact_id  uuid not null references contacts(id) on delete cascade,
    channel     text not null
                  check (channel in ('telegram','whatsapp','email','call','in_person','other')),
    direction   text not null check (direction in ('outbound','inbound','both')),
    summary     text not null,
    sentiment   text check (sentiment in ('positive','neutral','negative')),
    happened_at timestamptz not null,
    created_at  timestamptz not null default now()
);

create index if not exists interactions_contact_id_idx on interactions(contact_id);
create index if not exists interactions_happened_at_idx on interactions(happened_at desc);

-- ─────────────────────────────────────────
-- NUDGES
-- ─────────────────────────────────────────
create table if not exists nudges (
    id               uuid primary key default gen_random_uuid(),
    user_id          uuid not null references users(id) on delete cascade,
    contact_id       uuid not null references contacts(id) on delete cascade,
    reason           text not null,
    suggested_action text not null,
    draft_message    text not null,
    status           text not null default 'sent'
                       check (status in ('sent','viewed','acted','snoozed','muted')),
    created_at       timestamptz not null default now(),
    acted_at         timestamptz
);

-- ─────────────────────────────────────────
-- CONVERSATIONS + MESSAGES
-- ─────────────────────────────────────────
create table if not exists conversations (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null references users(id) on delete cascade,
    telegram_chat_id bigint not null,
    last_message_at timestamptz not null default now(),
    unique(user_id, telegram_chat_id)
);

create table if not exists messages (
    id              uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references conversations(id) on delete cascade,
    role            text not null check (role in ('user','assistant')),
    content         jsonb not null,
    created_at      timestamptz not null default now()
);

create index if not exists messages_conversation_created_idx
    on messages(conversation_id, created_at desc);

-- ─────────────────────────────────────────
-- HELPER: update updated_at automatically
-- ─────────────────────────────────────────
create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger users_updated_at before update on users
    for each row execute function set_updated_at();
create trigger contacts_updated_at before update on contacts
    for each row execute function set_updated_at();

-- ─────────────────────────────────────────
-- HELPER: recalculate next_nudge_at after interaction
-- ─────────────────────────────────────────
create or replace function update_contact_after_interaction(
    p_contact_id uuid,
    p_happened_at timestamptz
)
returns void language plpgsql as $$
declare
    v_cadence int;
begin
    select cadence_days into v_cadence
    from contacts where id = p_contact_id;

    update contacts
    set
        last_interaction_at = p_happened_at,
        -- Normaliza para meia-noite UTC para garantir que o scan de 11:00 UTC sempre pega
        next_nudge_at = date_trunc('day', p_happened_at + (v_cadence || ' days')::interval)
    where id = p_contact_id;
end;
$$;
