-- Migration Revision: 20260718_0035
-- Down Revision: 20260718_0034
-- Owner: alembic
-- Extracted SQL Blocks: 4

-- Statement 1
CREATE TABLE inventory_realtime_resource (
            resource_id TEXT PRIMARY KEY,
            change_kind TEXT NOT NULL CHECK (change_kind IN ('upsert', 'delete')),
            resource_type TEXT NOT NULL,
            props JSONB NOT NULL DEFAULT '{}'::jsonb,
            provider_ref TEXT,
            observed_at TIMESTAMPTZ NOT NULL,
            event_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

-- Statement 2
CREATE INDEX idx_inventory_realtime_resource_type ON inventory_realtime_resource(resource_type, observed_at DESC);

-- Statement 3
CREATE TABLE inventory_realtime_link (
            from_id TEXT NOT NULL,
            from_type TEXT NOT NULL,
            link_type TEXT NOT NULL CHECK (link_type IN
                ('contains', 'attached_to', 'depends_on')),
            to_id TEXT NOT NULL,
            to_type TEXT NOT NULL,
            change_kind TEXT NOT NULL CHECK (change_kind IN ('upsert', 'delete')),
            props JSONB NOT NULL DEFAULT '{}'::jsonb,
            observed_at TIMESTAMPTZ NOT NULL,
            event_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (from_id, link_type, to_id),
            UNIQUE (idempotency_key, from_id, link_type, to_id)
        );

-- Statement 4
CREATE INDEX idx_inventory_realtime_link_observed ON inventory_realtime_link(observed_at DESC);
