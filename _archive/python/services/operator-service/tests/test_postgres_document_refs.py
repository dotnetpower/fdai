"""Tests for the grant-scoped PostgreSQL Web document resolver."""

from __future__ import annotations

from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID

import pytest
from fdai_operator_service.families.conversation.document_refs import (
    DocumentRef,
    DocumentRefAccessDeniedError,
)
from fdai_operator_service.families.conversation.postgres_document_refs import (
    PostgresDocumentContextResolver,
    PostgresDocumentContextResolverConfig,
)

NOW = datetime(2026, 9, 14, tzinfo=UTC)
DOCUMENT_ID = UUID(int=1)
VERSION_ID = UUID(int=2)


class _Cursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, object]]:
        return self._rows


class _Connection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.statements: list[tuple[str, object]] = []

    async def __aenter__(self):  # type: ignore[no-untyped-def]
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback

    async def set_isolation_level(self, _level: object) -> None:
        return None

    async def set_read_only(self, _value: bool) -> None:
        return None

    async def execute(self, statement: str, params: object) -> _Cursor:
        self.statements.append((statement, params))
        return _Cursor(self.rows)


def _row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ordinal": 1,
        "document_id": DOCUMENT_ID,
        "version_id": VERSION_ID,
        "revision": 4,
        "updated_at": NOW,
        "source_sha256": "a" * 64,
        "access_descriptor_ref": "access:operations",
    }
    row.update(updates)
    return row


async def _resolver(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, object]],
) -> tuple[PostgresDocumentContextResolver, _Connection]:
    connection = _Connection(rows)

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(
        "fdai_operator_service.families.conversation.postgres_document_refs."
        "psycopg.AsyncConnection.connect",
        connect,
    )
    return (
        PostgresDocumentContextResolver(
            PostgresDocumentContextResolverConfig(dsn="postgresql://example/fdai"),
            clock=lambda: NOW,
        ),
        connection,
    )


async def test_postgres_document_resolver_binds_current_ordered_attestation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver, connection = await _resolver(monkeypatch, [_row()])
    ref = DocumentRef(DOCUMENT_ID, VERSION_ID)

    result = await resolver.resolve_context(
        principal_id="principal-example",
        principal_groups=frozenset({"group:responders"}),
        refs=(ref,),
    )

    assert result.citations == (ref.citation,)
    assert result.authorization_digest.startswith("sha256:")
    query_statement, query_params = connection.statements[-1]
    assert "fdai_resolve_conversation_document_refs" in query_statement
    assert query_params[0] == "principal-example"
    assert query_params[1] == ["group:responders"]
    assert query_params[3] == NOW


@pytest.mark.parametrize(
    "rows",
    (
        [],
        [_row(ordinal=2)],
        [_row(document_id=UUID(int=9))],
    ),
    ids=("missing", "reordered", "substituted"),
)
async def test_postgres_document_resolver_returns_uniform_denial_for_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, object]],
) -> None:
    resolver, _connection = await _resolver(monkeypatch, rows)

    with pytest.raises(DocumentRefAccessDeniedError):
        await resolver.resolve_context(
            principal_id="principal-example",
            principal_groups=frozenset(),
            refs=(DocumentRef(DOCUMENT_ID, VERSION_ID),),
        )


@pytest.mark.parametrize(
    "source_sha256",
    ("short", "z" * 64, "A" * 64),
    ids=("short", "non-hex", "non-canonical"),
)
async def test_postgres_document_resolver_rejects_malformed_attestation(
    monkeypatch: pytest.MonkeyPatch,
    source_sha256: str,
) -> None:
    resolver, _connection = await _resolver(
        monkeypatch,
        [_row(source_sha256=source_sha256)],
    )

    with pytest.raises(RuntimeError, match="invalid attestation"):
        await resolver.resolve_context(
            principal_id="principal-example",
            principal_groups=frozenset(),
            refs=(DocumentRef(DOCUMENT_ID, VERSION_ID),),
        )
