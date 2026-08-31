"""Atomicity tests for guarded workflow transition proposal persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import psycopg
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)
from fdai_service_contracts import OperatorRole

NOW = datetime(2026, 8, 31, tzinfo=UTC)


class _Cursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    async def fetchone(self) -> dict[str, object] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, object]]:
        return self.rows


class _Transaction:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> None:
        self.connection.in_transaction = True

    async def __aexit__(self, *args: object) -> None:
        self.connection.in_transaction = False


class _Connection:
    def __init__(self, existing: dict[str, object] | None = None) -> None:
        self.existing = existing
        self.inserted: dict[str, object] | None = None
        self.statements: list[str] = []
        self.in_transaction = False

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    async def execute(
        self,
        statement: str,
        parameters: tuple[object, ...],
    ) -> _Cursor:
        assert self.in_transaction
        normalized = " ".join(statement.split())
        self.statements.append(normalized)
        if "set_config" in statement:
            return _Cursor([])
        if "SELECT value FROM state_kv" in statement and "FOR UPDATE" in statement:
            return _Cursor([] if self.existing is None else [{"value": self.existing}])
        if "FROM process_runtime AS runtime" in statement:
            assert "FOR SHARE OF runtime" in statement
            return _Cursor([_process()])
        if "FROM process_event" in statement:
            return _Cursor(_events())
        if "workflow.catalog" in str(parameters):
            return _Cursor([{"value": _catalog()}])
        if "INSERT INTO state_kv" in statement:
            self.inserted = json.loads(str(parameters[1]))
            return _Cursor([{"value": self.inserted}])
        raise AssertionError(f"unexpected SQL: {normalized}")


def _process() -> dict[str, object]:
    return {
        "process_id": "process-1",
        "workflow_ref": "review-workflow",
        "workflow_version": "1.0.0",
        "status": "waiting",
        "current_step": "gate",
        "target_resource_id": "resource-1",
        "started_at": NOW,
        "updated_at": NOW,
        "correlation_id": "correlation-1",
        "revision": 3,
    }


def _events() -> list[dict[str, object]]:
    return [
        {
            "kind": "process.created",
            "step_id": None,
            "attempt": 1,
            "payload": {
                "resume": {
                    "mode": "shadow",
                    "context": {"requester.principal": "operator-a"},
                }
            },
        },
        {
            "kind": "step.waiting",
            "step_id": "gate",
            "attempt": 1,
            "payload": {"step_kind": "gate", "reason": "waiting_for_gate_evaluation"},
        },
    ]


def _catalog() -> dict[str, object]:
    return {
        "_revision": "catalog-7",
        "workflows": [
            {
                "name": "review-workflow",
                "version": "1.0.0",
                "steps": [
                    {
                        "id": "gate",
                        "kind": "gate",
                        "gate_ref": "release.production-ready",
                    }
                ],
            }
        ],
    }


async def test_guard_and_insert_share_one_process_revision_lock(
    monkeypatch: Any,
) -> None:
    first = _Connection()
    second = _Connection()
    connections = iter((first, second))

    async def connect(*args: object, **kwargs: object) -> _Connection:
        del args, kwargs
        connection = next(connections)
        if connection is second:
            connection.existing = first.inserted
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))
    kwargs = {
        "operation": "workflow.cancel-request",
        "process_id": "process-1",
        "principal_id": "operator-a",
        "principal_roles": frozenset({OperatorRole.CONTRIBUTOR}),
        "idempotency_key": "cancel-3",
        "expected_revision": "3",
        "proposal_payload": {"mode": "shadow"},
    }

    accepted = await store.append_guarded_workflow_transition_proposal(**kwargs)
    replayed = await store.append_guarded_workflow_transition_proposal(**kwargs)

    assert accepted.duplicate is False
    assert replayed.duplicate is True
    assert accepted.proposal_id == replayed.proposal_id
    first_sql = "\n".join(first.statements)
    assert first_sql.index("FOR SHARE OF runtime") < first_sql.index("INSERT INTO state_kv")
    assert not any("process_runtime" in statement for statement in second.statements)
