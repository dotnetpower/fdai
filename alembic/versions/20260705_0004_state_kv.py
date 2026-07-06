"""state_kv: tracked key/value store for the StateStore protocol

Adds the missing table behind :meth:`StateStore.read_state` /
:meth:`StateStore.write_state`. The audit log lives in ``audit_log``
(base migration); this migration only introduces the ``state_kv``
key-value backing store so a running control plane can persist
tracked state (feature-flag values, promotion registry snapshots,
scheduler last-tick markers) across restarts.

Idempotency-by-key is enforced at the SQL layer via ``PRIMARY KEY (key)``
and ``INSERT ... ON CONFLICT DO UPDATE`` from the adapter side.

Revision ID: 20260705_0004
Revises: 20260705_0003
Create Date: 2026-07-06 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260705_0004"
down_revision: str | None = "20260705_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS state_kv (
            key         TEXT PRIMARY KEY,
            value       JSONB NOT NULL,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS state_kv CASCADE;")
