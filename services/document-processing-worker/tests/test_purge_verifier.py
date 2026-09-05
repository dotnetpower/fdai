"""Focused tests for authoritative document purge verification."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import UUID

import psycopg
from fdai_document_worker_service.purge import PostgresDocumentPurgeVerifier
from pytest import MonkeyPatch


class _Cursor:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self._row = row

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _Connection:
    def __init__(self, upload_id: UUID) -> None:
        self._upload_id = upload_id

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def execute(
        self,
        query: str,
        params: Sequence[object],
    ) -> _Cursor:
        del params
        if "FROM knowledge_chunk" in query:
            return _Cursor((0,))
        if "FROM document_version" in query:
            assert "legal_hold')::boolean, FALSE" in query
            return _Cursor((self._upload_id, False))
        if "FROM document_worker_claim" in query:
            return _Cursor(None)
        raise AssertionError(f"unexpected query: {query}")


class _AsyncConnection:
    connection: _Connection

    @classmethod
    async def connect(cls, dsn: str) -> _Connection:
        assert dsn == "postgresql://local"
        return cls.connection


class _ArtifactProbe:
    async def artifact_exists(self, document_id: UUID, version_id: UUID) -> bool:
        del document_id, version_id
        return False


class _SourceProbe:
    async def source_exists(self, object_key: str) -> bool:
        del object_key
        return False


async def test_missing_legacy_legal_hold_defaults_to_not_blocked(
    monkeypatch: MonkeyPatch,
) -> None:
    upload_id = UUID(int=1)
    document_id = UUID(int=2)
    version_id = UUID(int=3)
    _AsyncConnection.connection = _Connection(upload_id)
    monkeypatch.setattr(psycopg, "AsyncConnection", _AsyncConnection)
    verifier = PostgresDocumentPurgeVerifier(
        dsn="postgresql://local",
        artifacts=_ArtifactProbe(),
        sources=_SourceProbe(),
        clock=lambda: datetime(2026, 9, 5, tzinfo=UTC),
    )

    receipt = await verifier.verify(
        document_id=document_id,
        version_id=version_id,
        source_object_keys=("source/object",),
    )

    assert receipt.legal_hold_blocked is False
    assert receipt.verified is True
