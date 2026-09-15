"""Core-private inert semantic package claims and source-bound envelope metadata reads."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "core_handover_semantics_20260914"
down_revision = "core_handover_review_read_20260914"
branch_labels = None
depends_on = None
migration_owner = "core-control-plane"
owned_tables = ("handover_semantic_package",)
rollback = {
    "strategy": "drop-empty-private-semantic-package-store",
    "restores": "core_handover_review_read_20260914",
    "requires": "consumers-stopped-and-no-retained-semantic-attempts",
}


def upgrade() -> None:
    """Keep derived candidate bodies private; only content-free references enter common state."""
    op.execute(
        """
        CREATE TABLE handover_semantic_package (
            key TEXT PRIMARY KEY,
            identity JSONB NOT NULL CHECK (jsonb_typeof(identity) = 'object'),
            package JSONB CHECK (package IS NULL OR jsonb_typeof(package) = 'object'),
            retention_descriptor JSONB,
            receipt JSONB,
            retired_at TIMESTAMPTZ,
            checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (package IS NULL OR (retention_descriptor IS NOT NULL AND receipt IS NOT NULL))
        );
        REVOKE ALL ON TABLE handover_semantic_package FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE ON handover_semantic_package TO fdai_core;
        CREATE INDEX handover_semantic_source_check ON handover_semantic_package
            ((identity->>'source_id'), checked_at, key) WHERE package IS NOT NULL;

        CREATE FUNCTION fdai_core_handover_package_policy(p_key TEXT) RETURNS JSONB
        LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
            SELECT jsonb_build_object(
                'source_current', EXISTS (
                    SELECT 1 FROM public.state_kv AS goal
                    WHERE goal.key=p.retention_descriptor->>'source_key'
                      AND goal.value->>'revision'=p.retention_descriptor->>'source_revision'
                      AND goal.value->>'state'='accepted'
                ),
                'documents', (
                    SELECT jsonb_agg(jsonb_build_object(
                        'document_id', item.value->>'document_id',
                        'version_id', item.value->>'version_id',
                        'active', version.active, 'state', version.state,
                        'available', version.payload->'available',
                        'disposition', version.payload->'disposition',
                        'index_state', version.payload->'index_state',
                        'retention_state', version.payload->'retention_state',
                        'source_sha256', version.payload->'source_sha256',
                        'purposes', version.payload->'purposes',
                        'access', version.payload->'access',
                        'retention', version.payload->'retention'
                    ) ORDER BY item.ordinal)
                    FROM jsonb_array_elements(p.retention_descriptor->'documents')
                        WITH ORDINALITY AS item(value, ordinal)
                    LEFT JOIN public.document_version AS version
                      ON version.document_id::text=item.value->>'document_id'
                     AND version.version_id::text=item.value->>'version_id'
                )
            ) FROM public.handover_semantic_package AS p WHERE p.key=p_key
        $$;
        REVOKE ALL ON FUNCTION fdai_core_handover_package_policy(TEXT) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_core_handover_package_policy(TEXT) TO fdai_core;

        CREATE FUNCTION fdai_guard_handover_semantic_package() RETURNS TRIGGER
        LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
        DECLARE source_policy JSONB;
        BEGIN
            IF OLD.key <> NEW.key OR OLD.identity <> NEW.identity
               OR OLD.recorded_at <> NEW.recorded_at
               OR (OLD.retired_at IS NOT NULL AND NEW.retired_at IS DISTINCT FROM OLD.retired_at)
               OR (OLD.receipt IS NOT NULL AND (
                   NEW.receipt IS DISTINCT FROM OLD.receipt
                   OR NEW.retention_descriptor IS DISTINCT FROM OLD.retention_descriptor
                   OR (NEW.package IS DISTINCT FROM OLD.package AND NEW.package IS NOT NULL))) THEN
                RAISE EXCEPTION 'handover semantic attempts are immutable after completion';
            END IF;
            IF OLD.package IS NOT NULL AND NEW.package IS NULL THEN
                source_policy := public.fdai_core_handover_package_policy(OLD.key);
                IF NEW.retired_at IS NULL OR source_policy->'documents' IS NULL
                   OR jsonb_array_length(source_policy->'documents') NOT BETWEEN 1 AND 4
                   OR EXISTS (
                       SELECT 1 FROM jsonb_array_elements(source_policy->'documents') AS item
                       WHERE item #> '{retention,legal_hold}' IS DISTINCT FROM 'false'::jsonb
                   ) THEN
                    RAISE EXCEPTION 'semantic content scrub requires current no-hold source policy';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER handover_semantic_package_guard BEFORE UPDATE ON handover_semantic_package
            FOR EACH ROW EXECUTE FUNCTION fdai_guard_handover_semantic_package();

        CREATE FUNCTION fdai_core_handover_source_metadata(
            p_goal_key TEXT, p_revision BIGINT, p_document UUID, p_version UUID, p_digest TEXT
        ) RETURNS JSONB LANGUAGE SQL STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $$
            SELECT jsonb_build_object(
                'access', version.payload->'access',
                'retention', version.payload->'retention',
                'protection_state', version.payload->'protection_state',
                'purposes', version.payload->'purposes',
                'updated_at', version.payload->'updated_at'
            ) FROM public.document_version AS version
            WHERE version.document_id=p_document AND version.version_id=p_version
              AND public.fdai_verify_handover_source_document(
                    p_goal_key, p_revision, p_document, p_version, p_digest)
              AND version.payload->'purposes' @> '["manual_distillation"]'::jsonb
              AND (version.payload #>> '{retention,derived_expires_at}' IS NULL
                   OR (version.payload #>> '{retention,derived_expires_at}')::timestamptz > NOW())
        $$;
        REVOKE ALL ON FUNCTION fdai_core_handover_source_metadata(
            TEXT, BIGINT, UUID, UUID, TEXT) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_core_handover_source_metadata(
            TEXT, BIGINT, UUID, UUID, TEXT) TO fdai_core;
        """
    )


def downgrade() -> None:
    """Never delete retained attempt or audit evidence as a schema rollback shortcut."""
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE handover_semantic_package IN ACCESS EXCLUSIVE MODE"))
    if connection.execute(sa.text("SELECT count(*) FROM handover_semantic_package")).scalar_one():
        raise RuntimeError("semantic package rollback must preserve retained attempts")
    op.execute(
        """
        DROP FUNCTION fdai_core_handover_source_metadata(TEXT, BIGINT, UUID, UUID, TEXT);
        DROP FUNCTION fdai_core_handover_package_policy(TEXT);
        DROP TABLE handover_semantic_package;
        DROP FUNCTION fdai_guard_handover_semantic_package();
        """
    )
