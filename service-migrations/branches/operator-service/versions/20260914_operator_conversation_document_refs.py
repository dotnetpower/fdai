"""Expose bounded current document-reference authorization to Operator."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_conversation_document_refs_20260914"
down_revision: str | Sequence[str] | None = "operator_cost_disclosure_audit_20260912"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-operator-conversation-document-resolver",
    "restores": "operator_cost_disclosure_audit_20260912",
    "requires": "operator-conversation-document-resolution-stopped",
}


def upgrade() -> None:
    """Grant only a bounded authorization projection, never raw table reads."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE document_version FROM PUBLIC, fdai_operator;

        CREATE OR REPLACE FUNCTION fdai_resolve_conversation_document_refs(
            p_principal_id TEXT,
            p_principal_groups TEXT[],
            p_refs JSONB,
            p_observed_at TIMESTAMPTZ
        )
        RETURNS TABLE(
            ordinal INTEGER,
            document_id UUID,
            version_id UUID,
            revision BIGINT,
            updated_at TIMESTAMPTZ,
            source_sha256 TEXT,
            access_descriptor_ref TEXT
        )
        LANGUAGE SQL
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            WITH requested AS (
                SELECT item.ordinality::INTEGER AS ordinal,
                       (item.value ->> 'document_id')::UUID AS document_id,
                       (item.value ->> 'version_id')::UUID AS version_id
                  FROM jsonb_array_elements(
                           CASE
                               WHEN jsonb_typeof(p_refs) = 'array'
                                AND jsonb_array_length(p_refs) BETWEEN 1 AND 8
                               THEN p_refs
                               ELSE '[]'::JSONB
                           END
                       ) WITH ORDINALITY AS item(value, ordinality)
            )
            SELECT requested.ordinal,
                   version.document_id,
                   version.version_id,
                   version.revision,
                   version.updated_at,
                   version.payload ->> 'source_sha256',
                   version.payload #>> '{access,reference}'
              FROM requested
              JOIN public.document_version AS version
                ON version.document_id = requested.document_id
               AND version.version_id = requested.version_id
             WHERE version.state IN ('ready', 'ready_with_warnings')
               AND version.active
               AND COALESCE((version.payload ->> 'available')::BOOLEAN, FALSE)
               AND version.payload ->> 'disposition' = 'governed_knowledge'
               AND version.payload ->> 'index_state' = 'active'
               AND version.payload ->> 'retention_state' = 'live'
               AND version.payload ->> 'scope_kind' = 'collection'
               AND version.payload ->> 'scope_ref'
                   = version.payload #>> '{access,collection_id}'
               AND version.payload -> 'purposes' ? 'knowledge_base'
               AND (
                    version.payload #>> '{retention,derived_expires_at}' IS NULL
                    OR (version.payload #>> '{retention,derived_expires_at}')::TIMESTAMPTZ
                       > p_observed_at
               )
               AND (
                    version.payload ->> 'uploader_id' = p_principal_id
                    OR EXISTS (
                        SELECT 1
                          FROM jsonb_array_elements_text(
                                   COALESCE(
                                       version.payload #> '{access,reader_groups}',
                                       '[]'::JSONB
                                   )
                               ) AS reader_group(value)
                         WHERE reader_group.value = ANY(p_principal_groups)
                    )
               )
             ORDER BY requested.ordinal ASC
        $$;

        REVOKE ALL ON FUNCTION fdai_resolve_conversation_document_refs(
            TEXT, TEXT[], JSONB, TIMESTAMPTZ
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_resolve_conversation_document_refs(
            TEXT, TEXT[], JSONB, TIMESTAMPTZ
        ) TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove the bounded resolver without changing document ownership."""

    op.execute(
        """
        REVOKE EXECUTE ON FUNCTION fdai_resolve_conversation_document_refs(
            TEXT, TEXT[], JSONB, TIMESTAMPTZ
        ) FROM fdai_operator;
        DROP FUNCTION fdai_resolve_conversation_document_refs(
            TEXT, TEXT[], JSONB, TIMESTAMPTZ
        )
        """
    )
