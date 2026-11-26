-- fdai PostgreSQL + pgvector baseline (mode=migration, legacy_alembic_count=92)
CREATE TABLE IF NOT EXISTS transactional_outbox (
    event_id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    payload_jcs BYTEA NOT NULL,
    published_at TIMESTAMPTZ
);
