"""Add isolated retention and recovery support for OI-16 certification."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_oi16_synthetic_retention_20260907"
down_revision: str | Sequence[str] | None = "core_t2_cache_lookup_repair_20260906"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "inventory_observation_checkpoint",
    "inventory_observation_correction_receipt",
    "inventory_observation_journal",
    "inventory_observation_lifecycle_binding",
    "inventory_observation_partition",
    "inventory_observation_partition_pin_event",
    "inventory_observation_pending_tombstone",
    "operational_archive_artifact",
    "operational_archive_manifest",
    "operational_archive_restore_receipt",
    "operational_archive_verification_receipt",
    "operational_history_recovery_rehearsal",
    "operational_retention_policy",
)
rollback = {
    "strategy": "remove-oi16-recovery-data-and-restore-standard-purge-gate",
    "restores": "core_t2_cache_lookup_repair_20260906",
    "requires": "operational-history-certification-writers-stopped",
}


def upgrade() -> None:
    """Add isolated recovery storage, policy, and database-enforced synthetic gate."""

    op.execute(
        """
        CREATE TABLE operational_history_recovery_rehearsal (
            campaign_id TEXT NOT NULL
                CHECK (campaign_id ~ '^certify-history-[0-9a-f]{48}$'),
            scope_ref TEXT NOT NULL
                CHECK (scope_ref ~ '^synthetic/oi16-certification/[0-9a-f]{48}$'),
            partition_id TEXT NOT NULL
                CHECK (partition_id ~ '^sha256:[0-9a-f]{64}$'),
            observation_id TEXT NOT NULL
                CHECK (observation_id ~ '^sha256:[0-9a-f]{64}$'),
            content_digest TEXT NOT NULL
                CHECK (content_digest ~ '^sha256:[0-9a-f]{64}$'),
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            recovered_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (campaign_id, observation_id),
            CHECK (record->>'scope_ref' = scope_ref),
            CHECK (record->>'observation_id' = observation_id),
            CHECK (record->>'content_digest' = content_digest)
        );
        CREATE INDEX operational_history_recovery_rehearsal_partition_idx
            ON operational_history_recovery_rehearsal
            (campaign_id, partition_id, observation_id);
        CREATE TRIGGER operational_history_recovery_rehearsal_update_guard
            BEFORE UPDATE ON operational_history_recovery_rehearsal
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_history_lifecycle_mutation();
        CREATE TRIGGER operational_history_recovery_rehearsal_delete_guard
            BEFORE DELETE ON operational_history_recovery_rehearsal
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_history_lifecycle_mutation();
        INSERT INTO operational_retention_policy (
            policy_digest, policy_id, fact_family, purpose,
            hot_retention_seconds, warm_retention_seconds, archive_class,
            deletion_method, review_at, record, recorded_at
        ) VALUES (
            'sha256:9d9ef7da4609bdc9c9626d82c8443c89f34072b5f98973181fb9409f652fdb52',
            'oi16-dev-synthetic-purge-v1',
            'oi16_synthetic_full_observation',
            'oi16-dev-synthetic-certification',
            0,
            0,
            'dev-synthetic-ephemeral',
            'partition_purge',
            '2099-01-01T00:00:00Z',
            jsonb_build_object(
                'source', 'repository-bounded-certification',
                'deletion_authority', TRUE,
                'scope_prefix', 'synthetic/oi16-certification/'
            ),
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (policy_digest) DO NOTHING;
        GRANT SELECT, INSERT ON TABLE operational_history_recovery_rehearsal TO fdai_core;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fdai_purge_observation_partition(requested_partition_id TEXT)
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
              JOIN operational_archive_artifact AS artifact
                ON artifact.scope_refs @> ARRAY[partition.scope_ref]
              JOIN operational_archive_manifest AS manifest
                ON manifest.manifest_digest = artifact.manifest_digest
               AND manifest.coverage_complete
               AND manifest.record->'source_partitions' @>
                   jsonb_build_array(jsonb_build_object('partition_id', partition.partition_id))
             WHERE partition.partition_id = requested_partition_id
               AND partition.state = 'purge_eligible'
               AND policy.deletion_method = 'partition_purge'
               AND (
                    checkpoint.valid
                    OR (
                        policy.policy_digest =
                          'sha256:9d9ef7da4609bdc9c9626d82c8443c89f34072b5f98973181fb9409f652fdb52'
                        AND partition.scope_ref ~
                          '^synthetic/oi16-certification/[0-9a-f]{48}$'
                        AND COALESCE((checkpoint.record->>'object_count')::BIGINT, 0) > 0
                        AND COALESCE((checkpoint.record->>'missing_count')::BIGINT, 0) = 0
                        AND COALESCE((checkpoint.record->>'quarantined_count')::BIGINT, 0) = 0
                        AND COALESCE((checkpoint.record->>'conflicted_count')::BIGINT, 0) = 0
                    )
               )
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
                    OR EXISTS (
                        SELECT 1
                          FROM inventory_observation_correction_receipt AS correction
                         WHERE correction.correction_partition_id = partition.partition_id
                           AND correction.complete
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
                        ON correction_partition.partition_id = correction.correction_partition_id
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
        """
    )


def downgrade() -> None:
    """Restore the standard projection-valid gate and remove the synthetic policy."""

    op.execute(
        """
        CREATE OR REPLACE FUNCTION fdai_purge_observation_partition(requested_partition_id TEXT)
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
                    OR EXISTS (
                        SELECT 1
                          FROM inventory_observation_correction_receipt AS correction
                         WHERE correction.correction_partition_id = partition.partition_id
                           AND correction.complete
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
                        ON correction_partition.partition_id = correction.correction_partition_id
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
        DROP TABLE operational_history_recovery_rehearsal;
        SELECT set_config('fdai.archive_purge', 'authorized', true);
        DELETE FROM operational_retention_policy AS policy
        WHERE policy_digest =
          'sha256:9d9ef7da4609bdc9c9626d82c8443c89f34072b5f98973181fb9409f652fdb52'
          AND fact_family = 'oi16_synthetic_full_observation'
          AND purpose = 'oi16-dev-synthetic-certification'
          AND NOT EXISTS (
              SELECT 1
              FROM inventory_observation_partition AS partition
              WHERE partition.retention_policy_digest = policy.policy_digest
          );
        SELECT set_config('fdai.archive_purge', '', true);
        """
    )
