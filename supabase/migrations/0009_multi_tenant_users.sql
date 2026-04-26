-- Multi-tenant: user tiers, limits, and invite codes

-- Tier and status columns on users
ALTER TABLE users ADD COLUMN IF NOT EXISTS tier TEXT NOT NULL DEFAULT 'free'
    CHECK (tier IN ('free', 'personal', 'professional', 'business'));
ALTER TABLE users ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'suspended', 'churned'));
ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_token_budget_usd NUMERIC(10,4) NOT NULL DEFAULT 0.50;
ALTER TABLE users ADD COLUMN IF NOT EXISTS max_contacts INT NOT NULL DEFAULT 25;
ALTER TABLE users ADD COLUMN IF NOT EXISTS max_messages_per_day INT NOT NULL DEFAULT 15;
ALTER TABLE users ADD COLUMN IF NOT EXISTS invited_by UUID REFERENCES users(id);

-- Invite codes table
CREATE TABLE IF NOT EXISTS invite_codes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code TEXT UNIQUE NOT NULL,
    tier TEXT NOT NULL DEFAULT 'free'
        CHECK (tier IN ('free', 'personal', 'professional', 'business')),
    created_by UUID REFERENCES users(id),
    used_by UUID REFERENCES users(id),
    used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS invite_codes_code_idx ON invite_codes(code);
ALTER TABLE invite_codes ENABLE ROW LEVEL SECURITY;

-- Index for fast per-user monthly usage queries
CREATE INDEX IF NOT EXISTS idx_api_usage_user_month
    ON api_usage (user_id, created_at)
    WHERE user_id IS NOT NULL;

-- Per-user monthly spend function (callable via supabase rpc)
CREATE OR REPLACE FUNCTION get_user_monthly_spend(p_user_id UUID)
RETURNS NUMERIC LANGUAGE sql STABLE AS $$
    SELECT COALESCE(SUM(cost_usd), 0)
    FROM api_usage
    WHERE user_id = p_user_id
      AND created_at >= date_trunc('month', now());
$$;

-- Per-user daily message count function
CREATE OR REPLACE FUNCTION get_user_daily_messages(p_user_id UUID)
RETURNS BIGINT LANGUAGE sql STABLE AS $$
    SELECT COUNT(*)
    FROM api_usage
    WHERE user_id = p_user_id
      AND created_at >= date_trunc('day', now());
$$;

-- Set existing users to beta (professional tier, free)
UPDATE users SET tier = 'professional', status = 'active'
    WHERE tier = 'free';
