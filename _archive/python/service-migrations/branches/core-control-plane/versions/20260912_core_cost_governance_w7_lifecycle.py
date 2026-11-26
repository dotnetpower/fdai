"""Make Cost Governance lifecycle receipts exact, canonical, and deployable."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_cost_governance_w7_lifecycle_20260912"
down_revision: str | Sequence[str] | None = "core_resource_change_sources_20260912"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "cost_governance_lifecycle_receipt",
    "cost_governance_validation_retention",
    "cost_governance_validation_retention_event",
    "vertical_package_activation",
)
rollback = {
    "strategy": "remove-cost-governance-release-pin-and-receipt-triggers",
    "restores": "core_resource_change_sources_20260912",
    "requires": "cost-governance-lifecycle-writers-stopped",
}


def upgrade() -> None:
    """Bind live lifecycle writes to a complete exact release pin."""

    op.execute(
        """
        ALTER TABLE vertical_package_activation
            ADD COLUMN source_revision TEXT NULL,
            ADD COLUMN wheel_digest TEXT NULL,
            ADD COLUMN runtime_config_digest TEXT NULL,
            ADD CONSTRAINT vertical_package_activation_release_pin_check CHECK (
                (
                    source_revision IS NULL
                    AND wheel_digest IS NULL
                    AND runtime_config_digest IS NULL
                ) OR (
                    source_revision ~ '^[0-9a-f]{40}$'
                    AND wheel_digest ~ '^sha256:[0-9a-f]{64}$'
                    AND runtime_config_digest ~ '^sha256:[0-9a-f]{64}$'
                )
            );

        CREATE FUNCTION fdai_cost_governance_canonical_json(document JSONB)
        RETURNS TEXT
        LANGUAGE plpgsql
        IMMUTABLE
        STRICT
        SET search_path = pg_catalog, public
        AS $canonical$
        DECLARE
            rendered TEXT;
        BEGIN
            CASE jsonb_typeof(document)
                WHEN 'object' THEN
                    SELECT COALESCE(
                        '{' || string_agg(
                            to_json(entry.key)::TEXT || ':' ||
                            fdai_cost_governance_canonical_json(entry.value),
                            ',' ORDER BY entry.key
                        ) || '}',
                        '{}'
                    )
                    INTO rendered
                    FROM jsonb_each(document) AS entry(key, value);
                WHEN 'array' THEN
                    SELECT COALESCE(
                        '[' || string_agg(
                            fdai_cost_governance_canonical_json(entry.value),
                            ',' ORDER BY entry.ordinality
                        ) || ']',
                        '[]'
                    )
                    INTO rendered
                    FROM jsonb_array_elements(document)
                        WITH ORDINALITY AS entry(value, ordinality);
                ELSE
                    rendered := document::TEXT;
            END CASE;
            RETURN rendered;
        END;
        $canonical$;
        REVOKE ALL ON FUNCTION fdai_cost_governance_canonical_json(JSONB) FROM PUBLIC;

        CREATE FUNCTION fdai_cost_governance_rfc3339(value TIMESTAMPTZ)
        RETURNS TEXT
        LANGUAGE sql
        IMMUTABLE
        STRICT
        SET search_path = pg_catalog
        AS $timestamp$
            SELECT CASE
                WHEN EXTRACT(MICROSECONDS FROM value)::BIGINT % 1000000 = 0
                    THEN to_char(value AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS')
                ELSE to_char(value AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US')
            END || '+00:00'
        $timestamp$;
        REVOKE ALL ON FUNCTION fdai_cost_governance_rfc3339(TIMESTAMPTZ) FROM PUBLIC;

        CREATE FUNCTION fdai_canonicalize_cost_governance_lifecycle_receipt()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $receipt$
        DECLARE
            activation vertical_package_activation%ROWTYPE;
            pin JSONB;
            retention_until TIMESTAMPTZ;
            legal_hold BOOLEAN;
            legal_hold_ref TEXT;
            request_digest TEXT;
        BEGIN
            IF NEW.evidence_kind <> 'live-authoritative' THEN
                RETURN NEW;
            END IF;
            request_digest := current_setting(
                'fdai.cost_governance_request_digest',
                TRUE
            );
            IF request_digest IS NOT NULL AND request_digest <> '' THEN
                IF request_digest !~ '^request:sha256:[0-9a-f]{64}$'
                    OR jsonb_array_length(NEW.evidence_refs) >= 64 THEN
                    RAISE EXCEPTION 'Cost Governance lifecycle request digest is invalid'
                        USING ERRCODE = 'CG004';
                END IF;
                NEW.evidence_refs := NEW.evidence_refs || jsonb_build_array(request_digest);
            END IF;
            SELECT * INTO activation
              FROM vertical_package_activation
             WHERE package_id = NEW.package_id
               AND revision = NEW.activation_revision;
            IF NOT FOUND OR activation.source_revision IS NULL
                OR activation.wheel_digest IS NULL
                OR activation.runtime_config_digest IS NULL THEN
                RAISE EXCEPTION 'Cost Governance exact release pin is unavailable'
                    USING ERRCODE = 'CG005';
            END IF;
            IF NEW.outcome = 'succeeded' AND (
                (NEW.operation IN ('install', 'disable') AND activation.enabled)
                OR (NEW.operation = 'enable' AND (
                    NOT activation.available OR NOT activation.enabled
                ))
            ) THEN
                RAISE EXCEPTION 'Cost Governance lifecycle state is inconsistent'
                    USING ERRCODE = 'CG004';
            END IF;

            retention_until := COALESCE(
                (NEW.payload ->> 'retention_until')::TIMESTAMPTZ,
                NEW.occurred_at + INTERVAL '400 days'
            );
            legal_hold := COALESCE((NEW.payload ->> 'legal_hold')::BOOLEAN, FALSE);
            legal_hold_ref := NEW.payload ->> 'legal_hold_ref';
            IF legal_hold <> (legal_hold_ref IS NOT NULL) THEN
                RAISE EXCEPTION 'Cost Governance legal hold state is inconsistent'
                    USING ERRCODE = 'CG004';
            END IF;

            pin := jsonb_build_object(
                'activation_revision', activation.revision,
                'asset_manifest_digest', activation.asset_manifest_digest,
                'image_digest', activation.image_digest,
                'ontology_release_digest', activation.ontology_release_digest,
                'package_id', activation.package_id,
                'package_version', activation.package_version,
                'runtime_config_digest', activation.runtime_config_digest,
                'semantic_profile_digest', activation.semantic_profile_digest,
                'source_revision', activation.source_revision,
                'wheel_digest', activation.wheel_digest
            );
            NEW.revision_pin_digest := 'sha256:' || encode(
                sha256(convert_to(fdai_cost_governance_canonical_json(pin), 'UTF8')),
                'hex'
            );
            NEW.payload := jsonb_build_object(
                'available', activation.available,
                'enabled', activation.enabled,
                'evidence_kind', NEW.evidence_kind,
                'evidence_refs', NEW.evidence_refs,
                'idempotency_key', NEW.idempotency_key,
                'legal_hold', legal_hold,
                'legal_hold_ref', legal_hold_ref,
                'occurred_at', fdai_cost_governance_rfc3339(NEW.occurred_at),
                'operation', NEW.operation,
                'outcome', NEW.outcome,
                'receipt_id', NEW.receipt_id,
                'retention_until', fdai_cost_governance_rfc3339(retention_until),
                'revision_pin', pin,
                'schema_version', '1.0.0'
            );
            NEW.receipt_digest := 'sha256:' || encode(
                sha256(convert_to(
                    fdai_cost_governance_canonical_json(NEW.payload),
                    'UTF8'
                )),
                'hex'
            );
            RETURN NEW;
        END;
        $receipt$;
        REVOKE ALL ON FUNCTION fdai_canonicalize_cost_governance_lifecycle_receipt()
            FROM PUBLIC;

        CREATE TRIGGER canonicalize_cost_governance_lifecycle_receipt
        BEFORE INSERT ON cost_governance_lifecycle_receipt
        FOR EACH ROW
        EXECUTE FUNCTION fdai_canonicalize_cost_governance_lifecycle_receipt();

        CREATE FUNCTION fdai_normalize_cost_governance_retention_revision()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $retention$
        BEGIN
            IF NEW.evidence_kind = 'lifecycle-receipt' THEN
                NEW.revision := 1;
            END IF;
            RETURN NEW;
        END;
        $retention$;
        REVOKE ALL ON FUNCTION fdai_normalize_cost_governance_retention_revision()
            FROM PUBLIC;

        CREATE TRIGGER normalize_cost_governance_retention_revision
        BEFORE INSERT ON cost_governance_validation_retention
        FOR EACH ROW
        EXECUTE FUNCTION fdai_normalize_cost_governance_retention_revision();

        ALTER FUNCTION fdai_set_cost_governance_enabled(
            TEXT, TEXT, BOOLEAN, BIGINT, TEXT
        ) RENAME TO fdai_set_cost_governance_enabled_legacy;

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
        AS $settings$
        DECLARE
            operation_name TEXT;
            request_digest TEXT;
            existing_receipt cost_governance_lifecycle_receipt%ROWTYPE;
        BEGIN
            IF requested_package_id <> 'cost-governance'
                OR actor_id IS NULL
                OR char_length(actor_id) NOT BETWEEN 1 AND 256
                OR requested_enabled IS NULL
                OR expected_revision IS NULL OR expected_revision < 0
                OR request_id IS NULL
                OR request_id !~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{7,127}$' THEN
                RAISE EXCEPTION 'Cost Governance settings request is invalid'
                    USING ERRCODE = 'CG004';
            END IF;
            operation_name := CASE WHEN requested_enabled THEN 'enable' ELSE 'disable' END;
            request_digest := 'request:sha256:' || encode(
                sha256(convert_to(fdai_cost_governance_canonical_json(
                    jsonb_build_object(
                        'actor_id', actor_id,
                        'expected_revision', expected_revision,
                        'operation', operation_name,
                        'package_id', requested_package_id,
                        'request_id', request_id,
                        'requested_enabled', requested_enabled
                    )
                ), 'UTF8')),
                'hex'
            );
            PERFORM pg_advisory_xact_lock(
                hashtextextended('cost-governance-settings:' || requested_package_id, 0)
            );
            SELECT * INTO existing_receipt
              FROM cost_governance_lifecycle_receipt
             WHERE idempotency_key = request_id;
            IF FOUND THEN
                IF existing_receipt.operation <> operation_name
                    OR NOT existing_receipt.evidence_refs @>
                        jsonb_build_array(request_digest) THEN
                    RAISE EXCEPTION 'Cost Governance lifecycle idempotency conflict'
                        USING ERRCODE = 'CG004';
                END IF;
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
            PERFORM set_config(
                'fdai.cost_governance_request_digest', request_digest, TRUE
            );
            RETURN QUERY SELECT * FROM fdai_set_cost_governance_enabled_legacy(
                requested_package_id,
                actor_id,
                requested_enabled,
                expected_revision,
                request_id
            );
            PERFORM set_config('fdai.cost_governance_request_digest', '', TRUE);
        END;
        $settings$;
        REVOKE ALL ON FUNCTION fdai_set_cost_governance_enabled(
            TEXT, TEXT, BOOLEAN, BIGINT, TEXT
        ) FROM PUBLIC;
        REVOKE ALL ON FUNCTION fdai_set_cost_governance_enabled_legacy(
            TEXT, TEXT, BOOLEAN, BIGINT, TEXT
        ) FROM PUBLIC;

        CREATE FUNCTION fdai_register_cost_governance_release(
            requested_operation TEXT,
            requested_package_id TEXT,
            requested_vertical_id TEXT,
            requested_package_version TEXT,
            requested_image_digest TEXT,
            requested_wheel_digest TEXT,
            requested_asset_manifest_digest TEXT,
            requested_semantic_profile_digest TEXT,
            requested_ontology_release_id TEXT,
            requested_ontology_release_digest TEXT,
            requested_source_revision TEXT,
            requested_runtime_config_digest TEXT,
            expected_revision BIGINT,
            request_id TEXT,
            requested_evidence_refs JSONB
        )
        RETURNS SETOF vertical_package_activation
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $register$
        DECLARE
            current_activation vertical_package_activation%ROWTYPE;
            next_revision BIGINT;
            occurred_at TIMESTAMPTZ := clock_timestamp();
            receipt_id TEXT := 'cost-governance-lifecycle:' || request_id;
            request_digest TEXT;
            existing_receipt cost_governance_lifecycle_receipt%ROWTYPE;
        BEGIN
            IF requested_operation NOT IN ('install', 'upgrade', 'rollback')
                OR requested_package_id <> 'cost-governance'
                OR requested_vertical_id <> 'cost-governance'
                OR requested_package_version !~ '^[0-9]+[.][0-9]+[.][0-9]+$'
                OR requested_source_revision !~ '^[0-9a-f]{40}$'
                OR requested_image_digest !~ '^sha256:[0-9a-f]{64}$'
                OR requested_wheel_digest !~ '^sha256:[0-9a-f]{64}$'
                OR requested_asset_manifest_digest !~ '^sha256:[0-9a-f]{64}$'
                OR requested_semantic_profile_digest !~ '^sha256:[0-9a-f]{64}$'
                OR requested_ontology_release_digest !~ '^sha256:[0-9a-f]{64}$'
                OR requested_runtime_config_digest !~ '^sha256:[0-9a-f]{64}$'
                OR requested_ontology_release_id IS NULL
                OR char_length(requested_ontology_release_id) NOT BETWEEN 1 AND 256
                OR expected_revision IS NULL OR expected_revision < 0
                OR request_id IS NULL
                OR request_id !~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{7,127}$'
                OR jsonb_typeof(requested_evidence_refs) <> 'array'
                OR jsonb_array_length(requested_evidence_refs) NOT BETWEEN 1 AND 63
                OR EXISTS (
                    SELECT 1 FROM jsonb_array_elements(requested_evidence_refs) AS item
                    WHERE jsonb_typeof(item) <> 'string'
                       OR char_length(item #>> '{}') NOT BETWEEN 1 AND 512
                ) THEN
                RAISE EXCEPTION 'Cost Governance release registration is invalid'
                    USING ERRCODE = 'CG004';
            END IF;

            PERFORM pg_advisory_xact_lock(
                hashtextextended('cost-governance-release:' || requested_package_id, 0)
            );
            request_digest := 'request:sha256:' || encode(
                sha256(convert_to(fdai_cost_governance_canonical_json(
                    jsonb_build_object(
                        'asset_manifest_digest', requested_asset_manifest_digest,
                        'evidence_refs', requested_evidence_refs,
                        'expected_revision', expected_revision,
                        'image_digest', requested_image_digest,
                        'ontology_release_digest', requested_ontology_release_digest,
                        'ontology_release_id', requested_ontology_release_id,
                        'operation', requested_operation,
                        'package_id', requested_package_id,
                        'package_version', requested_package_version,
                        'request_id', request_id,
                        'runtime_config_digest', requested_runtime_config_digest,
                        'semantic_profile_digest', requested_semantic_profile_digest,
                        'source_revision', requested_source_revision,
                        'vertical_id', requested_vertical_id,
                        'wheel_digest', requested_wheel_digest
                    )
                ), 'UTF8')),
                'hex'
            );
            SELECT * INTO existing_receipt
              FROM cost_governance_lifecycle_receipt
             WHERE idempotency_key = request_id;
            IF FOUND THEN
                IF existing_receipt.operation <> requested_operation
                    OR NOT existing_receipt.evidence_refs @>
                        jsonb_build_array(request_digest) THEN
                    RAISE EXCEPTION 'Cost Governance lifecycle idempotency conflict'
                        USING ERRCODE = 'CG004';
                END IF;
                RETURN QUERY SELECT * FROM vertical_package_activation
                    WHERE package_id = requested_package_id;
                RETURN;
            END IF;

            SELECT * INTO current_activation
              FROM vertical_package_activation
             WHERE package_id = requested_package_id
             FOR UPDATE;
            IF requested_operation = 'install' THEN
                IF FOUND OR expected_revision <> 0 THEN
                    RAISE EXCEPTION 'Cost Governance install revision conflict'
                        USING ERRCODE = 'CG001';
                END IF;
                next_revision := 1;
                INSERT INTO vertical_package_activation (
                    package_id, vertical_id, available, enabled, previously_enabled,
                    availability_reasons, package_version, image_digest,
                    asset_manifest_digest, semantic_profile_digest, revision,
                    effective_at, ontology_release_id, ontology_release_digest,
                    source_authority, updated_at, source_revision, wheel_digest,
                    runtime_config_digest
                ) VALUES (
                    requested_package_id, requested_vertical_id, TRUE, FALSE, FALSE,
                    '[]'::JSONB, requested_package_version, requested_image_digest,
                    requested_asset_manifest_digest, requested_semantic_profile_digest,
                    next_revision, occurred_at, requested_ontology_release_id,
                    requested_ontology_release_digest,
                    'protected-cost-governance-lifecycle', occurred_at,
                    requested_source_revision, requested_wheel_digest,
                    requested_runtime_config_digest
                );
            ELSE
                IF NOT FOUND OR current_activation.revision <> expected_revision THEN
                    RAISE EXCEPTION 'Cost Governance release revision conflict'
                        USING ERRCODE = 'CG001';
                END IF;
                IF requested_operation = 'upgrade'
                    AND current_activation.package_version = requested_package_version
                    AND current_activation.image_digest = requested_image_digest THEN
                    RAISE EXCEPTION 'Cost Governance upgrade MUST change the release'
                        USING ERRCODE = 'CG004';
                END IF;
                IF requested_operation = 'rollback' AND NOT EXISTS (
                    SELECT 1
                      FROM cost_governance_lifecycle_receipt AS receipt
                     WHERE receipt.package_id = requested_package_id
                       AND receipt.outcome = 'succeeded'
                       AND receipt.operation IN ('install', 'upgrade')
                       AND receipt.payload -> 'revision_pin' - 'activation_revision' =
                           jsonb_build_object(
                               'asset_manifest_digest', requested_asset_manifest_digest,
                               'image_digest', requested_image_digest,
                               'ontology_release_digest', requested_ontology_release_digest,
                               'package_id', requested_package_id,
                               'package_version', requested_package_version,
                               'runtime_config_digest', requested_runtime_config_digest,
                               'semantic_profile_digest', requested_semantic_profile_digest,
                               'source_revision', requested_source_revision,
                               'wheel_digest', requested_wheel_digest
                           )
                ) THEN
                    RAISE EXCEPTION 'Cost Governance rollback release was not retained'
                        USING ERRCODE = 'CG004';
                END IF;
                next_revision := expected_revision + 1;
                UPDATE vertical_package_activation
                   SET vertical_id = requested_vertical_id,
                       available = TRUE,
                       enabled = FALSE,
                       previously_enabled = enabled,
                       availability_reasons = '[]'::JSONB,
                       package_version = requested_package_version,
                       image_digest = requested_image_digest,
                       asset_manifest_digest = requested_asset_manifest_digest,
                       semantic_profile_digest = requested_semantic_profile_digest,
                       revision = next_revision,
                       effective_at = occurred_at,
                       ontology_release_id = requested_ontology_release_id,
                       ontology_release_digest = requested_ontology_release_digest,
                       source_authority = 'protected-cost-governance-lifecycle',
                       updated_at = occurred_at,
                       source_revision = requested_source_revision,
                       wheel_digest = requested_wheel_digest,
                       runtime_config_digest = requested_runtime_config_digest
                 WHERE package_id = requested_package_id;
            END IF;

            INSERT INTO cost_governance_lifecycle_receipt (
                receipt_id, package_id, activation_revision, operation, outcome,
                receipt_digest, revision_pin_digest, evidence_kind, payload,
                evidence_refs, occurred_at, idempotency_key
            ) VALUES (
                receipt_id, requested_package_id, next_revision,
                requested_operation, 'succeeded',
                'sha256:' || repeat('0', 64), 'sha256:' || repeat('0', 64),
                'live-authoritative', '{}'::JSONB,
                requested_evidence_refs || jsonb_build_array(request_digest),
                occurred_at, request_id
            );
            INSERT INTO cost_governance_validation_retention (
                evidence_kind, evidence_id, revision, retention_until,
                purge_after, legal_hold, legal_hold_ref, purged_at, updated_at
            ) VALUES (
                'lifecycle-receipt', receipt_id, 1,
                occurred_at + INTERVAL '400 days',
                occurred_at + INTERVAL '430 days',
                FALSE, NULL, NULL, occurred_at
            );
            INSERT INTO cost_governance_validation_retention_event (
                evidence_kind, evidence_id, revision, event_kind,
                legal_hold_ref, recorded_at, idempotency_key
            ) VALUES (
                'lifecycle-receipt', receipt_id, 1, 'created',
                NULL, occurred_at, request_id
            );

            RETURN QUERY SELECT * FROM vertical_package_activation
                WHERE package_id = requested_package_id;
        END;
        $register$;
        REVOKE ALL ON FUNCTION fdai_register_cost_governance_release(
            TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
            TEXT, TEXT, BIGINT, TEXT, JSONB
        ) FROM PUBLIC;
        """
    )


def downgrade() -> None:
    """Remove the exact-release registration boundary after writers stop."""

    op.execute(
        """
        DROP FUNCTION fdai_set_cost_governance_enabled(
            TEXT, TEXT, BOOLEAN, BIGINT, TEXT
        );
        ALTER FUNCTION fdai_set_cost_governance_enabled_legacy(
            TEXT, TEXT, BOOLEAN, BIGINT, TEXT
        ) RENAME TO fdai_set_cost_governance_enabled;
        DROP FUNCTION fdai_register_cost_governance_release(
            TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
            TEXT, TEXT, BIGINT, TEXT, JSONB
        );
        DROP TRIGGER normalize_cost_governance_retention_revision
            ON cost_governance_validation_retention;
        DROP FUNCTION fdai_normalize_cost_governance_retention_revision();
        DROP TRIGGER canonicalize_cost_governance_lifecycle_receipt
            ON cost_governance_lifecycle_receipt;
        DROP FUNCTION fdai_canonicalize_cost_governance_lifecycle_receipt();
        DROP FUNCTION fdai_cost_governance_rfc3339(TIMESTAMPTZ);
        DROP FUNCTION fdai_cost_governance_canonical_json(JSONB);
        ALTER TABLE vertical_package_activation
            DROP CONSTRAINT vertical_package_activation_release_pin_check,
            DROP COLUMN runtime_config_digest,
            DROP COLUMN wheel_digest,
            DROP COLUMN source_revision;
        """
    )
