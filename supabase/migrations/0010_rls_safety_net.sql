-- RLS Safety Net: replace auth.uid() policies with session variable policies.
-- These policies serve as defense-in-depth documentation.
-- With service_role key, RLS is still bypassed.
-- They become enforced when switching to anon/authenticated keys (Phase 3.5).

-- Helper function: set current user context for the transaction
CREATE OR REPLACE FUNCTION set_request_user(p_user_id UUID)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
    PERFORM set_config('app.current_user_id', p_user_id::text, true);
END;
$$;

-- Drop old auth.uid() policies (they never worked with service_role)
DROP POLICY IF EXISTS "users_self" ON users;
DROP POLICY IF EXISTS "contacts_owner" ON contacts;
DROP POLICY IF EXISTS "memories_owner" ON memories;
DROP POLICY IF EXISTS "interactions_owner" ON interactions;
DROP POLICY IF EXISTS "nudges_owner" ON nudges;
DROP POLICY IF EXISTS "conversations_owner" ON conversations;
DROP POLICY IF EXISTS "messages_owner" ON messages;
DROP POLICY IF EXISTS "contact_relationships_user_policy" ON contact_relationships;

-- Recreate with session variable (current_setting returns NULL if not set)
CREATE POLICY "users_self_v2" ON users
    FOR ALL USING (id::text = current_setting('app.current_user_id', true))
    WITH CHECK (id::text = current_setting('app.current_user_id', true));

CREATE POLICY "contacts_owner_v2" ON contacts
    FOR ALL USING (user_id::text = current_setting('app.current_user_id', true))
    WITH CHECK (user_id::text = current_setting('app.current_user_id', true));

CREATE POLICY "memories_owner_v2" ON memories
    FOR ALL USING (user_id::text = current_setting('app.current_user_id', true))
    WITH CHECK (user_id::text = current_setting('app.current_user_id', true));

CREATE POLICY "interactions_owner_v2" ON interactions
    FOR ALL USING (user_id::text = current_setting('app.current_user_id', true))
    WITH CHECK (user_id::text = current_setting('app.current_user_id', true));

CREATE POLICY "nudges_owner_v2" ON nudges
    FOR ALL USING (user_id::text = current_setting('app.current_user_id', true))
    WITH CHECK (user_id::text = current_setting('app.current_user_id', true));

CREATE POLICY "conversations_owner_v2" ON conversations
    FOR ALL USING (user_id::text = current_setting('app.current_user_id', true))
    WITH CHECK (user_id::text = current_setting('app.current_user_id', true));

CREATE POLICY "messages_owner_v2" ON messages
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM conversations c
            WHERE c.id = messages.conversation_id
            AND c.user_id::text = current_setting('app.current_user_id', true)
        )
    );

CREATE POLICY "contact_relationships_owner_v2" ON contact_relationships
    FOR ALL USING (user_id::text = current_setting('app.current_user_id', true))
    WITH CHECK (user_id::text = current_setting('app.current_user_id', true));

-- invite_codes: admin-only, no user-facing policy needed
-- api_usage: admin-only, no user-facing policy needed
