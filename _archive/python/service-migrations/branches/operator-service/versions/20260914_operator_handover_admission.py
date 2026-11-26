"""Expose strict source and reviewer admission without document-table access."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_handover_admission_20260914"
down_revision: str | Sequence[str] | None = "operator_assignment_receipts_20260914"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "drop-operator-handover-admission-functions",
    "restores": "operator_assignment_receipts_20260914",
    "requires": "operator-handover-runtime-stopped",
}


def upgrade() -> None:
    """Grant boolean reads only; the caller proves current reviewer identity and membership."""
    op.execute(
        """
        CREATE FUNCTION fdai_verify_handover_document_admission(
            p_principal_id TEXT, p_document_id UUID, p_version_id UUID, p_source_sha256 TEXT
        ) RETURNS BOOLEAN
        LANGUAGE SQL STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT EXISTS (
                SELECT 1 FROM public.document_version AS version
                 WHERE version.document_id = p_document_id
                   AND version.version_id = p_version_id
                   AND version.state IN ('ready', 'ready_with_warnings')
                   AND version.active
                   AND version.payload ->> 'uploader_id' = p_principal_id
                   AND version.payload ->> 'source_sha256' = p_source_sha256
                   AND version.payload -> 'available' = 'true'::JSONB
                   AND version.payload ->> 'disposition' = 'governed_knowledge'
                   AND version.payload ->> 'index_state' = 'active'
                   AND version.payload ->> 'retention_state' = 'live'
            )
        $$;
        REVOKE ALL ON FUNCTION fdai_verify_handover_document_admission(
            TEXT, UUID, UUID, TEXT
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_verify_handover_document_admission(
            TEXT, UUID, UUID, TEXT
        ) TO fdai_operator;

        CREATE FUNCTION fdai_verify_handover_document_review(
            p_principal_id TEXT, p_document_id UUID, p_version_id UUID, p_source_sha256 TEXT,
            p_reviewer_id TEXT, p_reviewer_roles TEXT[], p_reviewer_group_ids TEXT[]
        ) RETURNS BOOLEAN
        LANGUAGE SQL STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT COALESCE(
                public.fdai_verify_handover_document_admission(
                    p_principal_id, p_document_id, p_version_id, p_source_sha256
                )
                AND length(p_reviewer_id) BETWEEN 1 AND 256
                AND lower(p_reviewer_id) <> lower(p_principal_id)
                AND cardinality(p_reviewer_roles) BETWEEN 1 AND 5
                AND cardinality(p_reviewer_group_ids) BETWEEN 0 AND 500
                AND p_reviewer_roles && ARRAY['Reader', 'Contributor', 'Approver', 'Owner']
                AND (
                    p_reviewer_roles && ARRAY['Contributor', 'Approver', 'Owner']
                    OR EXISTS (
                        SELECT 1 FROM public.document_version AS version
                         WHERE version.document_id = p_document_id
                           AND version.version_id = p_version_id
                           AND jsonb_typeof(version.payload #> '{access,reader_groups}') = 'array'
                           AND (version.payload #> '{access,reader_groups}') ?| p_reviewer_group_ids
                    )
                ), FALSE
            )
        $$;
        REVOKE ALL ON FUNCTION fdai_verify_handover_document_review(
            TEXT, UUID, UUID, TEXT, TEXT, TEXT[], TEXT[]
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_verify_handover_document_review(
            TEXT, UUID, UUID, TEXT, TEXT, TEXT[], TEXT[]
        ) TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove the new booleans; newer application code then holds on an absent reader."""
    op.execute(
        """
        DROP FUNCTION fdai_verify_handover_document_review(
            TEXT, UUID, UUID, TEXT, TEXT, TEXT[], TEXT[]
        );
        DROP FUNCTION fdai_verify_handover_document_admission(TEXT, UUID, UUID, TEXT);
        """
    )
