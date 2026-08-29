"""Create Operator-owned background-task projection tables."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_background_task_projection_transport_20260829"
down_revision: str | Sequence[str] | None = "operator_completion_retention_20260829"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables = (
    "operator_background_task_projection",
    "operator_background_task_progress",
)
rollback = {
    "strategy": "drop-operator-background-task-projection-and-restore-core-read-grants",
    "restores": "operator_completion_retention_20260829",
    "requires": "operator-background-task-projection-consumer-stopped",
}


def upgrade() -> None:
    """Materialize Operator-owned task reads and revoke Core table access."""

    op.execute(
        """
        CREATE TABLE operator_background_task_projection (
            task_id TEXT PRIMARY KEY
                CHECK (char_length(task_id) BETWEEN 1 AND 256),
            principal_id TEXT NOT NULL
                CHECK (char_length(principal_id) BETWEEN 1 AND 256),
            attempt_id TEXT NOT NULL
                CHECK (char_length(attempt_id) BETWEEN 1 AND 256),
            task_kind TEXT NOT NULL CHECK (task_kind = 'read_only_investigation'),
            status TEXT NOT NULL CHECK (
                status IN (
                    'queued', 'claimed', 'running', 'succeeded',
                    'failed', 'cancelled', 'timed_out', 'unknown'
                )
            ),
            revision INTEGER NOT NULL CHECK (revision >= 1),
            projection_sequence BIGINT NOT NULL CHECK (projection_sequence >= 1),
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            retention_until TIMESTAMPTZ NOT NULL,
            lease_expires_at TIMESTAMPTZ NULL,
            budget JSONB NOT NULL CHECK (jsonb_typeof(budget) = 'object'),
            usage JSONB NOT NULL CHECK (jsonb_typeof(usage) = 'object'),
            request_summary TEXT NULL CHECK (
                request_summary IS NULL OR char_length(request_summary) BETWEEN 1 AND 500
            ),
            request_truncated BOOLEAN NOT NULL,
            accountable_agent TEXT NULL CHECK (
                accountable_agent IS NULL OR accountable_agent = 'Heimdall'
            ),
            result_summary TEXT NULL CHECK (
                result_summary IS NULL OR char_length(result_summary) BETWEEN 1 AND 2000
            ),
            result_truncated BOOLEAN NOT NULL,
            evidence_refs JSONB NOT NULL CHECK (jsonb_typeof(evidence_refs) = 'array'),
            evidence_truncated BOOLEAN NOT NULL,
            terminal_reason TEXT NULL CHECK (
                terminal_reason IS NULL OR char_length(terminal_reason) BETWEEN 1 AND 256
            ),
            started_at TIMESTAMPTZ NULL,
            finished_at TIMESTAMPTZ NULL,
            completion_state TEXT NULL CHECK (
                completion_state IS NULL OR completion_state IN (
                    'pending', 'sending', 'failed', 'delivered', 'abandoned'
                )
            ),
            completion_attempt_count INTEGER NULL CHECK (
                completion_attempt_count IS NULL OR completion_attempt_count BETWEEN 0 AND 8
            ),
            progress_watermark BIGINT NULL CHECK (
                progress_watermark IS NULL OR progress_watermark >= 0
            ),
            recorded_at TIMESTAMPTZ NOT NULL,
            projection_id TEXT NOT NULL UNIQUE CHECK (
                projection_id ~ '^background-task-(snapshot|progress)-[a-f0-9]{32}$'
            ),
            projection_digest TEXT NOT NULL CHECK (
                projection_digest ~ '^sha256:[a-f0-9]{64}$'
            ),
            CHECK (created_at <= updated_at),
            CHECK (updated_at <= recorded_at),
            CHECK (recorded_at <= retention_until),
            CHECK (
                completion_state IS NOT NULL
                OR completion_attempt_count IS NULL
            )
        );
        CREATE INDEX operator_background_task_projection_owner_updated_idx
            ON operator_background_task_projection (
                principal_id, updated_at DESC, task_id DESC
            );
        CREATE INDEX operator_background_task_projection_retention_idx
            ON operator_background_task_projection (
                retention_until, task_id
            );

        CREATE TABLE operator_background_task_progress (
            task_id TEXT NOT NULL CHECK (char_length(task_id) BETWEEN 1 AND 256),
            progress_sequence INTEGER NOT NULL CHECK (progress_sequence BETWEEN 0 AND 255),
            progress_order BIGINT NOT NULL UNIQUE CHECK (progress_order >= 1),
            principal_id TEXT NOT NULL CHECK (char_length(principal_id) BETWEEN 1 AND 256),
            attempt_id TEXT NOT NULL CHECK (char_length(attempt_id) BETWEEN 1 AND 256),
            progress_id TEXT NOT NULL UNIQUE CHECK (
                progress_id ~ '^background-task-(snapshot|progress)-[a-f0-9]{32}$'
            ),
            progress_digest TEXT NOT NULL CHECK (
                progress_digest ~ '^sha256:[a-f0-9]{64}$'
            ),
            progress_kind TEXT NOT NULL CHECK (
                char_length(progress_kind) BETWEEN 1 AND 256
            ),
            progress_message TEXT NOT NULL CHECK (
                char_length(progress_message) BETWEEN 1 AND 1000
            ),
            progress_at TIMESTAMPTZ NOT NULL,
            usage JSONB NOT NULL CHECK (jsonb_typeof(usage) = 'object'),
            retention_until TIMESTAMPTZ NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (task_id, progress_sequence),
            CHECK (progress_at <= recorded_at),
            CHECK (recorded_at <= retention_until)
        );
        CREATE INDEX operator_background_task_progress_owner_sequence_idx
            ON operator_background_task_progress (
                principal_id, task_id, progress_sequence
            );
        CREATE INDEX operator_background_task_progress_owner_order_idx
            ON operator_background_task_progress (
                principal_id, task_id, progress_order DESC
            );
        CREATE INDEX operator_background_task_progress_retention_idx
            ON operator_background_task_progress (
                retention_until, task_id, progress_sequence
            );

        REVOKE ALL PRIVILEGES ON TABLE
            operator_background_task_projection,
            operator_background_task_progress
        FROM PUBLIC, fdai_operator;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
            operator_background_task_projection
        TO fdai_operator;
        GRANT SELECT, INSERT, DELETE ON TABLE
            operator_background_task_progress
        TO fdai_operator;

        REVOKE ALL PRIVILEGES ON TABLE
            background_task_attempt,
            background_task_progress,
            background_task_completion
        FROM fdai_operator;
        """
    )


def downgrade() -> None:
    """Drop Operator projection tables and restore the prior Core read grants."""

    op.execute(
        """
        GRANT SELECT ON TABLE
            background_task_attempt,
            background_task_progress,
            background_task_completion
        TO fdai_operator;
        REVOKE ALL PRIVILEGES ON TABLE
            operator_background_task_progress,
            operator_background_task_projection
        FROM fdai_operator;
        DROP TABLE operator_background_task_progress;
        DROP TABLE operator_background_task_projection;
        """
    )
