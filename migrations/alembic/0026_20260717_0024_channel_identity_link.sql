-- Migration Revision: 20260717_0024
-- Down Revision: 20260717_0023
-- Owner: alembic
-- Extracted SQL Blocks: 2

-- Statement 1
CREATE TABLE channel_identity_link (
            link_id TEXT PRIMARY KEY,
            principal_id TEXT NOT NULL,
            first_channel_kind TEXT NOT NULL CHECK (
                first_channel_kind IN ('teams', 'slack', 'web')
            ),
            first_channel_id TEXT NOT NULL,
            first_sender_id TEXT NOT NULL,
            second_channel_kind TEXT NOT NULL CHECK (
                second_channel_kind IN ('teams', 'slack', 'web')
            ),
            second_channel_id TEXT NOT NULL,
            second_sender_id TEXT NOT NULL,
            approved_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            CHECK (first_channel_kind <> second_channel_kind)
        );

-- Statement 2
CREATE INDEX idx_channel_identity_link_principal ON channel_identity_link(principal_id, created_at);
