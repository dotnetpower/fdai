"""Grant Core bounded handover ACL booleans and exact-goal search, never raw document SELECT."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "core_handover_review_read_20260914"
down_revision = "core_handover_admission_20260914"
branch_labels = None
depends_on = None
migration_owner = "core-control-plane"
owned_tables = ("state_kv",)
rollback = {
    "strategy": "drop-core-handover-review-and-search-capabilities",
    "restores": "core_handover_admission_20260914",
    "requires": "core-handover-review-and-search-consumers-stopped",
}


def upgrade() -> None:
    """Keep document and chunk tables private; authenticate current human facts in Core."""
    op.execute(
        """
        CREATE FUNCTION fdai_guard_core_handover_state()
        RETURNS TRIGGER LANGUAGE plpgsql
        SET search_path = pg_catalog, public AS $guard$
        DECLARE original_key TEXT; updated_key TEXT;
        BEGIN
            original_key := CASE WHEN TG_OP = 'INSERT' THEN NEW.key ELSE OLD.key END;
            updated_key := CASE WHEN TG_OP = 'DELETE' THEN OLD.key ELSE NEW.key END;
            IF (starts_with(original_key, 'handover_goal:') OR
                starts_with(updated_key, 'handover_goal:')) AND current_user <> 'fdai_core' THEN
                RAISE EXCEPTION 'only Core may write its handover goals';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $guard$;
        CREATE TRIGGER core_handover_state_guard BEFORE INSERT OR DELETE OR UPDATE ON state_kv
            FOR EACH ROW EXECUTE FUNCTION fdai_guard_core_handover_state();

        CREATE FUNCTION fdai_verify_core_handover_document_access(
            p_subject TEXT, p_document UUID, p_version UUID, p_digest TEXT,
            p_reviewer TEXT, p_roles TEXT[], p_groups TEXT[]
        ) RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $$
            SELECT COALESCE(
                length(p_subject) BETWEEN 1 AND 256
                AND length(p_reviewer) BETWEEN 1 AND 256
                AND p_digest ~ '^[a-f0-9]{64}$'
                AND cardinality(p_roles) BETWEEN 1 AND 4
                AND p_roles <@ ARRAY['Reader', 'Contributor', 'Approver', 'Owner']
                AND cardinality(p_groups) BETWEEN 0 AND 500
                AND EXISTS (
                    SELECT 1 FROM public.document_version AS version
                    WHERE version.document_id = p_document AND version.version_id = p_version
                    AND version.active AND version.state IN ('ready', 'ready_with_warnings')
                    AND version.payload ->> 'uploader_id' = p_subject
                    AND version.payload ->> 'source_sha256' = p_digest
                    AND version.payload -> 'available' = 'true'::JSONB
                    AND version.payload ->> 'disposition' = 'governed_knowledge'
                    AND version.payload ->> 'index_state' = 'active'
                    AND version.payload ->> 'retention_state' = 'live'
                    AND (version.payload #>> '{retention,derived_expires_at}' IS NULL
                         OR (version.payload #>> '{retention,derived_expires_at}')::timestamptz
                            > NOW())
                    AND (p_reviewer = p_subject
                         OR p_roles && ARRAY['Contributor', 'Approver', 'Owner']
                         OR (jsonb_typeof(version.payload #> '{access,reader_groups}') = 'array'
                             AND (version.payload #> '{access,reader_groups}') ?| p_groups))
                ), FALSE)
        $$;
        REVOKE ALL ON FUNCTION fdai_verify_core_handover_document_access(
            TEXT, UUID, UUID, TEXT, TEXT, TEXT[], TEXT[]
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_verify_core_handover_document_access(
            TEXT, UUID, UUID, TEXT, TEXT, TEXT[], TEXT[]
        ) TO fdai_core;

        CREATE FUNCTION fdai_search_core_handover_goal(
            p_goal TEXT, p_revision BIGINT, p_subject TEXT, p_collection TEXT,
            p_access TEXT[], p_query TEXT, p_limit INTEGER
        ) RETURNS TABLE (
            doc_id TEXT, chunk_id TEXT, text TEXT, source_ref TEXT, metadata JSONB, score REAL
        ) LANGUAGE SQL STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $$
            SELECT chunk.doc_id, chunk.chunk_id, chunk.text, chunk.source_ref,
                   chunk.metadata || jsonb_build_object(
                       'goal_ref', p_goal,
                       'source_sha256', version.payload ->> 'source_sha256'),
                   ts_rank_cd(to_tsvector('simple', chunk.text),
                              websearch_to_tsquery('simple', p_query))
            FROM public.state_kv AS goal
            JOIN public.document_version AS version ON EXISTS (
                SELECT 1 FROM jsonb_array_elements(
                    CASE WHEN jsonb_typeof(goal.value -> 'evidence') = 'array'
                         THEN goal.value -> 'evidence' ELSE '[]'::jsonb END
                ) evidence WHERE evidence ->> 'evidence_ref' =
                    'doc:' || version.document_id::text || ':' || version.version_id::text
                  AND evidence ->> 'digest' = version.payload ->> 'source_sha256'
            )
            JOIN public.knowledge_chunk AS chunk
              ON chunk.metadata ->> 'document_id' = version.document_id::text
             AND chunk.metadata ->> 'version_id' = version.version_id::text
            WHERE goal.key = 'handover_goal:goal:' || p_goal
              AND goal.value -> 'revision' = to_jsonb(p_revision)
              AND goal.value ->> 'subject_ref' = p_subject
              AND goal.value ->> 'state' IN ('ready_for_review', 'accepted')
              AND length(p_query) BETWEEN 1 AND 20000 AND p_limit BETWEEN 1 AND 20
              AND cardinality(p_access) BETWEEN 1 AND 100
              AND public.fdai_verify_handover_source_document(
                  goal.key, p_revision, version.document_id, version.version_id,
                  version.payload ->> 'source_sha256')
              AND public.fdai_verify_core_handover_document_access(
                  p_subject, version.document_id, version.version_id,
                  version.payload ->> 'source_sha256', p_subject, ARRAY['Reader'], ARRAY[]::TEXT[])
              AND version.payload #>> '{access,collection_id}' = p_collection
              AND version.payload #>> '{access,reference}' = ANY(p_access)
              AND chunk.metadata ->> 'collection_id' = p_collection
                            AND chunk.metadata ->> 'access_descriptor_ref'
                                        = version.payload #>> '{access,reference}'
              AND chunk.metadata ->> 'governed_document' = 'true'
              AND chunk.metadata ->> 'retention_state' = 'live'
                            AND (chunk.metadata ->> 'expires_at' IS NULL
                                     OR (chunk.metadata ->> 'expires_at')::timestamptz > NOW())
                            AND chunk.doc_id = 'governed:' || version.document_id::text
                                                                || ':' || version.version_id::text
              AND octet_length(chunk.text) BETWEEN 1 AND 8192
              AND to_tsvector('simple', chunk.text) @@ websearch_to_tsquery('simple', p_query)
            ORDER BY 6 DESC, chunk.chunk_id LIMIT p_limit
        $$;
        REVOKE ALL ON FUNCTION fdai_search_core_handover_goal(
            TEXT, BIGINT, TEXT, TEXT, TEXT[], TEXT, INTEGER
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_search_core_handover_goal(
            TEXT, BIGINT, TEXT, TEXT, TEXT[], TEXT, INTEGER
        ) TO fdai_core;

        CREATE FUNCTION fdai_core_handover_goal_access(
            p_goal TEXT, p_revision BIGINT, p_subject TEXT)
        RETURNS TABLE (collection_id TEXT, access_ref TEXT)
        LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
            SELECT DISTINCT version.payload #>> '{access,collection_id}',
                            version.payload #>> '{access,reference}'
            FROM public.state_kv AS goal
            JOIN public.document_version AS version ON EXISTS (
                SELECT 1 FROM jsonb_array_elements(
                    CASE WHEN jsonb_typeof(goal.value -> 'evidence') = 'array'
                         THEN goal.value -> 'evidence' ELSE '[]'::jsonb END
                ) evidence WHERE evidence ->> 'evidence_ref' =
                    'doc:' || version.document_id::text || ':' || version.version_id::text
                  AND evidence ->> 'digest' = version.payload ->> 'source_sha256'
            )
            WHERE goal.key = 'handover_goal:goal:' || p_goal
              AND goal.value -> 'revision' = to_jsonb(p_revision)
              AND goal.value ->> 'subject_ref' = p_subject
              AND goal.value ->> 'state' IN ('ready_for_review', 'accepted')
              AND public.fdai_verify_handover_source_document(
                  goal.key, p_revision, version.document_id, version.version_id,
                  version.payload ->> 'source_sha256')
              AND length(version.payload #>> '{access,collection_id}') BETWEEN 1 AND 256
              AND length(version.payload #>> '{access,reference}') BETWEEN 1 AND 512
            ORDER BY 1, 2 LIMIT 65
        $$;
        REVOKE ALL ON FUNCTION fdai_core_handover_goal_access(TEXT, BIGINT, TEXT) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_core_handover_goal_access(TEXT, BIGINT, TEXT) TO fdai_core;
        """
    )


def downgrade() -> None:
    """Revoke only read functions; preserve all document, goal, and review history."""
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE state_kv IN ACCESS EXCLUSIVE MODE"))
    if connection.execute(
        sa.text("SELECT count(*) FROM state_kv WHERE starts_with(key, 'handover_goal:')")
    ).scalar_one():
        raise RuntimeError("Core handover rollback must preserve its retained goal boundary")
    op.execute(
        """
        DROP FUNCTION fdai_core_handover_goal_access(TEXT, BIGINT, TEXT);
        DROP FUNCTION fdai_search_core_handover_goal(
            TEXT, BIGINT, TEXT, TEXT, TEXT[], TEXT, INTEGER);
        DROP FUNCTION fdai_verify_core_handover_document_access(
            TEXT, UUID, UUID, TEXT, TEXT, TEXT[], TEXT[]);
        DROP TRIGGER core_handover_state_guard ON state_kv;
        DROP FUNCTION fdai_guard_core_handover_state();
        """
    )
