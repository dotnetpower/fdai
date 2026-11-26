"""Retain immutable, content-free dialogue-state snapshots for compacted conversation turns."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_dialogue_state_snapshot_20261028"
down_revision: str | Sequence[str] | None = "operator_automation_blueprint_intent_20261019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ("conversation_dialogue_snapshot",)
rollback = {
    "strategy": "drop-derived-dialogue-state-snapshots-after-readers-stop",
    "restores": "operator_automation_blueprint_intent_20261019",
    "requires": "operator-dialogue-state-writers-stopped-and-conversation-turns-retained",
}


def upgrade() -> None:
    """Create the insert-only derived table; conversation_turn stays the source of record."""
    op.execute(
        """
        CREATE TABLE conversation_dialogue_snapshot (
            principal_id TEXT NOT NULL CHECK (char_length(principal_id) BETWEEN 1 AND 256),
            conversation_id TEXT NOT NULL CHECK (char_length(conversation_id) BETWEEN 1 AND 256),
            snapshot_id TEXT NOT NULL CHECK (snapshot_id ~ '^sha256:[0-9a-f]{64}$'),
            tier TEXT NOT NULL CHECK (tier IN ('T0', 'T1')),
            source_turn_count INTEGER NOT NULL CHECK (source_turn_count >= 0),
            compacted_turn_count INTEGER NOT NULL CHECK (
                compacted_turn_count >= 1 AND compacted_turn_count <= source_turn_count
            ),
            compacted_digest TEXT NOT NULL CHECK (compacted_digest ~ '^sha256:[0-9a-f]{64}$'),
            state JSONB NOT NULL CHECK (jsonb_typeof(state) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (principal_id, conversation_id, snapshot_id)
        );
        CREATE INDEX ix_conversation_dialogue_snapshot_latest
            ON conversation_dialogue_snapshot (principal_id, conversation_id, recorded_at DESC);

        CREATE FUNCTION fdai_operator_dialogue_snapshot_immutable()
        RETURNS TRIGGER LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $immutable$
        BEGIN
            RAISE EXCEPTION 'dialogue-state snapshots are immutable';
        END;
        $immutable$;
        REVOKE ALL ON FUNCTION fdai_operator_dialogue_snapshot_immutable() FROM PUBLIC;
        CREATE TRIGGER conversation_dialogue_snapshot_update_immutable
            BEFORE UPDATE ON conversation_dialogue_snapshot
            FOR EACH ROW EXECUTE FUNCTION fdai_operator_dialogue_snapshot_immutable();
        CREATE TRIGGER conversation_dialogue_snapshot_delete_immutable
            BEFORE DELETE ON conversation_dialogue_snapshot
            FOR EACH ROW EXECUTE FUNCTION fdai_operator_dialogue_snapshot_immutable();

        REVOKE ALL PRIVILEGES ON TABLE conversation_dialogue_snapshot FROM PUBLIC, fdai_operator;
        GRANT SELECT, INSERT ON TABLE conversation_dialogue_snapshot TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Drop the derived table; the retained conversation turns can regenerate it."""
    op.execute(
        """
        DROP TRIGGER conversation_dialogue_snapshot_delete_immutable
            ON conversation_dialogue_snapshot;
        DROP TRIGGER conversation_dialogue_snapshot_update_immutable
            ON conversation_dialogue_snapshot;
        DROP FUNCTION fdai_operator_dialogue_snapshot_immutable();
        REVOKE ALL PRIVILEGES ON TABLE conversation_dialogue_snapshot FROM fdai_operator;
        DROP TABLE conversation_dialogue_snapshot;
        """
    )
