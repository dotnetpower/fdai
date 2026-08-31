"""Add an audited database boundary for Cost Governance enablement."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_cost_governance_settings_20260831"
down_revision: str | Sequence[str] | None = "core_ontology_property_index_20260830"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = "core_cost_governance_validation_20260829"

migration_owner = "core-control-plane"
owned_tables = (
    "cost_governance_lifecycle_receipt",
    "cost_governance_analytics_snapshot",
    "cost_governance_validation_retention",
    "cost_governance_validation_retention_event",
    "vertical_package_activation",
)
rollback = {
    "strategy": "drop-cost-governance-settings-function-after-operator-stopped",
    "restores": "core_ontology_property_index_20260830",
    "requires": "operator-cost-governance-settings-route-stopped",
}


def upgrade() -> None:
    """Create a revision-fenced function that records each enablement transition."""

    op.execute(
        """
        CREATE TABLE cost_governance_analytics_snapshot (
            snapshot_id TEXT PRIMARY KEY
                CHECK (snapshot_id ~ '^analytics:[0-9a-f]{64}$'),
            package_id TEXT NOT NULL REFERENCES vertical_package_activation(package_id),
            scope_id TEXT NOT NULL CHECK (char_length(scope_id) BETWEEN 1 AND 1024),
            observed_at TIMESTAMPTZ NOT NULL,
            source_authority TEXT NOT NULL
                CHECK (char_length(source_authority) BETWEEN 1 AND 256),
            complete BOOLEAN NOT NULL,
            payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            evidence_digest TEXT NOT NULL UNIQUE
                CHECK (evidence_digest ~ '^sha256:[0-9a-f]{64}$'),
            retention_until TIMESTAMPTZ NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (observed_at < retention_until)
        );
        CREATE INDEX cost_governance_analytics_scope_idx
            ON cost_governance_analytics_snapshot(scope_id, observed_at DESC);
        REVOKE ALL PRIVILEGES ON TABLE cost_governance_analytics_snapshot
            FROM PUBLIC, fdai_core, fdai_operator;
        GRANT SELECT, INSERT ON TABLE cost_governance_analytics_snapshot TO fdai_core;
        GRANT SELECT ON TABLE cost_governance_analytics_snapshot TO fdai_operator;

        CREATE FUNCTION fdai_set_cost_governance_enabled(
            requested_package_id TEXT,
            actor_id TEXT,
            requested_enabled BOOLEAN,
            expected_revision BIGINT,
            request_id TEXT
        )
        RETURNS TABLE (
            vertical_id TEXT,
            package_id TEXT,
            available BOOLEAN,
            enabled BOOLEAN,
            availability_reasons JSONB,
            package_version TEXT,
            image_digest TEXT,
            asset_manifest_digest TEXT,
            semantic_profile_digest TEXT,
            ontology_release_digest TEXT,
            revision BIGINT
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            current_activation vertical_package_activation%ROWTYPE;
            next_revision BIGINT;
            operation_name TEXT;
            occurred_at TIMESTAMPTZ := clock_timestamp();
            payload JSONB;
            pin_digest TEXT;
            receipt_digest TEXT;
            receipt_id TEXT;
        BEGIN
            IF requested_package_id <> 'cost-governance' THEN
                RAISE EXCEPTION 'unknown Cost Governance package' USING ERRCODE = 'CG004';
            END IF;
            IF actor_id IS NULL OR char_length(actor_id) NOT BETWEEN 1 AND 256 THEN
                RAISE EXCEPTION 'actor_id is invalid' USING ERRCODE = 'CG004';
            END IF;
            IF request_id IS NULL OR request_id !~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{7,127}$' THEN
                RAISE EXCEPTION 'request_id is invalid' USING ERRCODE = 'CG004';
            END IF;
            IF expected_revision IS NULL OR expected_revision < 0 THEN
                RAISE EXCEPTION 'expected_revision is invalid' USING ERRCODE = 'CG004';
            END IF;

            SELECT *
              INTO current_activation
              FROM vertical_package_activation
             WHERE vertical_package_activation.package_id = requested_package_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Cost Governance package is not installed'
                    USING ERRCODE = 'CG002';
            END IF;
            IF NOT current_activation.available THEN
                RAISE EXCEPTION 'Cost Governance package is unavailable'
                    USING ERRCODE = 'CG003';
            END IF;

            operation_name := CASE WHEN requested_enabled THEN 'enable' ELSE 'disable' END;
            receipt_id := 'cost-governance-settings:' || request_id;
            IF EXISTS (
                SELECT 1
                  FROM cost_governance_lifecycle_receipt
                 WHERE idempotency_key = request_id
            ) THEN
                RETURN QUERY
                SELECT activation.vertical_id, activation.package_id,
                       activation.available, activation.enabled,
                       activation.availability_reasons,
                       activation.package_version, activation.image_digest,
                       activation.asset_manifest_digest,
                       activation.semantic_profile_digest,
                       activation.ontology_release_digest, activation.revision
                  FROM vertical_package_activation AS activation
                 WHERE activation.package_id = requested_package_id;
                RETURN;
            END IF;
            IF current_activation.revision <> expected_revision THEN
                RAISE EXCEPTION 'Cost Governance activation revision conflict'
                    USING ERRCODE = 'CG001';
            END IF;

            UPDATE vertical_package_activation AS activation
               SET enabled = requested_enabled,
                   previously_enabled = activation.enabled,
                   revision = activation.revision + 1,
                   effective_at = occurred_at,
                   source_authority = 'operator-settings',
                   updated_at = occurred_at
             WHERE activation.package_id = requested_package_id
             RETURNING activation.revision INTO next_revision;

            payload := jsonb_build_object(
                'actor_id', actor_id,
                'enabled', requested_enabled,
                'expected_revision', expected_revision,
                'request_id', request_id
            );
            pin_digest := 'sha256:' || encode(
                sha256(convert_to(
                    requested_package_id || ':' || next_revision::TEXT || ':'
                    || current_activation.image_digest || ':'
                    || current_activation.ontology_release_digest,
                    'UTF8'
                )),
                'hex'
            );
            receipt_digest := 'sha256:' || encode(
                sha256(convert_to(
                    receipt_id || ':' || operation_name || ':'
                    || payload::TEXT || ':' || pin_digest,
                    'UTF8'
                )),
                'hex'
            );

            INSERT INTO cost_governance_lifecycle_receipt (
                receipt_id, package_id, activation_revision, operation, outcome,
                receipt_digest, revision_pin_digest, evidence_kind, payload,
                evidence_refs, occurred_at, idempotency_key
            )
            VALUES (
                receipt_id, requested_package_id, next_revision, operation_name, 'succeeded',
                receipt_digest, pin_digest, 'live-authoritative', payload,
                jsonb_build_array('operator-request:' || request_id),
                occurred_at, request_id
            );
            INSERT INTO cost_governance_validation_retention (
                evidence_kind, evidence_id, revision, retention_until,
                purge_after, legal_hold, legal_hold_ref, purged_at, updated_at
            )
            VALUES (
                'lifecycle-receipt', receipt_id, next_revision,
                occurred_at + INTERVAL '400 days',
                occurred_at + INTERVAL '430 days',
                FALSE, NULL, NULL, occurred_at
            );
            INSERT INTO cost_governance_validation_retention_event (
                evidence_kind, evidence_id, revision, event_kind,
                legal_hold_ref, recorded_at, idempotency_key
            )
            VALUES (
                'lifecycle-receipt', receipt_id, 1, 'created',
                NULL, occurred_at, request_id
            );

            RETURN QUERY
            SELECT activation.vertical_id, activation.package_id,
                   activation.available, activation.enabled,
                   activation.availability_reasons,
                   activation.package_version, activation.image_digest,
                   activation.asset_manifest_digest,
                   activation.semantic_profile_digest,
                   activation.ontology_release_digest, activation.revision
              FROM vertical_package_activation AS activation
             WHERE activation.package_id = requested_package_id;
        END;
        $$;
        REVOKE ALL ON FUNCTION fdai_set_cost_governance_enabled(
            TEXT, TEXT, BOOLEAN, BIGINT, TEXT
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_set_cost_governance_enabled(
            TEXT, TEXT, BOOLEAN, BIGINT, TEXT
        ) TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove the settings mutation boundary without deleting lifecycle evidence."""

    op.execute(
        """
        REVOKE EXECUTE ON FUNCTION fdai_set_cost_governance_enabled(
            TEXT, TEXT, BOOLEAN, BIGINT, TEXT
        ) FROM fdai_operator;
        DROP FUNCTION fdai_set_cost_governance_enabled(
            TEXT, TEXT, BOOLEAN, BIGINT, TEXT
        );
        REVOKE SELECT ON TABLE cost_governance_analytics_snapshot FROM fdai_operator;
        REVOKE SELECT, INSERT ON TABLE cost_governance_analytics_snapshot FROM fdai_core;
        DROP TABLE cost_governance_analytics_snapshot;
        """
    )
