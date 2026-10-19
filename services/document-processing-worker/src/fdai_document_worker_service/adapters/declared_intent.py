"""Persist explicit machine-authored intent envelopes for Core's governed proposal path."""

from __future__ import annotations

import json

import psycopg
from fdai_service_contracts import DocumentEnvelope, DocumentPurpose, UploadSession
from fdai_service_contracts.document_intent import IntentServiceProperties
from fdai_service_contracts.ontology_query import content_digest
from psycopg.types.json import Jsonb

_KIND = "fdai.declared-intent.business-service.v1"


class PostgresDeclaredIntentEnvelopeConsumer:
    """Stage exact envelope bytes; no review, graph write, or action authority."""

    purpose = DocumentPurpose.MANUAL_DISTILLATION

    def __init__(self, *, dsn: str) -> None:
        self._dsn = dsn

    async def consume(
        self, *, session: UploadSession, envelope: DocumentEnvelope
    ) -> tuple[str, ...]:
        if len(envelope.units) != 1:
            return ()
        try:
            payload = json.loads(envelope.units[0].text)
        except json.JSONDecodeError:
            return ()
        if not isinstance(payload, dict) or payload.get("kind") != _KIND:
            return ()
        if set(payload) != {"kind", "properties"}:
            raise ValueError("declared intent payload contains unsupported fields")
        IntentServiceProperties.model_validate(payload["properties"])
        if envelope.artifact_manifest is None:
            raise ValueError("declared intent envelope requires an artifact manifest")
        digest = content_digest(envelope.model_dump(mode="json"))
        async with await psycopg.AsyncConnection.connect(self._dsn) as connection:
            await connection.execute(
                "INSERT INTO document_intent_envelope"
                "(document_id,version_id,envelope,envelope_digest,source_sha256) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    envelope.document_id,
                    envelope.version_id,
                    Jsonb(envelope.model_dump(mode="json")),
                    digest,
                    envelope.source_sha256,
                ),
            )
            row = await (
                await connection.execute(
                    "SELECT envelope_digest,source_sha256 FROM document_intent_envelope "
                    "WHERE document_id=%s AND version_id=%s",
                    (envelope.document_id, envelope.version_id),
                )
            ).fetchone()
            if row is None or row[0] != digest or row[1] != envelope.source_sha256:
                raise ValueError("declared intent envelope replay conflicts")
        return ()


__all__ = ["PostgresDeclaredIntentEnvelopeConsumer"]
