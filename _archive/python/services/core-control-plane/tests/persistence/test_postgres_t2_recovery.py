from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import fdai.delivery.persistence.postgres_t2_recovery as subject
import pytest
from fdai.delivery.persistence.postgres import PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_t2_recovery import PostgresT2RecoveryLegacyReader


class _AsyncContext:
    def __init__(self, value: Any) -> None:
        self.value = value

    async def __aenter__(self) -> Any:
        return self.value

    async def __aexit__(self, *args: object) -> None:
        return None


class _Cursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    async def fetchall(self) -> list[dict[str, object]]:
        return self.rows


class _Connection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def transaction(self) -> _AsyncContext:
        return _AsyncContext(None)

    async def execute(self, query: str, params: tuple[object, ...]) -> _Cursor:
        self.queries.append((query, params))
        return _Cursor(self.rows)


async def test_reads_only_sanitized_legacy_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _Connection(
        [
            {
                "event_id": "event-1",
                "correlation_id": None,
                "t2_reason": "t2_proposer_error:DeploymentNotFound",
                "recorded_at": "2026-08-13T00:00:00+00:00",
                "provider_error": "must-not-leak",
            }
        ]
    )
    connect_args: dict[str, object] = {}

    async def _connect(dsn: str, **kwargs: object) -> _Connection:
        connect_args.update({"dsn": dsn, **kwargs})
        return connection

    monkeypatch.setattr(
        subject,
        "psycopg",
        SimpleNamespace(AsyncConnection=SimpleNamespace(connect=_connect)),
    )
    reader = PostgresT2RecoveryLegacyReader(
        config=PostgresStateStoreConfig(
            dsn="postgresql://example.invalid/fdai",
            connect_timeout_s=3,
            statement_timeout_ms=500,
        )
    )

    rows = await reader.read_failures(limit=25)

    assert rows == (
        {
            "event_id": "event-1",
            "correlation_id": "event-1",
            "t2_reason": "t2_proposer_error:DeploymentNotFound",
            "recorded_at": "2026-08-13T00:00:00+00:00",
        },
    )
    assert connect_args["dsn"] == "postgresql://example.invalid/fdai"
    assert connect_args["connect_timeout"] == 3
    assert connection.queries[0] == (
        "SELECT set_config('statement_timeout', %s, true)",
        ("500",),
    )
    query, params = connection.queries[1]
    assert "action_kind = 'control_loop.t2_evaluate'" in query
    assert "entry->>'t2_reason' LIKE %s" in query
    assert "provider_error" not in query
    assert params == ("t2_proposer_error:%", 25)


@pytest.mark.parametrize("limit", [0, 1_001])
async def test_rejects_unbounded_legacy_reads(limit: int) -> None:
    reader = PostgresT2RecoveryLegacyReader(
        config=PostgresStateStoreConfig(dsn="postgresql://example.invalid/fdai")
    )

    with pytest.raises(ValueError, match=r"\[1, 1000\]"):
        await reader.read_failures(limit=limit)
