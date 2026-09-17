"""Grant Core bounded search over non-governed knowledge chunks."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_knowledge_read_20260917"
down_revision: str | Sequence[str] | None = "core_conversation_assurance_writer_20260917"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "drop-core-non-governed-knowledge-search",
    "restores": "core_conversation_assurance_writer_20260917",
    "requires": "core-runtime-stopped",
}


def upgrade() -> None:
    """Expose bounded non-governed search without granting raw table access."""
    op.execute(
        """
        CREATE FUNCTION fdai_search_core_knowledge(
            p_embedding vector,
            p_limit INTEGER
        ) RETURNS TABLE (
            doc_id TEXT,
            chunk_id TEXT,
            text TEXT,
            source_ref TEXT,
            metadata JSONB,
            score DOUBLE PRECISION
        ) LANGUAGE SQL STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $$
            SELECT chunk.doc_id,
                   chunk.chunk_id,
                   chunk.text,
                   chunk.source_ref,
                   chunk.metadata,
                   1.0 - (chunk.embedding <=> p_embedding)
            FROM public.knowledge_chunk AS chunk
            WHERE COALESCE(chunk.metadata->>'governed_document', 'false') <> 'true'
              AND p_limit BETWEEN 1 AND 20
            ORDER BY chunk.embedding <=> p_embedding ASC
            LIMIT p_limit
        $$;
        REVOKE ALL ON FUNCTION fdai_search_core_knowledge(vector, INTEGER) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_search_core_knowledge(vector, INTEGER) TO fdai_core;
        """
    )


def downgrade() -> None:
    """Remove Core's bounded non-governed knowledge search capability."""
    op.execute(
        """
        REVOKE ALL ON FUNCTION fdai_search_core_knowledge(vector, INTEGER) FROM fdai_core;
        DROP FUNCTION fdai_search_core_knowledge(vector, INTEGER);
        """
    )
