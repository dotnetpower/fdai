"""Grant Operator read-only access to remaining Console evidence ledgers."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_console_evidence_reads_20260827"
down_revision: str | Sequence[str] | None = "operator_assurance_read_20260827"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-operator-console-evidence-reads",
    "restores": "operator_assurance_read_20260827",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    """Grant only SELECT on forecast, memory, and skill evidence."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            forecast_episode,
            forecast_publication_outbox,
            operator_memory,
            memory_compaction_candidate,
            skill_source,
            skill_source_refresh_state
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            forecast_episode,
            forecast_publication_outbox,
            operator_memory,
            memory_compaction_candidate,
            skill_source,
            skill_source_refresh_state
        TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove only the remaining Console evidence reads."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            forecast_episode,
            forecast_publication_outbox,
            operator_memory,
            memory_compaction_candidate,
            skill_source,
            skill_source_refresh_state
        FROM fdai_operator
        """
    )
