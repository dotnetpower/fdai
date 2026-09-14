"""Read-only source-check overlay; package arrival never renews source provenance."""

from __future__ import annotations

import os
import stat
from datetime import datetime

import psycopg
from fdai_service_contracts.cloud_knowledge import (
    CloudSourceEvidence,
    SourceRegistryRevision,
)
from fdai_service_contracts.cloud_knowledge_admission import validate_admitted_binding
from fdai_service_contracts.cloud_knowledge_package import KnowledgeTrustPolicy
from fdai_service_contracts.cloud_knowledge_release import KnowledgeReleaseBinding


class PostgresCloudKnowledgeRead:
    """Use independently installed source/trust policies, never client or chunk assertions."""

    def __init__(self, *, dsn: str, registry_path: str, trust_path: str) -> None:
        self._dsn = dsn
        self._registry_path = registry_path
        self._trust_path = trust_path

    async def resolve(
        self, binding: KnowledgeReleaseBinding, source_id: str, now: datetime
    ) -> tuple[CloudSourceEvidence, bool]:
        if not self._registry_path or not self._trust_path or now >= binding.admission_expires_at:
            raise ValueError("cloud reference admission is unavailable or expired")
        registry = SourceRegistryRevision.model_validate_json(_policy_bytes(self._registry_path))
        trust = KnowledgeTrustPolicy.model_validate_json(_policy_bytes(self._trust_path))
        validate_admitted_binding(binding, registry=registry, trust=trust, now=now)
        source = next((item for item in binding.sources if item.source_id == source_id), None)
        if source is None:
            raise ValueError("cloud reference source does not belong to the active release")
        async with await psycopg.AsyncConnection.connect(self._dsn, connect_timeout=5) as conn:
            await conn.execute("SET LOCAL statement_timeout = '5s'")
            row = await (
                await conn.execute(
                    "SELECT payload FROM document_knowledge_source "
                    "WHERE registry_digest = %s AND source_id = %s",
                    (binding.registry_digest, source_id),
                )
            ).fetchone()
        if row is None:
            return source, False
        cached = row[0].get("document")
        receipt = row[0].get("last_attempt")
        if cached is None or receipt is None:
            return source, False
        cached_evidence = CloudSourceEvidence.model_validate(cached["evidence"])
        observed = cached_evidence.check
        pending = cached_evidence.source_sha256 != source.source_sha256
        if (
            not pending
            and observed.content_sha256 == source.source_sha256
            and source.check.checked_at < observed.checked_at <= now
            and observed.source_id == source.source_id
            and observed.source_url == source.source_url
        ):
            source = CloudSourceEvidence.model_validate(
                source.model_dump()
                | {
                    "check": observed.model_dump(),
                }
            )
        return source, pending


def _policy_bytes(path: str) -> bytes:
    """Verify and read one bounded regular descriptor without following substituted links."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("cloud reference policy is unavailable")
        content = stream.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise ValueError("cloud reference policy exceeds its byte limit")
    return content
