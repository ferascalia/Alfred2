-- Contact relationships: generic, bidirectional links between contacts
-- Labels are free-text (not enum) — the agent writes what makes sense in context.
-- Service layer creates A→B and B→A automatically.

CREATE TABLE IF NOT EXISTS contact_relationships (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    from_contact_id UUID NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    to_contact_id   UUID NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    label           TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, from_contact_id, to_contact_id)
);

CREATE INDEX IF NOT EXISTS cr_user_idx ON contact_relationships(user_id);
CREATE INDEX IF NOT EXISTS cr_from_idx ON contact_relationships(from_contact_id);
CREATE INDEX IF NOT EXISTS cr_to_idx ON contact_relationships(to_contact_id);

ALTER TABLE contact_relationships ENABLE ROW LEVEL SECURITY;

CREATE POLICY contact_relationships_user_policy ON contact_relationships
    FOR ALL USING (user_id = auth.uid());
