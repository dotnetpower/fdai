-- Migration Revision: operator_dialogue_state_snapshot_20261028
-- Down Revision: operator_automation_blueprint_intent_20261019
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
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
