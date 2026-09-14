"""Resolve exact Web document refs without granting Operator raw table reads."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg
from fdai_operator_service.families.conversation.document_refs import (
    DocumentRef,
    DocumentRefAccessDeniedError,
    ResolvedDocumentAuthorization,
)
from fdai_service_contracts import canonical_digest
from psycopg import IsolationLevel
from psycopg.rows import dict_row


@dataclass(frozen=True, slots=True)
class PostgresDocumentContextResolverConfig:
    """Bound the read-only document authorization call."""

    dsn: str
    statement_timeout_ms: int = 5_000
    connect_timeout_s: int = 5

    def __post_init__(self) -> None:
        if not self.dsn.strip():
            raise ValueError("document context resolver DSN MUST be non-empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("document context resolver timeouts MUST be positive")


class PostgresDocumentContextResolver:
    """Call one grant-scoped function and attest its exact ordered result."""

    def __init__(
        self,
        config: PostgresDocumentContextResolverConfig,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def resolve_context(
        self,
        *,
        principal_id: str,
        principal_groups: frozenset[str],
        refs: Sequence[DocumentRef],
    ) -> ResolvedDocumentAuthorization:
        if (
            not principal_id.strip()
            or len(principal_id) > 256
            or not 1 <= len(refs) <= 8
            or len(refs) != len({(ref.document_id, ref.version_id) for ref in refs})
            or any(not group.strip() or len(group) > 256 for group in principal_groups)
        ):
            raise ValueError("document context resolver inputs are invalid")
        observed_at = self._clock()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("document context resolver clock MUST be timezone-aware")
        requested = [
            {"document_id": str(ref.document_id), "version_id": str(ref.version_id)} for ref in refs
        ]
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
            options="",
        ) as connection:
            await connection.set_isolation_level(IsolationLevel.REPEATABLE_READ)
            await connection.set_read_only(True)
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._config.statement_timeout_ms),),
            )
            cursor = await connection.execute(
                """
                SELECT ordinal, document_id, version_id, revision, updated_at,
                       source_sha256, access_descriptor_ref
                  FROM fdai_resolve_conversation_document_refs(%s, %s, %s::jsonb, %s)
                 ORDER BY ordinal ASC
                """,
                (
                    principal_id,
                    sorted(principal_groups),
                    json.dumps(requested, sort_keys=True, separators=(",", ":")),
                    observed_at,
                ),
            )
            rows = await cursor.fetchall()
        if len(rows) != len(refs):
            raise DocumentRefAccessDeniedError()
        authorization_rows: list[dict[str, object]] = []
        citations: list[str] = []
        for ordinal, (ref, row) in enumerate(zip(refs, rows, strict=True), start=1):
            if (
                row.get("ordinal") != ordinal
                or str(row.get("document_id")) != str(ref.document_id)
                or str(row.get("version_id")) != str(ref.version_id)
            ):
                raise DocumentRefAccessDeniedError()
            revision = row.get("revision")
            updated_at = row.get("updated_at")
            source_sha256 = row.get("source_sha256")
            access_ref = row.get("access_descriptor_ref")
            if (
                not isinstance(revision, int)
                or isinstance(revision, bool)
                or revision < 1
                or not isinstance(updated_at, datetime)
                or updated_at.tzinfo is None
                or updated_at.utcoffset() is None
                or not isinstance(source_sha256, str)
                or len(source_sha256) != 64
                or any(character not in "0123456789abcdef" for character in source_sha256)
                or not isinstance(access_ref, str)
                or not access_ref.strip()
                or len(access_ref) > 512
            ):
                raise RuntimeError("document context resolver returned an invalid attestation")
            citations.append(ref.citation)
            authorization_rows.append(
                {
                    "ordinal": ordinal,
                    "document_id": str(ref.document_id),
                    "version_id": str(ref.version_id),
                    "revision": revision,
                    "updated_at": updated_at.astimezone(UTC).isoformat(),
                    "source_sha256": source_sha256,
                    "access_descriptor_ref": access_ref,
                }
            )
        return ResolvedDocumentAuthorization(
            citations=tuple(citations),
            authorization_digest=canonical_digest(
                {
                    "principal_id": principal_id,
                    "principal_groups": sorted(principal_groups),
                    "documents": authorization_rows,
                }
            ),
        )


def build_postgres_document_context_resolver(
    *,
    dsn: str,
    statement_timeout_ms: int,
    connect_timeout_s: int,
) -> PostgresDocumentContextResolver:
    """Build the family-owned exact document authorization resolver."""

    return PostgresDocumentContextResolver(
        PostgresDocumentContextResolverConfig(
            dsn=dsn,
            statement_timeout_ms=statement_timeout_ms,
            connect_timeout_s=connect_timeout_s,
        )
    )


__all__ = [
    "PostgresDocumentContextResolver",
    "PostgresDocumentContextResolverConfig",
    "build_postgres_document_context_resolver",
]
