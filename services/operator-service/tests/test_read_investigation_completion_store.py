"""Focused tests for the Operator read-investigation completion inbox."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fdai_operator_service.postgres_read_investigation_completion import (
    PostgresReadInvestigationCompletionConfig,
    PostgresReadInvestigationCompletionRepository,
    ReadInvestigationCompletionConflictError,
)
from fdai_service_contracts.read_investigation import (
    ReadInvestigationCompletion,
    ReadInvestigationCompletionUsage,
    ReadInvestigationOrigin,
    build_read_investigation_completion,
    read_investigation_task_id,
)


def _completion() -> ReadInvestigationCompletion:
    started_at = datetime(2026, 8, 24, tzinfo=UTC)
    return build_read_investigation_completion(
        task_id=read_investigation_task_id("principal-one", "idempotency-one"),
        attempt_id="attempt-one",
        attempt_number=1,
        owner_principal_id="principal-one",
        request_idempotency_key="idempotency-one",
        correlation_id="correlation-one",
        origin=ReadInvestigationOrigin(
            conversation_id="operator-request-one",
            channel_kind="web",
            channel_id="principal-one",
        ),
        status="succeeded",
        terminal_reason="completed",
        summary="Resource is healthy.",
        evidence_refs=("evidence-one",),
        usage=ReadInvestigationCompletionUsage(tool_calls=1),
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=2),
        completed_at=started_at + timedelta(seconds=3),
        retention_until=started_at + timedelta(days=30),
    )


def _database_url() -> str:
    value = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not value:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _stored(completion: ReadInvestigationCompletion) -> dict[str, object]:
    return {
        "kind": "operator.read_investigation_completion",
        "completion_id": completion.completion_id,
        "task_id": completion.task_id,
        "principal_id": completion.owner_principal_id,
        "completion_digest": completion.completion_digest,
        "stream": f"read-investigation:{completion.origin.conversation_id}",
        "event": "investigation.completed",
        "turn_id": f"turn:{completion.completion_id}",
        "data": completion.model_dump(mode="json"),
    }


async def test_project_binds_completion_to_exact_durable_request() -> None:
    completion = _completion()
    calls: list[tuple[str, Mapping[str, object]]] = []

    async def fetch_all(
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        calls.append((statement, parameters))
        return [
            {
                "sequence": 1,
                "event": "investigation.completed",
                "value": _stored(completion),
                "inserted": True,
            }
        ]

    stored = await PostgresReadInvestigationCompletionRepository(fetch_all=fetch_all).project(
        completion
    )

    assert stored.duplicate is False
    assert stored.completion_id == completion.completion_id
    assert stored.sequence == 1
    statement, parameters = calls[0]
    assert "value ->> 'kind' = 'operator.proposal'" in statement
    assert "value ->> 'operation' = 'read_investigation.start'" in statement
    assert "WHERE key = %(request_key)s" in statement
    assert "LIKE" not in statement
    assert "INSERT INTO conversation_turn" in statement
    assert "ELSE conversation_record.next_turn_index + 1" in statement
    assert "NOT EXISTS (SELECT 1 FROM existing_turn)" in statement
    assert "INSERT INTO operator_read_investigation_completion" in statement
    assert "turn_index" not in parameters
    assert parameters["request_key"] == (
        "operator-proposal:operations:" + hashlib.sha256(b"idempotency-one").hexdigest()
    )
    assert parameters["principal_id"] == "principal-one"
    assert parameters["request_idempotency_key"] == "idempotency-one"
    assert parameters["conversation_id"] == "operator-request-one"
    assert parameters["correlation_id"] == "correlation-one"
    assert parameters["channel_kind"] == "web"
    assert parameters["channel_id"] == "principal-one"
    assert isinstance(parameters["record"], str)


async def test_project_returns_exact_duplicate_without_second_identity() -> None:
    completion = _completion()

    async def fetch_all(
        _statement: str,
        _parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        return [
            {
                "sequence": 1,
                "event": "investigation.completed",
                "value": _stored(completion),
                "inserted": False,
            }
        ]

    stored = await PostgresReadInvestigationCompletionRepository(fetch_all=fetch_all).project(
        completion
    )

    assert stored.duplicate is True
    assert stored.task_id == completion.task_id


async def test_project_rejects_unmatched_request() -> None:
    async def fetch_all(
        _statement: str,
        _parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        return []

    with pytest.raises(ReadInvestigationCompletionConflictError, match="no matching"):
        await PostgresReadInvestigationCompletionRepository(fetch_all=fetch_all).project(
            _completion()
        )


async def test_project_rejects_conflicting_replay_digest() -> None:
    completion = _completion()
    conflict = _stored(completion)
    conflict["completion_digest"] = "sha256:" + "0" * 64

    async def fetch_all(
        _statement: str,
        _parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        return [
            {
                "sequence": 1,
                "event": "investigation.completed",
                "value": conflict,
                "inserted": False,
            }
        ]

    with pytest.raises(ReadInvestigationCompletionConflictError, match="conflicts"):
        await PostgresReadInvestigationCompletionRepository(fetch_all=fetch_all).project(completion)


async def test_project_maps_integrity_failure_to_bounded_conflict() -> None:
    async def fetch_all(
        _statement: str,
        _parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        raise psycopg.IntegrityError("deterministic unique conflict")

    with pytest.raises(ReadInvestigationCompletionConflictError, match="immutable"):
        await PostgresReadInvestigationCompletionRepository(fetch_all=fetch_all).project(
            _completion()
        )


@pytest.mark.integration
async def test_postgres_allocates_attempt_turns_and_reuses_duplicate_slot() -> None:
    dsn = _database_url()
    suffix = uuid.uuid4().hex
    principal_id = f"completion-principal-{suffix}"
    idempotency_key = f"completion-idempotency-{suffix}"
    proposal_id = f"operator-request-{suffix}"
    correlation_id = f"correlation-{suffix}"
    request_key = (
        "operator-proposal:operations:" + hashlib.sha256(idempotency_key.encode()).hexdigest()
    )
    proposal = {
        "kind": "operator.proposal",
        "family": "operations",
        "operation": "read_investigation.start",
        "principal_id": principal_id,
        "idempotency_key": idempotency_key,
        "proposal_id": proposal_id,
        "accepted_at": "2026-08-26T00:00:00+00:00",
        "payload": {"correlation_id": correlation_id},
    }
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        await connection.execute(
            "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb)",
            (request_key, json.dumps(proposal)),
        )
    repository = PostgresReadInvestigationCompletionRepository(
        config=PostgresReadInvestigationCompletionConfig(dsn=dsn)
    )
    started_at = datetime(2026, 8, 26, tzinfo=UTC)

    def completion(attempt: int, status: str) -> ReadInvestigationCompletion:
        return build_read_investigation_completion(
            task_id=read_investigation_task_id(principal_id, idempotency_key),
            attempt_id=f"interactive-{attempt}",
            attempt_number=attempt,
            owner_principal_id=principal_id,
            request_idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            origin=ReadInvestigationOrigin(
                conversation_id=proposal_id,
                channel_kind="web",
                channel_id=principal_id,
            ),
            status=status,  # type: ignore[arg-type]
            terminal_reason=status,
            summary=status,
            evidence_refs=(),
            usage=ReadInvestigationCompletionUsage(),
            started_at=started_at,
            finished_at=started_at,
            completed_at=started_at + timedelta(seconds=attempt),
            retention_until=started_at + timedelta(days=1),
        )

    first = completion(1, "failed")
    second = completion(2, "succeeded")
    await repository.project(first)
    await repository.project(second)
    duplicate = await repository.project(first)

    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        turn_cursor = await connection.execute(
            "SELECT turn_index FROM conversation_turn "
            "WHERE principal_id = %s AND conversation_id = %s ORDER BY turn_index",
            (principal_id, proposal_id),
        )
        turns = await turn_cursor.fetchall()
        conversation_cursor = await connection.execute(
            "SELECT next_turn_index FROM conversation_record "
            "WHERE principal_id = %s AND conversation_id = %s",
            (principal_id, proposal_id),
        )
        conversation = await conversation_cursor.fetchone()

    assert duplicate.duplicate is True
    assert [row[0] for row in turns] == [0, 1]
    assert conversation is not None and conversation[0] == 2
