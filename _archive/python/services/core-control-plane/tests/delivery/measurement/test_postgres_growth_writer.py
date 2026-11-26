"""Verify the growth-specific SQL preserves measurements and retention fences."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.core.tiers.t1_lightweight.contextual_reuse import OperationalCaseContext
from fdai.core.tiers.t1_lightweight.tier import LearnedAction
from fdai.delivery.measurement.postgres_growth_writer import PostgresShadowPatternWriter
from fdai.delivery.persistence.pgvector_pattern_library import (
    PgVectorPatternLibraryConfig,
    _retention_key,
)


class _Cursor:
    def __init__(self, *, row: Any = None, rowcount: int = 1) -> None:
        self.row = row
        self.rowcount = rowcount

    async def fetchone(self) -> Any:
        return self.row


class _Connection:
    def __init__(self) -> None:
        self.statements: list[tuple[str, Any]] = []
        self.rows: dict[str, tuple[Any, ...]] = {}
        self.blocked: str | None = None
        self.conflicting = False
        self.fail_after_write = False

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self.fail_after_write:
            self.fail_after_write = False
            raise RuntimeError("response lost after durable database commit")

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield

    async def execute(self, query: str, params: Any = None) -> _Cursor:
        self.statements.append((query, params))
        if "SELECT key FROM state_kv" in query:
            return _Cursor(row=(self.blocked,) if self.blocked in params[0] else None)
        if "INSERT INTO t1_pattern_library" in query:
            assert "historical_success_rate =" not in query
            assert "reuse_count =" not in query
            assert "SET signature = t1_pattern_library.signature" in query
            assert "IS NOT DISTINCT FROM EXCLUDED.operational_case" in query
            if self.conflicting:
                return _Cursor(rowcount=0)
            self.rows.setdefault(params[0], (*params, 0.0, 0))
        return _Cursor()


def _action() -> LearnedAction:
    return LearnedAction(
        signature="pattern-1",
        rule_id="rule-1",
        action_type="ops.scale-out",
        params={"replicas": 2},
        incident_id="incident-1",
        success_rate=0,
        reuse_count=0,
    )


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    connection: _Connection,
) -> PostgresShadowPatternWriter:
    async def connect(dsn: str, **kwargs: Any) -> _Connection:
        assert dsn == "postgresql://example/patterns"
        return connection

    monkeypatch.setattr(
        "fdai.delivery.measurement.postgres_growth_writer.psycopg.AsyncConnection.connect",
        connect,
    )
    return PostgresShadowPatternWriter(
        config=PgVectorPatternLibraryConfig(dsn="postgresql://example/patterns")
    )


async def test_growth_retry_preserves_existing_measured_statistics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    writer = _wire(monkeypatch, connection)
    await writer.upsert_pattern(vector=(0.1,) * 384, action=_action())
    original = connection.rows["pattern-1"]
    connection.rows["pattern-1"] = (*original[:-2], 0.97, 42)
    promoted = connection.rows["pattern-1"]
    await writer.upsert_pattern(
        vector=(0.9,) * 384,
        action=replace(_action(), incident_id="incident-2"),
    )
    assert connection.rows["pattern-1"] == promoted
    assert len(connection.rows) == 1
    sql = [query for query, _ in connection.statements]
    assert sql.index("SET TRANSACTION ISOLATION LEVEL READ COMMITTED") < next(
        index for index, query in enumerate(sql) if "INSERT INTO t1_pattern_library" in query
    )
    assert any("pg_advisory_xact_lock" in query for query in sql)


async def test_growth_refuses_retained_signature_deletion_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    connection.blocked = _retention_key("signature", "pattern-1")
    writer = _wire(monkeypatch, connection)
    with pytest.raises(PermissionError, match="pending deletion"):
        await writer.upsert_pattern(vector=(0.1,) * 384, action=_action())
    assert connection.rows == {}


async def test_growth_refuses_retained_source_case_deletion_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    connection.blocked = _retention_key("case", "case-1")
    writer = _wire(monkeypatch, connection)
    context = OperationalCaseContext(
        case_ref="case-history:case-1:1:" + "a" * 64,
        failure_fingerprint="b" * 64,
        resource_type="compute.vm",
        action_type="ops.scale-out",
        required_topology_role="service",
        graph_digest="c" * 64,
        owner_digest="d" * 64,
        evidence_cutoff=datetime(2026, 10, 16, tzinfo=UTC),
    )
    with pytest.raises(PermissionError, match="pending deletion"):
        await writer.upsert_pattern(
            vector=(0.1,) * 384,
            action=replace(_action(), operational_case=context),
        )
    assert connection.rows == {}


async def test_growth_refuses_source_identity_rebinding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    connection.conflicting = True
    writer = _wire(monkeypatch, connection)
    with pytest.raises(ValueError, match="source or action identity"):
        await writer.upsert_pattern(vector=(0.1,) * 384, action=_action())
    assert connection.rows == {}


async def test_retry_after_lost_write_response_does_not_reset_measurement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    connection.fail_after_write = True
    writer = _wire(monkeypatch, connection)
    with pytest.raises(RuntimeError, match="response lost"):
        await writer.upsert_pattern(vector=(0.1,) * 384, action=_action())
    previous = connection.rows["pattern-1"]
    connection.rows["pattern-1"] = (*previous[:-2], 0.95, 3)
    await writer.upsert_pattern(vector=(0.1,) * 384, action=_action())
    assert connection.rows["pattern-1"][-2:] == (0.95, 3)


@pytest.mark.parametrize("vector", [(0.1,), (float("nan"),) * 384])
async def test_growth_rejects_invalid_vectors_before_any_connection(
    monkeypatch: pytest.MonkeyPatch,
    vector: Sequence[float],
) -> None:
    connection = _Connection()
    writer = _wire(monkeypatch, connection)
    with pytest.raises(ValueError):
        await writer.upsert_pattern(vector=vector, action=_action())
    assert connection.statements == []


async def test_growth_writer_cannot_publish_non_shadow_statistics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    writer = _wire(monkeypatch, connection)
    with pytest.raises(ValueError, match="only new shadow statistics"):
        await writer.upsert_pattern(
            vector=(0.1,) * 384,
            action=replace(_action(), success_rate=0.99),
        )
    assert connection.statements == []
