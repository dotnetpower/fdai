"""Add Operator-owned read-investigation completion delivery."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_read_investigation_completion_20260826"
down_revision: str | Sequence[str] | None = "operator_index_maintenance_20260825"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables = (
    "operator_read_investigation_completion",
    "conversation_record",
    "conversation_turn",
)
rollback = {
    "strategy": "stop-completion-consumer-and-drop-inbox",
    "restores": "operator_index_maintenance_20260825",
    "requires": "core-completion-publisher-stopped",
}


def upgrade() -> None:
    """Create the durable inbox and grant only Operator-owned delivery writes."""
    op.execute(
        """
        CREATE TABLE operator_read_investigation_completion (
            sequence BIGSERIAL PRIMARY KEY,
            completion_id TEXT NOT NULL UNIQUE,
            task_id TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            stream TEXT NOT NULL,
            event TEXT NOT NULL CHECK (event = 'investigation.completed'),
            completion_digest TEXT NOT NULL CHECK (
                completion_digest ~ '^sha256:[a-f0-9]{64}$'
            ),
            data JSONB NOT NULL CHECK (jsonb_typeof(data) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL,
            retention_until TIMESTAMPTZ NOT NULL,
            CHECK (recorded_at <= retention_until)
        );
        CREATE INDEX operator_read_investigation_completion_replay_idx
            ON operator_read_investigation_completion (
                principal_id, stream, sequence
            );
        CREATE INDEX operator_read_investigation_completion_retention_idx
            ON operator_read_investigation_completion (
                retention_until, sequence
            );

        REVOKE ALL PRIVILEGES ON TABLE
            operator_read_investigation_completion
        FROM PUBLIC, fdai_operator;
        REVOKE ALL PRIVILEGES ON SEQUENCE
            operator_read_investigation_completion_sequence_seq
        FROM PUBLIC, fdai_operator;

        GRANT SELECT, INSERT ON TABLE
            operator_read_investigation_completion
        TO fdai_operator;
        GRANT USAGE, SELECT ON SEQUENCE
            operator_read_investigation_completion_sequence_seq
        TO fdai_operator;
        GRANT SELECT, INSERT, UPDATE ON TABLE conversation_record TO fdai_operator;
        GRANT SELECT, INSERT ON TABLE conversation_turn TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Stop delivery writes while preserving the previous read-only grants."""
    op.execute(
        """
        REVOKE INSERT, UPDATE ON TABLE conversation_record FROM fdai_operator;
        REVOKE INSERT ON TABLE conversation_turn FROM fdai_operator;
        REVOKE ALL PRIVILEGES ON SEQUENCE
            operator_read_investigation_completion_sequence_seq
        FROM fdai_operator;
        REVOKE ALL PRIVILEGES ON TABLE
            operator_read_investigation_completion
        FROM fdai_operator;
        DROP TABLE operator_read_investigation_completion;
        """
    )
