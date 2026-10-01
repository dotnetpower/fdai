from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.recent_resource_change_continuations import (
    ContinuationBinding,
    ContinuationInvalidError,
    RecentResourceChangeContinuationIssuer,
)
from fdai.delivery.persistence.postgres_recent_resource_change_continuations import (
    PostgresRecentResourceChangeContinuationStore,
    PostgresRecentResourceChangeContinuationStoreConfig,
)

NOW = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
DIGEST = "sha256:" + ("a" * 64)


@dataclass(frozen=True, slots=True)
class _Cursor:
    last_effective_at: datetime
    last_subject_ref: str


class _CursorResult:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, object] | None:
        return self._row


class _Connection:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.lock = asyncio.Lock()

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def execute(self, statement: str, params: tuple[object, ...] = ()) -> _CursorResult:
        if statement.startswith("INSERT"):
            value = params[1]
            self.values[str(params[0])] = value.obj
            return _CursorResult(None)
        if statement.startswith("SELECT set_config"):
            return _CursorResult(None)
        assert " ".join(statement.split()) == ("DELETE FROM state_kv WHERE key=%s RETURNING value")
        async with self.lock:
            value = self.values.pop(str(params[0]), None)
        return _CursorResult(None if value is None else {"value": value})


def _context() -> FunctionInvocationContext:
    return FunctionInvocationContext(
        caller_agent="Bragi",
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
    )


@pytest.mark.asyncio
async def test_postgres_store_claim_serializes_same_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()

    async def connect(*args: Any, **kwargs: Any) -> _Connection:
        del args, kwargs
        return connection

    from fdai.delivery.persistence import postgres_recent_resource_change_continuations as module

    monkeypatch.setattr(module.psycopg.AsyncConnection, "connect", connect)
    store = PostgresRecentResourceChangeContinuationStore(
        config=PostgresRecentResourceChangeContinuationStoreConfig(dsn="postgresql://unused")
    )
    issuer = RecentResourceChangeContinuationIssuer(
        store=store,
        binding=ContinuationBinding(
            deployment_scope_digest=DIGEST,
            conversation_id="conversation-a",
            admitted_goal_digest=DIGEST,
            plan_digest=DIGEST,
            manifest_digest=DIGEST,
        ),
        clock=lambda: NOW,
    )
    continuation_ref = await issuer.issue(
        context=_context(),
        start_at=NOW - timedelta(days=1),
        end_at=NOW,
        known_at=NOW,
        query_version_digest=DIGEST,
        page_size=20,
        cursor=_Cursor(NOW - timedelta(minutes=1), "resource-020"),
        remaining_rows=1,
    )

    results = await asyncio.gather(
        *(
            issuer.request(
                continuation_ref=continuation_ref,
                context=_context(),
                page_size=20,
                query_version_digest=DIGEST,
            )
            for _ in range(2)
        ),
        return_exceptions=True,
    )

    assert sum(isinstance(result, ContinuationInvalidError) for result in results) == 1
    assert sum(not isinstance(result, Exception) for result in results) == 1
