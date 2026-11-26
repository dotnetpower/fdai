-- Migration Revision: core_knowledge_read_20260917
-- Down Revision: core_conversation_assurance_writer_20260917
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
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
