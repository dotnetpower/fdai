from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.delivery.persistence.postgres_cost_governance_validation import (
    PostgresCostGovernanceValidationStore,
)


class _Cursor:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, object] | None:
        return self._row


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Connection:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row
        self.statements: list[str] = []

    def transaction(self) -> _Transaction:
        return _Transaction()

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, query: str, _params: object = None) -> _Cursor:
        self.statements.append(query)
        return _Cursor(self.row if "SELECT event_kind" in query else None)


@pytest.mark.asyncio
async def test_legal_hold_retry_replays_prior_matching_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = PostgresCostGovernanceValidationStore(dsn="postgresql://example.invalid/fdai")
    connection = _Connection({"event_kind": "hold-applied", "legal_hold_ref": "legal-hold:one"})

    async def connect() -> _Connection:
        return connection

    async def timeout(_connection: object) -> None:
        return None

    monkeypatch.setattr(store, "_connect", connect)
    monkeypatch.setattr(store, "_timeout", timeout)

    assert await store.set_validation_legal_hold(
        evidence_kind="campaign-episode",
        evidence_id="episode:one",
        expected_revision=1,
        legal_hold_ref="legal-hold:one",
        recorded_at=datetime(2026, 8, 28, tzinfo=UTC),
        idempotency_key="hold:one",
    )
    assert len(connection.statements) == 1


@pytest.mark.asyncio
async def test_legal_hold_retry_rejects_conflicting_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = PostgresCostGovernanceValidationStore(dsn="postgresql://example.invalid/fdai")
    connection = _Connection({"event_kind": "hold-released", "legal_hold_ref": None})

    async def connect() -> _Connection:
        return connection

    async def timeout(_connection: object) -> None:
        return None

    monkeypatch.setattr(store, "_connect", connect)
    monkeypatch.setattr(store, "_timeout", timeout)

    with pytest.raises(ValueError, match="idempotency key conflicts"):
        await store.set_validation_legal_hold(
            evidence_kind="campaign-episode",
            evidence_id="episode:one",
            expected_revision=1,
            legal_hold_ref="legal-hold:one",
            recorded_at=datetime(2026, 8, 28, tzinfo=UTC),
            idempotency_key="hold:one",
        )
