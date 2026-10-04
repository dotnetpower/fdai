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
    ReadInvestigationCompletionRejectReason,
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


def _external_completion(
    *,
    channel_kind: str = "slack",
    channel_id: str = "channel-one",
    conversation_id: str = "conversation-one",
    attempt: int = 1,
) -> ReadInvestigationCompletion:
    started_at = datetime(2026, 8, 24, tzinfo=UTC)
    return build_read_investigation_completion(
        task_id=read_investigation_task_id("principal-one", "idempotency-one"),
        attempt_id=f"attempt-{attempt}",
        attempt_number=attempt,
        owner_principal_id="principal-one",
        request_idempotency_key="idempotency-one",
        correlation_id="correlation-one",
        origin=ReadInvestigationOrigin(
            conversation_id=conversation_id,
            channel_kind=channel_kind,
            channel_id=channel_id,
            thread_id="thread-one",
            message_id="message-one",
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
    if os.environ.get("FDAI_SERVICE_MIGRATIONS_READY") != "1":
        pytest.skip("service-owned migrations are not ready")
    value = os.environ.get("FDAI_SERVICE_DATABASE_URL", "").strip()
    if not value:
        pytest.skip("FDAI_SERVICE_DATABASE_URL is unset")
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


async def test_project_verified_slack_binding_enqueues_operator_outbound_once() -> None:
    completion = _external_completion()
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
                "reject_reason": None,
            }
        ]

    stored = await PostgresReadInvestigationCompletionRepository(fetch_all=fetch_all).project(
        completion
    )

    assert stored.duplicate is False
    statement, parameters = calls[0]
    assert "FROM principal_conversation_binding" in statement
    assert "state = 'active'" in statement
    assert "COUNT(*) FILTER (WHERE state = 'active')" in statement
    assert "INSERT INTO conversation_outbound_delivery" in statement
    assert "ON CONFLICT (idempotency_key) DO NOTHING" in statement
    assert "JOIN selected_binding" in statement
    assert "existing_completion AS" in statement
    assert "NOT EXISTS (SELECT 1 FROM existing_completion)" in statement
    assert "Slack" not in statement and "Teams" not in statement
    assert parameters["principal_id"] == "principal-one"
    assert parameters["channel_kind"] == "slack"
    assert parameters["channel_id"] == "channel-one"
    assert parameters["delivery_idempotency_key"]
    assert str(parameters["delivery_id"]).startswith("read-completion-delivery:")
    response = json.loads(str(parameters["response"]))
    assert response["answer"] == "[Background task result: completed]\nResource is healthy."
    assert response["execution_authority"] is False
    assert response["verification"]["evidence_refs"] == ["evidence-one"]


