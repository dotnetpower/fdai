"""Read-only, independently connected verification of sealed cloud index effects."""

from __future__ import annotations

from typing import Any

import psycopg
from fdai_service_contracts import DocumentEnvelope, DocumentVersion
from fdai_service_contracts.cloud_knowledge import CloudSourceEvidence, content_digest
from psycopg import IsolationLevel
from psycopg.rows import dict_row

INDEX_DIGEST_SQL = """
SELECT encode(sha256(convert_to(COALESCE(string_agg(
    jsonb_build_array(chunk_id, doc_id, text, source_ref, embedding::text, metadata)::text,
    E'\\n' ORDER BY chunk_id), ''), 'UTF8')), 'hex') AS digest
FROM knowledge_chunk WHERE doc_id = %s
"""


async def observed_index_digest(
    connection: psycopg.AsyncConnection[dict[str, Any]], document_ref: str
) -> str:
    """Hash the complete persisted row set, including visibility and provenance, in one snapshot."""
    row = await (await connection.execute(INDEX_DIGEST_SQL, (document_ref,))).fetchone()
    if row is None or not isinstance(row["digest"], str):
        raise ValueError("knowledge index digest is unavailable")
    return row["digest"]


class PostgresCloudIndexVerifier:
    """Compare every stored row to sealed inputs using a separate read-only transaction."""

    def __init__(self, *, dsn: str) -> None:
        self._dsn = dsn

    async def verify(self, version: DocumentVersion, envelope: DocumentEnvelope) -> str:
        """Return exact observed bytes' digest; callers must fence it again before visibility."""
        binding = version.cloud_knowledge
        if binding is None or envelope.cloud_knowledge != binding or not envelope.units:
            raise ValueError("knowledge readback requires bound source units")
        doc_id = f"governed:{version.document_id}:{version.version_id}"
        expected = {f"{doc_id}:{unit.unit_id}:0": unit for unit in envelope.units}
        if len(expected) != len(envelope.units):
            raise ValueError("knowledge source units are not unique")
        async with await psycopg.AsyncConnection.connect(
            self._dsn, row_factory=dict_row, connect_timeout=10
        ) as connection:
            await connection.set_isolation_level(IsolationLevel.REPEATABLE_READ)
            await connection.set_read_only(True)
            await connection.execute("SET LOCAL statement_timeout = '10s'")
            active = await (
                await connection.execute(
                    "SELECT payload FROM document_version WHERE document_id = %s AND active",
                    (version.document_id,),
                )
            ).fetchall()
            if len(active) != 1 or DocumentVersion.model_validate(active[0]["payload"]) != version:
                raise ValueError("knowledge active generation changed before readback")
            rows = await (
                await connection.execute(
                    "SELECT chunk_id, text, source_ref, embedding IS NULL AS lexical, metadata "
                    "FROM knowledge_chunk WHERE doc_id = %s ORDER BY chunk_id LIMIT %s",
                    (doc_id, len(expected) + 1),
                )
            ).fetchall()
            if len(rows) != len(expected):
                raise ValueError("knowledge readback row count does not match its source")
            for row in rows:
                unit = expected.get(row["chunk_id"])
                metadata = row["metadata"]
                if unit is None or not isinstance(metadata, dict):
                    raise ValueError("knowledge index contains an unbound row")
                source = next(
                    (
                        item
                        for item in binding.sources
                        if unit.locator.startswith(
                            f"cloud:{content_digest(item.source_id.encode())[:16]}:"
                        )
                    ),
                    None,
                )
                if (
                    source is None
                    or row["text"] != unit.text
                    or row["source_ref"]
                    != (
                        f"document://{version.document_id}/versions/"
                        f"{version.version_id}#{unit.unit_id}"
                    )
                    or row["lexical"] is not True
                    or metadata.get("governed_document") != "true"
                    or metadata.get("document_id") != str(version.document_id)
                    or metadata.get("version_id") != str(version.version_id)
                    or metadata.get("collection_id") != version.access.collection_id
                    or metadata.get("access_descriptor_ref") != version.access.reference
                    or metadata.get("locator") != unit.locator
                    or metadata.get("cloud_manifest_digest") != binding.manifest_digest
                    or metadata.get("cloud_registry_digest") != binding.registry_digest
                    or metadata.get("cloud_admission_expires_at")
                    != binding.admission_expires_at.isoformat()
                    or metadata.get("retention_state") != "verifying"
                    or metadata.get("retrieval_mode") != "lexical"
                    or not isinstance(metadata.get("cloud_source"), str)
                    or CloudSourceEvidence.model_validate_json(metadata.get("cloud_source", ""))
                    != source
                ):
                    raise ValueError("knowledge readback differs from its approved input")
            return await observed_index_digest(connection, doc_id)
