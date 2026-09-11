"""Production PostgreSQL safeguard-bundle resolver tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Self
from uuid import UUID

import psycopg
import pytest
from fdai_executor_service.adapters.postgres_safeguard_bundle import (
    PostgresSafeguardBundleStore,
    PostgresSafeguardBundleStoreConfig,
)
from fdai_service_contracts.execution_safeguards import (
    SafeguardProof,
    SafeguardProofBundle,
    SafeguardProofKind,
)
from fdai_service_contracts.executor_models import ExecutionPath

_MIGRATION = (
    Path(__file__).resolve().parents[3] / "service-migrations/branches/isolated-executor/versions/"
    "20260912_executor_safeguard_bundle_read.py"
)


class _Cursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, object]]:
        return self._rows


class _Connection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.calls: list[tuple[str, object]] = []

    async def execute(self, sql: str, params: object = None) -> _Cursor:
        self.calls.append((sql, params))
        return _Cursor(self._rows if "FROM safeguard_dispatch_evidence" in sql else [])

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


def _bundle() -> SafeguardProofBundle:
    return SafeguardProofBundle.create(
        action_id=UUID(int=1),
        execution_path=ExecutionPath.DIRECT_API,
        execution_fingerprint="sha256:" + "a" * 64,
        source_revision="commit:" + "b" * 40,
        recorded_at=datetime(2026, 9, 11, tzinfo=UTC),
        proofs=tuple(
            SafeguardProof(
                kind=kind,
                proof_digest="sha256:" + f"{index:x}" * 64,
            )
            for index, kind in enumerate(SafeguardProofKind, start=1)
        ),
    )


def test_bundle_lookup_index_matches_runtime_json_path() -> None:
    migration = _MIGRATION.read_text(encoding="utf-8")

    assert "record #>> '{bundle,bundle_digest}'" in migration
    assert "record #>> '{{bundle,bundle_digest}}'" not in migration
    assert '"revision": "core_safeguard_dispatch_evidence_20260911"' in migration


async def test_postgres_bundle_store_reads_exact_core_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle()
    connection = _Connection([{"record": {"bundle": bundle.model_dump(mode="json")}}])

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresSafeguardBundleStore(
        config=PostgresSafeguardBundleStoreConfig(dsn="postgresql://example")
    )

    resolved = await store.resolve_bundle(bundle.bundle_digest)

    assert resolved == bundle
    query = next(sql for sql, _params in connection.calls if "FROM" in sql)
    assert "LIMIT 2" in query


async def test_postgres_bundle_store_rejects_ambiguous_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle()
    row = {"record": {"bundle": bundle.model_dump(mode="json")}}
    connection = _Connection([row, row])

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresSafeguardBundleStore(
        config=PostgresSafeguardBundleStoreConfig(dsn="postgresql://example")
    )

    with pytest.raises(RuntimeError, match="multiple generations"):
        await store.resolve_bundle(bundle.bundle_digest)
