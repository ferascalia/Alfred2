-- Alfred MVP — Row Level Security
-- Enables RLS on all tables with user_id scoping.
-- Even with a single user, this prepares us for multi-tenant Phase 3.

-- Enable RLS
alter table users enable row level security;
alter table contacts enable row level security;
alter table memories enable row level security;
alter table interactions enable row level security;
alter table nudges enable row level security;
alter table conversations enable row level security;
alter table messages enable row level security;

-- ─────────────────────────────────────────
-- POLICIES — service_role bypasses RLS by default in Supabase.
-- These policies apply to anon / authenticated roles.
-- ─────────────────────────────────────────

-- Users: can only see their own row
create policy "users_self" on users
    for all using (id = auth.uid())
    with check (id = auth.uid());

-- Contacts: scoped to user_id
create policy "contacts_owner" on contacts
    for all using (user_id = auth.uid())
    with check (user_id = auth.uid());

-- Memories: scoped to user_id
create policy "memories_owner" on memories
    for all using (user_id = auth.uid())
    with check (user_id = auth.uid());

-- Interactions: scoped to user_id
create policy "interactions_owner" on interactions
    for all using (user_id = auth.uid())
    with check (user_id = auth.uid());

-- Nudges: scoped to user_id
create policy "nudges_owner" on nudges
    for all using (user_id = auth.uid())
    with check (user_id = auth.uid());

-- Conversations: scoped to user_id
create policy "conversations_owner" on conversations
    for all using (user_id = auth.uid())
    with check (user_id = auth.uid());

-- Messages: scoped via conversation ownership
create policy "messages_owner" on messages
    for all using (
        exists (
            select 1 from conversations c
            where c.id = messages.conversation_id
            and c.user_id = auth.uid()
        )
    );
