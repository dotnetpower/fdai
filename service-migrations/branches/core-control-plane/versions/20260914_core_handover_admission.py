"""Give Core one boolean-only source-bound document check, never document-table access."""

from __future__ import annotations

from alembic import op

revision = "core_handover_admission_20260914"
down_revision = "core_assignment_receipts_20260914"
branch_labels = None
depends_on = None
migration_owner = "core-control-plane"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-core-handover-document-check",
    "restores": "core_assignment_receipts_20260914",
    "requires": "handover-knowledge-consumers-stopped",
}


def upgrade() -> None:
    """Read only source-bound availability; document content and table privileges stay private."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fdai_verify_handover_source_document(
            p_goal_key TEXT, p_goal_revision BIGINT,
            p_document_id UUID, p_version_id UUID, p_digest TEXT
        ) RETURNS BOOLEAN
        LANGUAGE SQL STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT EXISTS (
                SELECT 1 FROM public.state_kv AS goal
                JOIN public.document_version AS version
                  ON version.document_id = p_document_id AND version.version_id = p_version_id
                WHERE goal.key = p_goal_key
                  AND (starts_with(goal.key, 'handover_goal:goal:')
                       OR starts_with(goal.key, 'operator-handover-goal:'))
                  AND goal.value -> 'revision' = to_jsonb(p_goal_revision)
                  AND goal.value ->> 'state' IN ('ready_for_review', 'accepted')
                  AND version.state IN ('ready', 'ready_with_warnings')
                  AND version.active
                  AND version.payload -> 'available' = 'true'::jsonb
                  AND version.payload ->> 'uploader_id' = goal.value ->> 'subject_ref'
                  AND version.payload ->> 'source_sha256' = p_digest
                  AND version.payload ->> 'disposition' = 'governed_knowledge'
                  AND version.payload ->> 'index_state' = 'active'
                  AND version.payload ->> 'retention_state' = 'live'
                  AND EXISTS (
                      SELECT 1 FROM jsonb_array_elements(
                          CASE WHEN jsonb_typeof(goal.value -> 'evidence') = 'array'
                               THEN goal.value -> 'evidence' ELSE '[]'::jsonb END
                      ) AS evidence
                      WHERE evidence ->> 'evidence_ref' =
                          'doc:' || p_document_id::text || ':' || p_version_id::text
                        AND evidence ->> 'digest' = p_digest
                  )
            )
        $$;
        REVOKE ALL ON FUNCTION fdai_verify_handover_source_document(
            TEXT, BIGINT, UUID, UUID, TEXT
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_verify_handover_source_document(
            TEXT, BIGINT, UUID, UUID, TEXT
        ) TO fdai_core;
        """
    )


def downgrade() -> None:
    """Remove only this read capability without deleting source, review, or audit history."""
    op.execute("DROP FUNCTION fdai_verify_handover_source_document(TEXT, BIGINT, UUID, UUID, TEXT)")
