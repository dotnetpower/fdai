"""t1_pattern_library: pgvector-backed store for T1 similarity reuse

Revision ID: 20260706_0005
Revises: 20260705_0004
Create Date: 2026-07-06 00:00:00

Backs
:class:`~fdai.core.tiers.t1_lightweight.tier.PatternLibrary` with a
persistent Postgres+pgvector table so learned actions survive process
restarts. The in-memory fake in
:mod:`fdai.core.tiers.t1_lightweight.testing` mirrors the schema for
unit tests; this migration only creates the physical backing.

Columns
-------
- ``id`` - UUID primary key (server-assigned).
- ``signature`` - stable hash of ``(rule_id, action_type, params keys)``;
  UNIQUE so ``INSERT ... ON CONFLICT`` deduplicates re-seeds and lets a
  future promotion pipeline update the row in place.
- ``rule_id`` - the deterministic rule that resolved the origin incident.
- ``action_type`` - the ontology ActionType name the reuse targets.
- ``params`` - the parameter payload the ActionType renderer needs
  (JSONB so it round-trips without a serializer).
- ``embedding`` - ``vector(384)`` - matches the local
  ``sentence-transformers/all-MiniLM-L6-v2`` embedding dimension used
  by the Phase-2 EmbeddingModel adapter. Distinct from the 1536-d
  ``ontology_embedding`` table (OpenAI ``text-embedding-3-small``); the
  T1 library never mixes them.
- ``source_incident_id`` - audit trail of the origin resolution.
- ``historical_success_rate`` - float in ``[0, 1]``; the T1 tier's
  ``min_success_rate`` floor consults this before allowing reuse.
- ``reuse_count`` - how many times the pattern has been re-applied
  (informational; the risk-gate does not read it).
- ``created_at`` - server timestamp for audit / cache eviction.

Indexes
-------
- ``IVFFlat(embedding vector_cosine_ops, lists=100)`` for approximate
  nearest-neighbour search. IVFFlat trades a build-time list count for
  query latency; ``lists=100`` matches the pgvector recommendation for
  ``rows/1000`` when the library is still small (P2 seeds ~10³
  patterns). Query-time ``ivfflat.probes`` is set by the adapter.
- ``idx_t1_pattern_library_rule_id`` - the discovery loop scans
  per-rule to compute promotion / retirement candidates.

The ``vector`` extension is created here idempotently for callers that
run this migration in isolation; in practice the base migration chain
already installed it via ``20260705_0002_layered_cache``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260706_0005"
down_revision: str | None = "20260705_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector extension - idempotent. Also seeded by the base chain and by
    # infra/local/init-pgvector.sql; re-declared here so this migration is
    # safe to apply against a database with only the state_kv layer.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    op.execute("""
        CREATE TABLE IF NOT EXISTS t1_pattern_library (
            id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            signature                TEXT NOT NULL UNIQUE,
            rule_id                  TEXT NOT NULL,
            action_type              TEXT NOT NULL,
            params                   JSONB NOT NULL DEFAULT '{}'::jsonb,
            embedding                vector(384) NOT NULL,
            source_incident_id       TEXT NOT NULL,
            historical_success_rate  DOUBLE PRECISION NOT NULL DEFAULT 0.0
                CHECK (historical_success_rate >= 0.0
                       AND historical_success_rate <= 1.0),
            reuse_count              INTEGER NOT NULL DEFAULT 0
                CHECK (reuse_count >= 0),
            created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("CREATE INDEX idx_t1_pattern_library_rule_id ON t1_pattern_library(rule_id);")

    # IVFFlat cosine index. Creating on an empty table only emits a NOTICE
    # ("ivfflat index created on empty table"); it does not fail. The
    # list count is a build-time decision; re-tune with REINDEX once the
    # library exceeds ~10^5 rows.
    op.execute("""
        CREATE INDEX idx_t1_pattern_library_embedding_ivfflat
        ON t1_pattern_library
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100);
    """)


def downgrade() -> None:
    # Deliberately do NOT drop the ``vector`` extension - it is shared with
    # ontology_embedding + t2_cache. The base chain owns its lifecycle.
    op.execute("DROP TABLE IF EXISTS t1_pattern_library CASCADE;")
