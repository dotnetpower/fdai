"""action_outbox: transactional-outbox exactly-once guard

Revision ID: 20260708_0008
Revises: 20260708_0007
Create Date: 2026-07-08

Backs :class:`~fdai.shared.providers.outbox.OutboxStore` with a
persistent Postgres table so a claim-first-then-mutate flow closes the
"mutation applied but result not recorded" window that a plain
idempotency store leaves open on a crash between the two writes.

Two writers can safely race on ``claim(key)``:

- ``INSERT ... ON CONFLICT DO NOTHING`` picks a single winner as ``NEW``.
- The loser reads the existing row and returns ``IN_PROGRESS`` (retry
  the idempotent mutation) or ``DONE`` (skip mutation, reuse result).

The runtime adapter :class:`~fdai.delivery.persistence.postgres_outbox.PostgresOutboxStore`
still issues ``CREATE TABLE IF NOT EXISTS`` at first use so ad-hoc / dev
deploys work without Alembic; when Alembic runs first this migration is
authoritative and the runtime CREATE is a no-op.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260708_0008"
down_revision = "20260708_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS action_outbox (
            idempotency_key TEXT PRIMARY KEY
                CHECK (btrim(idempotency_key) <> ''),
            status          TEXT NOT NULL
                CHECK (status IN ('in_progress', 'done')),
            result          JSONB NULL,
            claimed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at    TIMESTAMPTZ NULL,
            CONSTRAINT action_outbox_done_has_result
                CHECK (status <> 'done' OR result IS NOT NULL),
            CONSTRAINT action_outbox_done_has_completed_at
                CHECK (status <> 'done' OR completed_at IS NOT NULL)
        );
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_action_outbox_claimed_at
        ON action_outbox (claimed_at DESC);
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_action_outbox_status
        ON action_outbox (status);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS action_outbox CASCADE;")