async def test_project_duplicate_external_enqueue_replays_without_duplication() -> None:
    first_completion = _external_completion(channel_kind="teams")
    duplicate_completion = _external_completion(channel_kind="teams")
    calls: list[Mapping[str, object]] = []

    async def fetch_all(
        _statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        calls.append(parameters)
        return [
            {
                "sequence": 1,
                "event": "investigation.completed",
                "value": _stored(first_completion),
                "inserted": len(calls) == 1,
                "reject_reason": None,
            }
        ]

    repository = PostgresReadInvestigationCompletionRepository(fetch_all=fetch_all)
    first = await repository.project(first_completion)
    duplicate = await repository.project(duplicate_completion)

    assert first.duplicate is False
    assert duplicate.duplicate is True
    assert calls[0]["delivery_id"] == calls[1]["delivery_id"]
    assert calls[0]["delivery_idempotency_key"] == calls[1]["delivery_idempotency_key"]


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("binding_unverified", ReadInvestigationCompletionRejectReason.BINDING_UNVERIFIED),
        ("binding_revoked", ReadInvestigationCompletionRejectReason.BINDING_REVOKED),
        ("binding_ambiguous", ReadInvestigationCompletionRejectReason.BINDING_AMBIGUOUS),
    ],
)
async def test_project_external_binding_rejections_are_typed(
    reason: str,
    expected: ReadInvestigationCompletionRejectReason,
) -> None:
    async def fetch_all(
        _statement: str,
        _parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        return [
            {
                "sequence": 0,
                "event": "",
                "value": {"reject_reason": reason},
                "inserted": False,
                "reject_reason": reason,
            }
        ]

    with pytest.raises(ReadInvestigationCompletionConflictError) as exc_info:
        await PostgresReadInvestigationCompletionRepository(fetch_all=fetch_all).project(
            _external_completion()
        )

    assert exc_info.value.reason is expected


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


async def test_purge_expired_completions_is_bounded_and_deadline_ordered() -> None:
    calls: list[tuple[str, Mapping[str, object]]] = []

    async def fetch_all(
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        calls.append((statement, parameters))
        return [{"completion_id": "read-completion-" + "a" * 32}]

    now = datetime(2026, 8, 29, tzinfo=UTC)
    deleted = await PostgresReadInvestigationCompletionRepository(
        fetch_all=fetch_all
    ).purge_expired_read_investigation_completions(now=now, limit=17)

    assert deleted == 1
    statement, parameters = calls[0]
    assert "retention_until <= %(now)s" in statement
    assert "ORDER BY retention_until, sequence" in statement
    assert "FOR UPDATE SKIP LOCKED" in statement
    assert "LIMIT %(limit)s" in statement
    assert "DELETE FROM operator_read_investigation_completion" in statement
    assert parameters == {"now": now, "limit": 17}


@pytest.mark.parametrize("limit", [0, 501])
async def test_purge_expired_completions_rejects_unbounded_batch(limit: int) -> None:
    async def fetch_all(
        _statement: str,
        _parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        raise AssertionError("invalid retention input MUST fail before PostgreSQL")

    repository = PostgresReadInvestigationCompletionRepository(fetch_all=fetch_all)
    with pytest.raises(ValueError, match="between 1 and 500"):
        await repository.purge_expired_read_investigation_completions(
            now=datetime(2026, 8, 29, tzinfo=UTC),
            limit=limit,
        )


async def test_purge_expired_completions_requires_aware_time() -> None:
    async def fetch_all(
        _statement: str,
        _parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        raise AssertionError("invalid retention input MUST fail before PostgreSQL")

    repository = PostgresReadInvestigationCompletionRepository(fetch_all=fetch_all)
    with pytest.raises(ValueError, match="timezone-aware"):
        await repository.purge_expired_read_investigation_completions(
            now=datetime(2026, 8, 29),
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


@pytest.mark.integration
async def test_postgres_external_completion_enqueue_replay_and_binding_rejections() -> None:
    dsn = _database_url()
    suffix = uuid.uuid4().hex
    started_at = datetime(2026, 8, 26, tzinfo=UTC)
    repository = PostgresReadInvestigationCompletionRepository(
        config=PostgresReadInvestigationCompletionConfig(dsn=dsn)
    )
    principals = {
        "verified": f"completion-external-verified-{suffix}",
        "revoked": f"completion-external-revoked-{suffix}",
        "unverified": f"completion-external-unverified-{suffix}",
    }
    idempotency_keys = {
        name: f"completion-external-idempotency-{name}-{suffix}" for name in principals
    }
    proposal_ids = {name: f"operator-request-{name}-{suffix}" for name in principals}
    correlation_ids = {name: f"correlation-{name}-{suffix}" for name in principals}
    channel_ids = {name: f"channel-{name}-{suffix}" for name in principals}
    binding_ids = {
        "verified": f"binding-verified-{suffix}",
        "revoked": f"binding-revoked-{suffix}",
    }

    def request_key(name: str) -> str:
        digest = hashlib.sha256(idempotency_keys[name].encode()).hexdigest()
        return f"operator-proposal:operations:{digest}"

    def proposal(name: str) -> dict[str, object]:
        return {
            "kind": "operator.proposal",
            "family": "operations",
            "operation": "read_investigation.start",
            "principal_id": principals[name],
            "idempotency_key": idempotency_keys[name],
            "proposal_id": proposal_ids[name],
            "accepted_at": "2026-08-26T00:00:00+00:00",
            "payload": {"correlation_id": correlation_ids[name]},
        }

    def completion(name: str) -> ReadInvestigationCompletion:
        return build_read_investigation_completion(
            task_id=read_investigation_task_id(principals[name], idempotency_keys[name]),
            attempt_id=f"interactive-{name}",
            attempt_number=1,
            owner_principal_id=principals[name],
            request_idempotency_key=idempotency_keys[name],
            correlation_id=correlation_ids[name],
            origin=ReadInvestigationOrigin(
                conversation_id=proposal_ids[name],
                channel_kind="slack",
                channel_id=channel_ids[name],
                thread_id=f"thread-{name}-{suffix}",
                message_id=f"message-{name}-{suffix}",
            ),
            status="succeeded",
            terminal_reason="completed",
            summary=f"{name} completion",
            evidence_refs=(f"evidence:{name}:{suffix}",),
            usage=ReadInvestigationCompletionUsage(),
            started_at=started_at,
            finished_at=started_at,
            completed_at=started_at + timedelta(seconds=1),
            retention_until=started_at + timedelta(days=1),
        )

    async def seed_proposal(connection: psycopg.AsyncConnection[object], name: str) -> None:
        await connection.execute(
            "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb)",
            (request_key(name), json.dumps(proposal(name))),
        )

    async def seed_binding(
        connection: psycopg.AsyncConnection[object],
        name: str,
        *,
        state: str,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO principal_conversation_binding (
                binding_id, principal_id, scope_ref, conversation_id, channel_kind,
                channel_id, sender_id, thread_id, verification_ref, verified_at,
                created_by, created_at, resumed_from_binding_id, state, revoked_by,
                revoked_at
            ) VALUES (
                %s, %s, %s, %s, 'slack', %s, %s, %s, %s, %s, 'operator-channel-edge',
                %s, NULL, %s, %s, %s
            )
            """,
            (
                binding_ids[name],
                principals[name],
                f"scope://completion/{name}/{suffix}",
                proposal_ids[name],
                channel_ids[name],
                f"sender-{name}-{suffix}",
                f"thread-{name}-{suffix}",
                f"verification-{name}-{suffix}",
                started_at,
                started_at,
                state,
                f"revoker-{suffix}" if state == "revoked" else None,
                started_at if state == "revoked" else None,
            ),
        )

    try:
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            for name in principals:
                await seed_proposal(connection, name)
            await seed_binding(connection, "verified", state="active")
            await seed_binding(connection, "revoked", state="revoked")

        verified = completion("verified")
        inserted = await repository.project(verified)
        duplicate = await repository.project(verified)

        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            delivery_cursor = await connection.execute(
                "SELECT delivery_id, principal_id, binding_id, channel_kind, state, "
                "response ->> 'execution_authority' "
                "FROM conversation_outbound_delivery WHERE principal_id = %s",
                (principals["verified"],),
            )
            deliveries = await delivery_cursor.fetchall()

        assert inserted.duplicate is False
        assert duplicate.duplicate is True
        assert len(deliveries) == 1
        assert deliveries[0][1] == principals["verified"]
        assert deliveries[0][2] == binding_ids["verified"]
        assert deliveries[0][3] == "slack"
        assert deliveries[0][4] == "pending"
        assert deliveries[0][5] == "false"

        with pytest.raises(ReadInvestigationCompletionConflictError) as revoked_error:
            await repository.project(completion("revoked"))
        assert revoked_error.value.reason is ReadInvestigationCompletionRejectReason.BINDING_REVOKED

        with pytest.raises(ReadInvestigationCompletionConflictError) as unverified_error:
            await repository.project(completion("unverified"))
        assert (
            unverified_error.value.reason
            is ReadInvestigationCompletionRejectReason.BINDING_UNVERIFIED
        )
    finally:
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute(
                "DELETE FROM operator_read_investigation_completion WHERE principal_id = ANY(%s)",
                (list(principals.values()),),
            )
            await connection.execute(
                "DELETE FROM conversation_outbound_delivery WHERE principal_id = ANY(%s)",
                (list(principals.values()),),
            )
            await connection.execute(
                "DELETE FROM principal_conversation_binding WHERE principal_id = ANY(%s)",
                (list(principals.values()),),
            )
            await connection.execute(
                "DELETE FROM state_kv WHERE key = ANY(%s)",
                ([request_key(name) for name in principals],),
            )
