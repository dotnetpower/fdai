"""layered cache: learned_action + pgvector embeddings + t2_cache partitions

Revision ID: 20260705_0002
Revises: 20260705_0001
Create Date: 2026-07-05 00:00:01

Depends on ``20260705_0001_base`` (needs ``ontology_resource``).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260705_0002"
down_revision: str | None = "20260705_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector extension - idempotent; also seeded by infra/local/init-pgvector.sql.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    op.execute("""
        CREATE TABLE IF NOT EXISTS learned_action (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            rule_id          TEXT NOT NULL,
            action_signature TEXT NOT NULL UNIQUE,
            action_payload   JSONB NOT NULL,
            success_count    INTEGER NOT NULL DEFAULT 0,
            rollback_count   INTEGER NOT NULL DEFAULT 0,
            last_used_at     TIMESTAMPTZ,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX idx_learned_action_rule_id ON learned_action(rule_id);")

    op.execute("""
        CREATE TABLE IF NOT EXISTS ontology_embedding (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            resource_ref TEXT NOT NULL REFERENCES ontology_resource(id) ON DELETE CASCADE,
            model        TEXT NOT NULL,
            embedding    vector(1536) NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute(
        "CREATE INDEX idx_ontology_embedding_resource_ref ON ontology_embedding(resource_ref);"
    )
    # HNSW index for cosine similarity (pgvector ≥ 0.5).
    op.execute("""
        CREATE INDEX idx_ontology_embedding_hnsw
        ON ontology_embedding USING hnsw (embedding vector_cosine_ops);
    """)

    # Partitioned by catalog_version so rotating catalogs stays cheap.
    op.execute("""
        CREATE TABLE IF NOT EXISTS t2_cache (
            id              UUID NOT NULL DEFAULT gen_random_uuid(),
            catalog_version TEXT NOT NULL,
            input_hash      TEXT NOT NULL,
            output          JSONB NOT NULL,
            model           TEXT NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (catalog_version, id)
        ) PARTITION BY LIST (catalog_version);
    """)
    op.execute("CREATE TABLE IF NOT EXISTS t2_cache_default PARTITION OF t2_cache DEFAULT;")
    op.execute("CREATE INDEX idx_t2_cache_input_hash ON t2_cache (catalog_version, input_hash);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS t2_cache_default;")
    op.execute("DROP TABLE IF EXISTS t2_cache CASCADE;")
    op.execute("DROP TABLE IF EXISTS ontology_embedding CASCADE;")
    op.execute("DROP TABLE IF EXISTS learned_action CASCADE;")
    # Deliberately do NOT drop the pgvector extension - it is shared and
    # also seeded by infra/local/init-pgvector.sql for local dev.
