"""access-scoped conversation search projection

Revision ID: 20260720_0038
Revises: 20260720_0037
Create Date: 2026-07-20 08:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260720_0038"
down_revision: str | None = "20260720_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE EXTENSION IF NOT EXISTS pg_trgm;

        ALTER TABLE conversation_turn
            ADD COLUMN search_text TEXT
            GENERATED ALWAYS AS (lower(content)) STORED;

        CREATE INDEX ix_conversation_turn_search_scope
            ON conversation_turn (principal_id, recorded_at DESC, conversation_id);
        CREATE INDEX ix_conversation_turn_search_trgm
            ON conversation_turn USING GIN (search_text gin_trgm_ops);
        CREATE INDEX ix_conversation_turn_search_incident
            ON conversation_turn (principal_id, (metadata ->> 'incident_id'))
            WHERE metadata ? 'incident_id';
        CREATE INDEX ix_conversation_turn_search_correlation
            ON conversation_turn (principal_id, (metadata ->> 'correlation_id'))
            WHERE metadata ? 'correlation_id';
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_conversation_turn_search_correlation;")
    op.execute("DROP INDEX IF EXISTS ix_conversation_turn_search_incident;")
    op.execute("DROP INDEX IF EXISTS ix_conversation_turn_search_trgm;")
    op.execute("DROP INDEX IF EXISTS ix_conversation_turn_search_scope;")
    op.execute("ALTER TABLE conversation_turn DROP COLUMN IF EXISTS search_text;")
