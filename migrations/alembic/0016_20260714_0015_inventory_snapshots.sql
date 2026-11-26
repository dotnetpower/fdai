-- Migration Revision: 20260714_0015
-- Down Revision: 20260713_0014
-- Owner: alembic
-- Extracted SQL Blocks: 5

-- Statement 1
CREATE TABLE inventory_snapshot (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK (status IN
                ('collecting', 'active', 'failed', 'superseded')),
            source TEXT NOT NULL,
            observation_kind TEXT NOT NULL CHECK (observation_kind IN ('observed', 'expected')),
            scopes JSONB NOT NULL,
            resource_types JSONB NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            started_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ,
            promoted_at TIMESTAMPTZ,
            failure_code TEXT,
            failure_message TEXT
        );

-- Statement 2
CREATE TABLE inventory_snapshot_resource (
            snapshot_id TEXT NOT NULL REFERENCES inventory_snapshot(id) ON DELETE CASCADE,
            resource_id TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            props JSONB NOT NULL DEFAULT '{}'::jsonb,
            provider_ref TEXT,
            last_seen TIMESTAMPTZ,
            PRIMARY KEY (snapshot_id, resource_id)
        );

-- Statement 3
CREATE INDEX idx_inventory_snapshot_resource_type ON inventory_snapshot_resource(snapshot_id, resource_type);

-- Statement 4
CREATE TABLE inventory_snapshot_link (
            snapshot_id TEXT NOT NULL REFERENCES inventory_snapshot(id) ON DELETE CASCADE,
            from_id TEXT NOT NULL,
            from_type TEXT NOT NULL,
            link_type TEXT NOT NULL CHECK (link_type IN ('contains', 'attached_to', 'depends_on')),
            to_id TEXT NOT NULL,
            to_type TEXT NOT NULL,
            props JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (snapshot_id, from_id, link_type, to_id)
        );

-- Statement 5
CREATE TABLE inventory_active (
            singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
            snapshot_id TEXT NOT NULL REFERENCES inventory_snapshot(id),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
