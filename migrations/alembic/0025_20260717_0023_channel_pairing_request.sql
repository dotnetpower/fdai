-- Migration Revision: 20260717_0023
-- Down Revision: 143566f8b16b
-- Owner: alembic
-- Extracted SQL Blocks: 2

-- Statement 1
CREATE TABLE channel_pairing_request (
            channel_kind TEXT NOT NULL CHECK (channel_kind IN ('teams', 'slack', 'web')),
            channel_id TEXT NOT NULL,
            sender_id TEXT NOT NULL,
            code_digest TEXT NOT NULL CHECK (length(code_digest) = 64),
            created_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL CHECK (expires_at > created_at),
            approved_principal_id TEXT,
            approved_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (channel_kind, channel_id, sender_id),
            CHECK ((approved_principal_id IS NULL) = (approved_at IS NULL))
        );

-- Statement 2
CREATE INDEX idx_channel_pairing_pending ON channel_pairing_request(channel_kind, expires_at) WHERE approved_principal_id IS NULL;
