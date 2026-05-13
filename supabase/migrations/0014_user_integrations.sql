-- User integrations: OAuth tokens for external services (Google, etc.)
CREATE TABLE user_integrations (
    id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider    TEXT NOT NULL,
    access_token  TEXT NOT NULL,
    refresh_token TEXT,
    token_expires_at TIMESTAMPTZ,
    scopes      TEXT[] DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'expired', 'revoked')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, provider)
);

CREATE INDEX idx_user_integrations_user ON user_integrations(user_id);

-- RLS
ALTER TABLE user_integrations ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_integrations_select ON user_integrations
    FOR SELECT USING (user_id = current_setting('app.current_user_id', true)::uuid);

CREATE POLICY user_integrations_insert ON user_integrations
    FOR INSERT WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);

CREATE POLICY user_integrations_update ON user_integrations
    FOR UPDATE USING (user_id = current_setting('app.current_user_id', true)::uuid);

CREATE POLICY user_integrations_delete ON user_integrations
    FOR DELETE USING (user_id = current_setting('app.current_user_id', true)::uuid);

-- Service-role bypass (Alfred backend uses service role key, so RLS is bypassed automatically)
-- Policies above are for future direct-access scenarios (e.g., Supabase Auth in Fase 3)
