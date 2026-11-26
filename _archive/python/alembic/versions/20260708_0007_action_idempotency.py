"""action_idempotency: durable L2 exactly-once guard for the executor

Revision ID: 20260708_0007
Revises: 20260706_0006
Create Date: 2026-07-08

Backs :class:`~fdai.shared.providers.idempotency.IdempotencyStore` with
a persistent Postgres table so a post-restart or cross-replica retry of
a mutating :class:`~fdai.shared.contracts.models.Action` is answered
from the store instead of re-executing. The in-memory adapter in
:mod:`fdai.shared.providers.testing.idempotency` mirrors this shape;
this migration only creates the physical backing.

Design notes
------------
- ``idempotency_key`` is the PRIMARY KEY. ``INSERT ... ON CONFLICT DO
  NOTHING`` from :class:`PostgresIdempotencyStore.record` is race-safe
  against two replicas trying to record the same key.
- ``result`` is JSONB so a downstream tool (audit reader, KPI dashboard)
  can query into it without deserializing every row.
- ``recorded_at`` supports simple retention pruning by any operator
  runbook, though the executor never depends on retention -- an evicted
  row simply means the next retry re-executes (still idempotent thanks
  to the audit log's UNIQUE ``entry_hash`` guard).

The runtime adapter
:class:`~fdai.delivery.persistence.postgres_idempotency.PostgresIdempotencyStore`
still issues ``CREATE TABLE IF NOT EXISTS`` at first use so ad-hoc / dev
deploys work without running Alembic; when Alembic is run first this
migration is authoritative and the runtime CREATE is a no-op.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260708_0007"
down_revision = "20260706_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS action_idempotency (
            idempotency_key TEXT PRIMARY KEY
                CHECK (btrim(idempotency_key) <> ''),
            result          JSONB NOT NULL,
            recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_action_idempotency_recorded_at
        ON action_idempotency (recorded_at DESC);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS action_idempotency CASCADE;")
