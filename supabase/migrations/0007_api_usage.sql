-- Track Anthropic API token usage for budget monitoring
create table api_usage (
    id                uuid primary key default gen_random_uuid(),
    user_id           uuid references users(id),
    model             text not null,
    input_tokens      int not null default 0,
    output_tokens     int not null default 0,
    cache_read_tokens int not null default 0,
    cache_write_tokens int not null default 0,
    cost_usd          numeric(10,6) not null default 0,
    created_at        timestamptz default now()
);

create index idx_api_usage_created on api_usage (created_at);

-- RLS: only service role can insert/read (server-side only)
alter table api_usage enable row level security;
