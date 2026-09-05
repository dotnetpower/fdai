"""Add Core-owned operational observation lifecycle and certification evidence."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_operational_history_lifecycle_20260906"
down_revision: str | Sequence[str] | None = "core_inventory_observation_journal_20260905"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "inventory_observation_journal",
    "inventory_observation_pending_tombstone",
    "inventory_resource_incarnation",
    "inventory_observation_partition",
    "inventory_observation_lifecycle_binding",
    "inventory_observation_checkpoint",
    "inventory_observation_partition_event",
    "inventory_observation_partition_pin_event",
    "inventory_observation_correction_receipt",
    "operational_retention_policy",
    "operational_archive_artifact",
    "operational_history_certification_receipt",
)
rollback = {
    "strategy": "drop-rebuildable-operational-history-lifecycle",
    "restores": "core_inventory_observation_journal_20260905",
    "requires": "observation-archive-and-certification-writers-stopped",
}


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE operational_retention_policy (
            policy_digest TEXT PRIMARY KEY CHECK (policy_digest ~ '^sha256:[a-f0-9]{64}$'),
            policy_id TEXT NOT NULL CHECK (char_length(policy_id) BETWEEN 1 AND 512),
            fact_family TEXT NOT NULL CHECK (char_length(fact_family) BETWEEN 1 AND 512),
            purpose TEXT NOT NULL CHECK (char_length(purpose) BETWEEN 1 AND 512),
            hot_retention_seconds BIGINT NOT NULL CHECK (hot_retention_seconds >= 0),
            warm_retention_seconds BIGINT NOT NULL CHECK (
                warm_retention_seconds >= hot_retention_seconds
            ),
            archive_class TEXT NOT NULL CHECK (char_length(archive_class) BETWEEN 1 AND 512),
            deletion_method TEXT NOT NULL CHECK (
                deletion_method IN ('partition_purge', 'retain')
            ),
            review_at TIMESTAMPTZ NOT NULL,
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL,
            UNIQUE (policy_id, policy_digest)
        );
        INSERT INTO operational_retention_policy (
            policy_digest, policy_id, fact_family, purpose,
            hot_retention_seconds, warm_retention_seconds, archive_class,
            deletion_method, review_at, record, recorded_at
        ) VALUES
        (
            'sha256:086589221a8bd798816d9b1d0136c20f547a3a3cd3b1a0693122340f64f05124',
            'safety-retain-change_hint-v1', 'change_hint', 'safety-hold-unconfigured',
            0, 0, 'unconfigured-retain', 'retain', '2099-01-01T00:00:00Z',
            jsonb_build_object(
                'source', 'repository-safe-default', 'deletion_authority', FALSE
            ),
            CURRENT_TIMESTAMP
        ),
        (
            'sha256:563c8966d345e1482e8c45ae499df526d93a8b31b9afe20744a93ab0d3215e05',
            'safety-retain-partial_observation-v1', 'partial_observation',
            'safety-hold-unconfigured', 0, 0, 'unconfigured-retain', 'retain',
            '2099-01-01T00:00:00Z',
            jsonb_build_object(
                'source', 'repository-safe-default', 'deletion_authority', FALSE
            ),
            CURRENT_TIMESTAMP
        ),
        (
            'sha256:7d79453a0b979e390cd81b9cfb74a042264fa7b03b09ef1cf4dd93e63b48bb21',
            'safety-retain-full_observation-v1', 'full_observation',
            'safety-hold-unconfigured', 0, 0, 'unconfigured-retain', 'retain',
            '2099-01-01T00:00:00Z',
            jsonb_build_object(
                'source', 'repository-safe-default', 'deletion_authority', FALSE
            ),
            CURRENT_TIMESTAMP
        ),
        (
            'sha256:4d58c7727600655f67139f0728caead288a4ac205e9fc3e301ef682241a58d4d',
            'safety-retain-tombstone_candidate-v1', 'tombstone_candidate',
            'safety-hold-unconfigured', 0, 0, 'unconfigured-retain', 'retain',
            '2099-01-01T00:00:00Z',
            jsonb_build_object(
                'source', 'repository-safe-default', 'deletion_authority', FALSE
            ),
            CURRENT_TIMESTAMP
        ),
        (
            'sha256:4ad17810911dc840f8b012d2ecc8099a742da09fc2bfb0c0505b7da8f35d936b',
            'safety-retain-confirmed_tombstone-v1', 'confirmed_tombstone',
            'safety-hold-unconfigured', 0, 0, 'unconfigured-retain', 'retain',
            '2099-01-01T00:00:00Z',
            jsonb_build_object(
                'source', 'repository-safe-default', 'deletion_authority', FALSE
            ),
            CURRENT_TIMESTAMP
        ),
        (
            'sha256:c68a9729d960b8783272ab239254bf6ead2a5916b3a5aeedf17635708550059f',
            'safety-retain-relationship_observation-v1', 'relationship_observation',
            'safety-hold-unconfigured', 0, 0, 'unconfigured-retain', 'retain',
            '2099-01-01T00:00:00Z',
            jsonb_build_object(
                'source', 'repository-safe-default', 'deletion_authority', FALSE
            ),
            CURRENT_TIMESTAMP
        );
        CREATE TABLE inventory_resource_incarnation (
            incarnation_id TEXT PRIMARY KEY CHECK (incarnation_id ~ '^sha256:[a-f0-9]{64}$'),
            resource_ref TEXT NOT NULL CHECK (char_length(resource_ref) BETWEEN 1 AND 512),
            resource_type TEXT NOT NULL CHECK (char_length(resource_type) BETWEEN 1 AND 512),
            provider_identity TEXT NOT NULL
                CHECK (char_length(provider_identity) BETWEEN 1 AND 512),
            lifecycle_boundary_ref TEXT NOT NULL
                CHECK (char_length(lifecycle_boundary_ref) BETWEEN 1 AND 512),
            opened_at TIMESTAMPTZ NOT NULL,
            closed_at TIMESTAMPTZ,
            opening_observation_id TEXT NOT NULL
                CHECK (opening_observation_id ~ '^sha256:[a-f0-9]{64}$'),
            closing_observation_id TEXT
                CHECK (closing_observation_id ~ '^sha256:[a-f0-9]{64}$'),
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            CHECK (
                (closed_at IS NULL AND closing_observation_id IS NULL)
                OR (closed_at >= opened_at AND closing_observation_id IS NOT NULL)
            )
        );
        CREATE UNIQUE INDEX inventory_resource_incarnation_current_idx
            ON inventory_resource_incarnation (resource_ref) WHERE closed_at IS NULL;
        CREATE TABLE inventory_observation_partition (
            partition_id TEXT PRIMARY KEY CHECK (partition_id ~ '^sha256:[a-f0-9]{64}$'),
            scope_ref TEXT NOT NULL CHECK (char_length(scope_ref) BETWEEN 1 AND 512),
            interval_start TIMESTAMPTZ NOT NULL,
            interval_end TIMESTAMPTZ NOT NULL,
            first_watermark BIGINT NOT NULL CHECK (first_watermark >= 1),
            last_watermark BIGINT NOT NULL CHECK (last_watermark >= first_watermark),
            partition_kind TEXT NOT NULL CHECK (partition_kind IN ('base', 'correction')),
            state TEXT NOT NULL CHECK (
                state IN (
                    'open', 'sealed', 'checkpointed', 'archived', 'verified',
                    'purge_eligible', 'purged', 'held', 'correction_pending'
                )
            ),
            correction_of TEXT REFERENCES inventory_observation_partition(partition_id),
            retention_policy_digest TEXT NOT NULL
                REFERENCES operational_retention_policy(policy_digest),
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CHECK (interval_end > interval_start),
            CHECK (
                (partition_kind = 'correction' AND correction_of IS NOT NULL)
                OR (partition_kind = 'base' AND correction_of IS NULL)
            )
        );
        CREATE INDEX inventory_observation_partition_scope_time_idx
            ON inventory_observation_partition (scope_ref, interval_start, state);
        CREATE TABLE inventory_observation_lifecycle_binding (
            observation_id TEXT PRIMARY KEY
                REFERENCES inventory_observation_journal(observation_id),
            incarnation_id TEXT REFERENCES inventory_resource_incarnation(incarnation_id),
            from_incarnation_id TEXT REFERENCES inventory_resource_incarnation(incarnation_id),
            to_incarnation_id TEXT REFERENCES inventory_resource_incarnation(incarnation_id),
            partition_id TEXT NOT NULL
                REFERENCES inventory_observation_partition(partition_id),
            bound_at TIMESTAMPTZ NOT NULL,
            CHECK (
                (incarnation_id IS NOT NULL
                    AND from_incarnation_id IS NULL AND to_incarnation_id IS NULL)
                OR
                (incarnation_id IS NULL
                    AND from_incarnation_id IS NOT NULL AND to_incarnation_id IS NOT NULL)
            )
        );
        CREATE TABLE inventory_observation_checkpoint (
            checkpoint_id TEXT PRIMARY KEY CHECK (checkpoint_id ~ '^sha256:[a-f0-9]{64}$'),
            partition_id TEXT NOT NULL
                REFERENCES inventory_observation_partition(partition_id),
            first_watermark BIGINT NOT NULL CHECK (first_watermark >= 1),
            last_watermark BIGINT NOT NULL CHECK (last_watermark >= first_watermark),
            projection_watermark BIGINT NOT NULL CHECK (projection_watermark >= last_watermark),
            valid BOOLEAN NOT NULL,
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            created_at TIMESTAMPTZ NOT NULL
        );
        CREATE INDEX inventory_observation_checkpoint_partition_idx
            ON inventory_observation_checkpoint (partition_id, created_at DESC);
        CREATE TABLE inventory_observation_partition_event (
            event_id TEXT PRIMARY KEY CHECK (event_id ~ '^sha256:[a-f0-9]{64}$'),
            partition_id TEXT NOT NULL
                REFERENCES inventory_observation_partition(partition_id),
            prior_state TEXT NOT NULL,
            resulting_state TEXT NOT NULL,
            reason_code TEXT NOT NULL CHECK (char_length(reason_code) BETWEEN 1 AND 128),
            evidence_refs TEXT[] NOT NULL
                CHECK (fdai_text_array_elements_bounded(evidence_refs, 256, 512)),
            recorded_at TIMESTAMPTZ NOT NULL,
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object')
        );
        CREATE TABLE inventory_observation_partition_pin_event (
            pin_event_id TEXT PRIMARY KEY CHECK (pin_event_id ~ '^sha256:[a-f0-9]{64}$'),
            pin_id TEXT NOT NULL CHECK (pin_id ~ '^sha256:[a-f0-9]{64}$'),
            partition_id TEXT NOT NULL
                REFERENCES inventory_observation_partition(partition_id),
            pin_kind TEXT NOT NULL CHECK (
                pin_kind IN (
                    'incident', 'investigation', 'approval', 'execution', 'rollback',
                    'legal_hold', 'replay_lease'
                )
            ),
            case_ref TEXT NOT NULL CHECK (char_length(case_ref) BETWEEN 1 AND 512),
            placed_at TIMESTAMPTZ NOT NULL,
            released_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            evidence_refs TEXT[] NOT NULL
                CHECK (fdai_text_array_elements_bounded(evidence_refs, 256, 512)),
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            CHECK (released_at IS NULL OR released_at >= placed_at),
            CHECK (expires_at IS NULL OR expires_at >= placed_at),
            CHECK (pin_kind <> 'legal_hold' OR expires_at IS NULL)
        );
        CREATE INDEX inventory_observation_pin_active_idx
            ON inventory_observation_partition_pin_event (
                partition_id, pin_id, placed_at, released_at
            );
        CREATE TABLE inventory_observation_correction_receipt (
            receipt_id TEXT PRIMARY KEY CHECK (receipt_id ~ '^sha256:[a-f0-9]{64}$'),
            correction_partition_id TEXT NOT NULL
                REFERENCES inventory_observation_partition(partition_id),
            projection_watermark BIGINT NOT NULL CHECK (projection_watermark >= 1),
            complete BOOLEAN NOT NULL,
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            closed_at TIMESTAMPTZ NOT NULL
        );
        CREATE TABLE operational_archive_artifact (
            artifact_digest TEXT PRIMARY KEY CHECK (artifact_digest ~ '^sha256:[a-f0-9]{64}$'),
            storage_ref TEXT NOT NULL UNIQUE
                CHECK (char_length(storage_ref) BETWEEN 1 AND 512),
            manifest_digest TEXT NOT NULL
                REFERENCES operational_archive_manifest(manifest_digest),
            scope_refs TEXT[] NOT NULL
                CHECK (fdai_text_array_elements_bounded(scope_refs, 256, 512)),
            allowed_purposes TEXT[] NOT NULL
                CHECK (fdai_text_array_elements_bounded(allowed_purposes, 32, 128)),
            byte_count BIGINT NOT NULL CHECK (byte_count > 0),
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            created_at TIMESTAMPTZ NOT NULL
        );
        CREATE TABLE operational_history_certification_receipt (
            receipt_digest TEXT PRIMARY KEY CHECK (receipt_digest ~ '^sha256:[a-f0-9]{64}$'),
            source_revision TEXT NOT NULL
                CHECK (char_length(source_revision) BETWEEN 1 AND 128),
            complete BOOLEAN NOT NULL,
            scenario_results JSONB NOT NULL CHECK (jsonb_typeof(scenario_results) = 'object'),
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL
        );
        CREATE FUNCTION fdai_reject_operational_history_lifecycle_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF current_setting('fdai.archive_purge', true) = 'authorized' THEN
                RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
            END IF;
            RAISE EXCEPTION 'operational history lifecycle evidence is append-only';
        END;
        $$;
        CREATE OR REPLACE FUNCTION fdai_reject_inventory_observation_journal_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF current_setting('fdai.archive_purge', true) = 'authorized' THEN
                RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
            END IF;
            RAISE EXCEPTION 'inventory observation journal is append-only';
        END;
        $$;
        CREATE TRIGGER operational_retention_policy_no_modify
            BEFORE UPDATE ON operational_retention_policy
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_history_lifecycle_mutation();
        CREATE TRIGGER operational_retention_policy_no_delete
            BEFORE DELETE ON operational_retention_policy
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_history_lifecycle_mutation();
        CREATE TRIGGER inventory_observation_lifecycle_binding_no_modify
            BEFORE UPDATE ON inventory_observation_lifecycle_binding
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_history_lifecycle_mutation();
        CREATE TRIGGER inventory_observation_lifecycle_binding_no_delete
            BEFORE DELETE ON inventory_observation_lifecycle_binding
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_history_lifecycle_mutation();
        CREATE TRIGGER inventory_observation_checkpoint_no_modify
            BEFORE UPDATE ON inventory_observation_checkpoint
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_history_lifecycle_mutation();
        CREATE TRIGGER inventory_observation_checkpoint_no_delete
            BEFORE DELETE ON inventory_observation_checkpoint
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_history_lifecycle_mutation();
        CREATE TRIGGER inventory_observation_partition_event_no_modify
            BEFORE UPDATE ON inventory_observation_partition_event
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_history_lifecycle_mutation();
        CREATE TRIGGER inventory_observation_partition_event_no_delete
            BEFORE DELETE ON inventory_observation_partition_event
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_history_lifecycle_mutation();
        CREATE TRIGGER inventory_observation_partition_pin_event_no_modify
            BEFORE UPDATE ON inventory_observation_partition_pin_event
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_history_lifecycle_mutation();
        CREATE TRIGGER inventory_observation_partition_pin_event_no_delete
            BEFORE DELETE ON inventory_observation_partition_pin_event
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_history_lifecycle_mutation();
        CREATE TRIGGER inventory_observation_correction_receipt_no_modify
            BEFORE UPDATE ON inventory_observation_correction_receipt
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_history_lifecycle_mutation();
        CREATE TRIGGER inventory_observation_correction_receipt_no_delete
            BEFORE DELETE ON inventory_observation_correction_receipt
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_history_lifecycle_mutation();
        CREATE TRIGGER operational_archive_artifact_no_modify
            BEFORE UPDATE ON operational_archive_artifact
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_history_lifecycle_mutation();
        CREATE TRIGGER operational_archive_artifact_no_delete
            BEFORE DELETE ON operational_archive_artifact
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_history_lifecycle_mutation();
        CREATE TRIGGER operational_history_certification_receipt_no_modify
            BEFORE UPDATE ON operational_history_certification_receipt
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_history_lifecycle_mutation();
        CREATE TRIGGER operational_history_certification_receipt_no_delete
            BEFORE DELETE ON operational_history_certification_receipt
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_history_lifecycle_mutation();
        CREATE FUNCTION fdai_purge_observation_partition(requested_partition_id TEXT)
        RETURNS BIGINT LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
        DECLARE
            deleted_rows BIGINT;
            selected_manifest_digest TEXT;
            observation_ids TEXT[];
        BEGIN
            SELECT artifact.manifest_digest
              INTO selected_manifest_digest
              FROM inventory_observation_partition AS partition
              JOIN operational_retention_policy AS policy
                ON policy.policy_digest = partition.retention_policy_digest
              JOIN inventory_observation_checkpoint AS checkpoint
                ON checkpoint.partition_id = partition.partition_id
               AND checkpoint.valid
              JOIN operational_archive_artifact AS artifact
                ON artifact.scope_refs @> ARRAY[partition.scope_ref]
             WHERE partition.partition_id = requested_partition_id
               AND partition.state = 'purge_eligible'
               AND policy.deletion_method = 'partition_purge'
               AND EXISTS (
                    SELECT 1 FROM operational_archive_verification_receipt AS verification
                     WHERE verification.manifest_digest = artifact.manifest_digest
                       AND verification.verified
               )
               AND EXISTS (
                    SELECT 1 FROM operational_archive_restore_receipt AS restore
                     WHERE restore.manifest_digest = artifact.manifest_digest
                       AND restore.passed
               )
               AND (
                    partition.partition_kind = 'base'
                    OR (
                        EXISTS (
                        SELECT 1 FROM inventory_observation_correction_receipt AS correction
                         WHERE correction.correction_partition_id = partition.partition_id
                           AND correction.complete
                        )
                    )
               )
               AND NOT EXISTS (
                    SELECT 1 FROM inventory_observation_partition AS pending_correction
                     WHERE pending_correction.correction_of = partition.partition_id
                       AND pending_correction.state = 'correction_pending'
               )
               AND NOT EXISTS (
                    SELECT 1
                      FROM inventory_observation_correction_receipt AS correction
                      JOIN inventory_observation_partition AS correction_partition
                        ON correction_partition.partition_id =
                           correction.correction_partition_id
                     WHERE correction_partition.correction_of = partition.partition_id
                       AND correction.complete
                       AND checkpoint.created_at <= correction.closed_at
                    )
               AND NOT EXISTS (
                    SELECT 1
                      FROM (
                            SELECT DISTINCT ON (pin_id)
                                pin_id, placed_at, released_at, expires_at
                              FROM inventory_observation_partition_pin_event
                             WHERE partition_id = partition.partition_id
                             ORDER BY pin_id, COALESCE(released_at, placed_at) DESC,
                                      pin_event_id DESC
                      ) AS pin
                     WHERE pin.released_at IS NULL
                       AND (pin.expires_at IS NULL OR pin.expires_at > CURRENT_TIMESTAMP)
               )
             ORDER BY checkpoint.created_at DESC
             LIMIT 1
             FOR UPDATE OF partition;
            IF selected_manifest_digest IS NULL THEN
                RAISE EXCEPTION 'observation partition purge gates are incomplete';
            END IF;
            PERFORM set_config('fdai.archive_purge', 'authorized', true);
            SELECT COALESCE(array_agg(observation_id), '{}')
              INTO observation_ids
              FROM inventory_observation_lifecycle_binding
             WHERE partition_id = requested_partition_id;
            DELETE FROM inventory_observation_pending_tombstone
             WHERE observation_id = ANY(observation_ids);
            DELETE FROM inventory_observation_lifecycle_binding
             WHERE partition_id = requested_partition_id;
            GET DIAGNOSTICS deleted_rows = ROW_COUNT;
            DELETE FROM inventory_observation_journal
             WHERE observation_id = ANY(observation_ids);
            UPDATE inventory_observation_partition
               SET state = 'purged', updated_at = CURRENT_TIMESTAMP
             WHERE partition_id = requested_partition_id;
            RETURN deleted_rows;
        END;
        $$;
        REVOKE ALL ON FUNCTION fdai_purge_observation_partition(TEXT) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_purge_observation_partition(TEXT) TO fdai_core;
        """
    )
    op.execute(
        """
        GRANT SELECT, INSERT ON TABLE
            operational_retention_policy,
            inventory_resource_incarnation,
            inventory_observation_partition,
            inventory_observation_lifecycle_binding,
            inventory_observation_checkpoint,
            inventory_observation_partition_event,
            inventory_observation_partition_pin_event,
            inventory_observation_correction_receipt,
            operational_archive_artifact,
            operational_history_certification_receipt
        TO fdai_core;
        GRANT UPDATE ON TABLE
            inventory_resource_incarnation,
            inventory_observation_partition
        TO fdai_core;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            operational_history_certification_receipt,
            operational_archive_artifact,
            inventory_observation_correction_receipt,
            inventory_observation_partition_pin_event,
            inventory_observation_partition_event,
            inventory_observation_checkpoint,
            inventory_observation_lifecycle_binding,
            inventory_observation_partition,
            inventory_resource_incarnation,
            operational_retention_policy
        FROM fdai_core;
        REVOKE ALL ON FUNCTION fdai_purge_observation_partition(TEXT) FROM fdai_core;
        DROP FUNCTION fdai_purge_observation_partition(TEXT);
        DROP TABLE operational_history_certification_receipt;
        DROP TABLE operational_archive_artifact;
        DROP TABLE inventory_observation_correction_receipt;
        DROP TABLE inventory_observation_partition_pin_event;
        DROP TABLE inventory_observation_partition_event;
        DROP TABLE inventory_observation_checkpoint;
        DROP TABLE inventory_observation_lifecycle_binding;
        DROP TABLE inventory_observation_partition;
        DROP TABLE inventory_resource_incarnation;
        DROP TABLE operational_retention_policy;
        DROP FUNCTION fdai_reject_operational_history_lifecycle_mutation();
        CREATE OR REPLACE FUNCTION fdai_reject_inventory_observation_journal_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'inventory observation journal is append-only';
        END;
        $$;
        """
    )
