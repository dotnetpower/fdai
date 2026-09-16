"""Create the append-only inventory progress ledger owned by Core collection."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_inventory_progress_20260916"
down_revision: str | Sequence[str] | None = "core_alert_forecast_merge_20260915"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("inventory_progress_event",)
rollback = {
    "strategy": "drop-inventory-progress-after-producer-and-operator-stop",
    "restores": "core_alert_forecast_merge_20260915",
    "requires": "inventory-progress-producer-and-operator-consumer-stopped",
}


def upgrade() -> None:
    """Create immutable, count-only records without provider or execution authority."""

    op.execute(
        """
        CREATE TABLE inventory_progress_event (
            event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            run_id TEXT NOT NULL CHECK (
                char_length(run_id) BETWEEN 1 AND 128
                AND run_id ~ '^[a-z][a-z0-9.-]*$'
            ),
            attempt_id TEXT NOT NULL CHECK (
                char_length(attempt_id) BETWEEN 1 AND 128
                AND attempt_id ~ '^[a-z][a-z0-9.-]*$'
            ),
            sequence BIGINT NOT NULL CHECK (sequence BETWEEN 1 AND 10000000000),
            previous_digest TEXT NOT NULL CHECK (
                previous_digest ~ '^sha256:[0-9a-f]{64}$'
            ),
            record_digest TEXT NOT NULL UNIQUE CHECK (
                record_digest ~ '^sha256:[0-9a-f]{64}$'
            ),
            stage TEXT NOT NULL CHECK (
                stage IN (
                    'count', 'collect', 'stage', 'enrich', 'validate',
                    'promote', 'verify', 'complete', 'failed'
                )
            ),
            state TEXT NOT NULL CHECK (state IN ('running', 'complete', 'failed')),
            payload JSONB NOT NULL CHECK (
                JSONB_TYPEOF(payload) = 'object'
                AND payload->>'execution_authority' = 'false'
                AND payload->>'record_digest' = record_digest
                AND payload->>'run_id' = run_id
                AND payload->>'attempt_id' = attempt_id
                AND (payload->>'sequence')::BIGINT = sequence
            ),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (run_id, attempt_id, sequence)
        );
        CREATE INDEX inventory_progress_event_run_order_idx
            ON inventory_progress_event (run_id, sequence, attempt_id);

        REVOKE ALL PRIVILEGES ON TABLE inventory_progress_event
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT ON TABLE inventory_progress_event TO fdai_core;
        """
    )


def downgrade() -> None:
    """Drop progress records only after both producer and consumer are stopped."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE inventory_progress_event
        FROM fdai_core;
        DROP TABLE inventory_progress_event;
        """
    )
