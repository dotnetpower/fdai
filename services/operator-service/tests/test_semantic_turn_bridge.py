"""Focused semantic-turn bridge tests for the independent Operator Service."""

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid5

import fdai_operator_service.composition as composition_module
import pytest
from fdai_operator_service.composition import ProductionOperatorComposition
from fdai_operator_service.environment import (
    AUDIENCE_ENV,
    DATABASE_ROLE_ENV,
    DATABASE_URL_ENV,
    GROUP_ENV,
    KAFKA_BOOTSTRAP_SERVERS_ENV,
    LOCAL_AZURE_NARRATOR_ENV,
    SEMANTIC_CONSUMER_GROUP_ENV,
    SEMANTIC_KAFKA_CLIENT_ID_ENV,
    SEMANTIC_PROJECTION_TOPIC_ENV,
    SEMANTIC_REQUEST_TOPIC_ENV,
    TENANT_ENV,
)
from fdai_operator_service.families.conversation import (
    semantic_turn_runtime as semantic_turn_runtime_module,
)
from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    ConversationProposal,
    ConversationQuery,
    ConversationResponse,
    ConversationStreamRequest,
    JsonObject,
    PrincipalScope,
)
from fdai_operator_service.families.conversation.semantic_turn import SemanticTurnEnvelopeBuilder
from fdai_operator_service.families.conversation.semantic_turn_runtime import (
    SemanticTurnBridge,
    SemanticTurnConversationAdapters,
    SemanticTurnOutboxDrainer,
    SemanticTurnProjectionConsumer,
    _held_projection,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
    PostgresSemanticTurnConflict,
    SemanticTurnClaim,
    StoredSemanticResult,
    StoredSemanticTurn,
)
from fdai_operator_service.postgres_semantic_turn_store import PostgresSemanticTurnRepository
from fdai_service_contracts import ContractValidationError
from pydantic import ValidationError

_TEST_NAMESPACE = UUID(int=0)


def _proposal(*, body: JsonObject | None = None) -> ConversationProposal:
    return ConversationProposal(
        operation="chat.stream",
        scope=PrincipalScope("operator-1", frozenset({"Reader", "Approver"})),
        idempotency_key="turn-retry-1",
        body=body or {"prompt": "Show the current incident evidence."},
    )


def test_semantic_envelope_defaults_to_core_operations_review_purpose() -> None:
    envelope = SemanticTurnEnvelopeBuilder(clock=lambda: datetime(2026, 8, 11, tzinfo=UTC)).build(
        _proposal()
    )

    semantic_turn = cast(dict[str, object], envelope["semantic_turn"])
    assert semantic_turn["purpose"] == "operations-review"


class _MemorySemanticStore:
    def __init__(self) -> None:
        self.turns: dict[str, StoredSemanticTurn] = {}
        self.results: dict[str, StoredSemanticResult] = {}
        self.claim: SemanticTurnClaim | None = None
        self.claim_available = False
        self.releases = 0
        self.published = 0

    async def append_semantic_turn(
        self,
        *,
        principal_id: str,
        idempotency_key: str,
        request_digest: str,
        envelope: Mapping[str, object],
    ) -> StoredSemanticTurn:
        del request_digest
        request_id = cast(str, envelope["request_id"])
        proposal_id = f"semantic-{request_id}"
        existing = self.turns.get(proposal_id)
        if existing is not None:
            return StoredSemanticTurn(
                key=existing.key,
                proposal_id=existing.proposal_id,
                request_id=existing.request_id,
                principal_id=existing.principal_id,
                envelope=existing.envelope,
                duplicate=True,
            )
        stored = StoredSemanticTurn(
            key=f"outbox:{hashlib.sha256(idempotency_key.encode()).hexdigest()}",
            proposal_id=proposal_id,
            request_id=request_id,
            principal_id=principal_id,
            envelope=dict(envelope),
            duplicate=False,
        )
        self.turns[proposal_id] = stored
        self.claim = SemanticTurnClaim(
            key=stored.key,
            claim_id="claim-1",
            request_id=request_id,
            principal_id=principal_id,
            envelope=stored.envelope,
            attempt=1,
        )
        self.claim_available = True
        return stored

    async def claim_semantic_turn(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> SemanticTurnClaim | None:
        del worker_id, lease_seconds
        if not self.claim_available:
            return None
        self.claim_available = False
        return self.claim

    async def mark_semantic_turn_published(self, *, key: str, claim_id: str) -> bool:
        del key, claim_id
        self.published += 1
        return True

    async def release_semantic_turn_claim(self, *, key: str, claim_id: str) -> bool:
        del key, claim_id
        self.releases += 1
        self.claim_available = True
        return True

    async def read_semantic_turn(
        self,
        *,
        principal_id: str,
        proposal_id: str,
    ) -> StoredSemanticTurn | None:
        stored = self.turns.get(proposal_id)
        return stored if stored is not None and stored.principal_id == principal_id else None

    async def project_semantic_turn_result(
        self,
        *,
        projection: Mapping[str, object],
    ) -> StoredSemanticResult:
        request_id = cast(str, projection["request_id"])
        projection_id = cast(str, projection["projection_id"])
        owner = next(turn for turn in self.turns.values() if turn.request_id == request_id)
        existing = self.results.get(projection_id)
        if existing is not None:
            return StoredSemanticResult(
                sequence=existing.sequence,
                event=existing.event,
                request_id=existing.request_id,
                principal_id=existing.principal_id,
                projection_id=existing.projection_id,
                data=existing.data,
                duplicate=True,
            )
        result_payload = cast(dict[str, object], projection["semantic_result"])
        stored = StoredSemanticResult(
            sequence=cast(int, result_payload["turn_sequence"]) + 1,
            event="semantic_turn_result",
            request_id=request_id,
            principal_id=owner.principal_id,
            projection_id=projection_id,
            data=dict(projection),
            duplicate=False,
        )
        self.results[projection_id] = stored
        return stored

    async def replay_semantic_turn(
        self,
        *,
        principal_id: str,
        request_id: str,
        after_sequence: int | None,
        limit: int = 100,
    ) -> tuple[StoredSemanticResult, ...]:
        return tuple(
            sorted(
                (
                    result
                    for result in self.results.values()
                    if result.principal_id == principal_id
                    and result.request_id == request_id
                    and result.sequence > (after_sequence or 0)
                ),
                key=lambda result: (result.sequence, result.projection_id),
            )
        )[:limit]


class _FailOncePublisher:
    def __init__(self) -> None:
        self.calls = 0

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object:
        del topic, key, payload
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transport unavailable")
        return object()


def _projection(
    envelope: Mapping[str, object],
    *,
    disposition: str = "held",
    answered_evidence: bool = False,
) -> dict[str, object]:
    semantic = cast(dict[str, object], envelope["semantic_turn"])
    result: dict[str, object] = {
        "disposition": disposition,
        "reason_code": "verified_answer" if disposition == "answered" else "runtime_held",
        "session_id": semantic["session_id"],
        "turn_id": semantic["turn_id"],
        "turn_sequence": semantic["turn_sequence"],
        "evidence_refs": ["evidence-1"] if answered_evidence else [],
        "checks_completed": 1 if answered_evidence else 0,
        "checks_total": 1 if answered_evidence else 0,
        "answer": f"Semantic result: {disposition}",
        "execution_authority": False,
    }
    if answered_evidence:
        digest = f"sha256:{'a' * 64}"
        result.update(
            {
                "ontology_release_digest": digest,
                "principal_manifest_digest": digest,
                "plan_digest": digest,
                "execution_receipt_digest": digest,
            }
        )
    request_id = cast(str, envelope["request_id"])
    return {
        "schema_version": "1.2.0",
        "projection_id": str(uuid5(_TEST_NAMESPACE, f"{disposition}:{request_id}")),
        "request_id": request_id,
        "correlation_id": envelope["correlation_id"],
        "idempotency_key": envelope["idempotency_key"],
        "status": disposition,
        "recorded_at": envelope["requested_at"],
        "payload": {},
        "semantic_result": result,
    }


def test_semantic_turn_roles_come_only_from_authorized_principal_scope() -> None:
    envelope = SemanticTurnEnvelopeBuilder(clock=lambda: datetime(2026, 8, 11, tzinfo=UTC)).build(
        _proposal(
            body={
                "prompt": "Show the current incident evidence.",
                "roles": ["Owner", "BreakGlass"],
            }
        )
    )

    turn = cast(dict[str, object], envelope["semantic_turn"])
    principal = cast(dict[str, object], turn["principal"])
    assert principal == {"subject_id": "operator-1", "roles": ["Reader", "Approver"]}


def test_semantic_turn_identity_is_stable_across_retry_clocks() -> None:
    first = SemanticTurnEnvelopeBuilder(clock=lambda: datetime(2026, 8, 11, tzinfo=UTC)).build(
        _proposal()
    )
    retried = SemanticTurnEnvelopeBuilder(
        clock=lambda: datetime(2026, 8, 11, tzinfo=UTC) + timedelta(seconds=5)
    ).build(_proposal())

    first_turn = cast(dict[str, object], first["semantic_turn"])
    retried_turn = cast(dict[str, object], retried["semantic_turn"])
    assert first["request_id"] == retried["request_id"]
    assert first["correlation_id"] == retried["correlation_id"]
    assert first["idempotency_key"] == retried["idempotency_key"]
    assert first_turn["session_id"] == retried_turn["session_id"]
    assert first_turn["turn_id"] == retried_turn["turn_id"]


async def test_semantic_turn_duplicate_with_different_content_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = SemanticTurnEnvelopeBuilder(clock=lambda: datetime(2026, 8, 11, tzinfo=UTC)).build(
        _proposal()
    )

    async def insert_if_absent(
        self: PostgresFamilyStore,
        *,
        key: str,
        value: Mapping[str, object],
    ) -> tuple[bool, dict[str, object]]:
        del self, key
        return False, {**value, "request_digest": "different"}

    monkeypatch.setattr(PostgresFamilyStore, "_insert_if_absent", insert_if_absent)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    with pytest.raises(PostgresSemanticTurnConflict, match="different semantic turn"):
        await store.append_semantic_turn(
            principal_id="operator-1",
            idempotency_key="turn-retry-1",
            request_digest="expected",
            envelope=envelope,
        )


async def test_semantic_turn_concurrent_claim_uses_one_replica_safe_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = SemanticTurnEnvelopeBuilder(clock=lambda: datetime(2026, 8, 11, tzinfo=UTC)).build(
        _proposal()
    )
    captured: list[tuple[str, Mapping[str, object]]] = []
    lock = asyncio.Lock()
    already_claimed = False

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self
        nonlocal already_claimed
        captured.append((statement, parameters))
        async with lock:
            if already_claimed:
                return []
            already_claimed = True
            return [
                {
                    "key": "operator-semantic-outbox:item",
                    "value": {
                        "proposal_id": f"semantic-{envelope['request_id']}",
                        "request_id": envelope["request_id"],
                        "principal_id": "operator-1",
                        "envelope": envelope,
                        "attempt": 1,
                    },
                }
            ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    claims = await asyncio.gather(
        store.claim_semantic_turn(worker_id="replica-a", lease_seconds=30),
        store.claim_semantic_turn(worker_id="replica-b", lease_seconds=30),
    )

    assert sum(claim is not None for claim in claims) == 1
    assert all("FOR UPDATE SKIP LOCKED" in statement for statement, _ in captured)
    assert all("NOW()" in statement for statement, _ in captured)
    assert all(parameters["test_now"] is None for _, parameters in captured)


async def test_claim_test_clock_controls_eligibility_and_lease() -> None:
    captured: list[tuple[str, Mapping[str, object]]] = []
    test_now = datetime(2026, 8, 11, 12, 30, tzinfo=UTC)

    async def fetch_all(
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        captured.append((statement, parameters))
        return []

    repository = PostgresSemanticTurnRepository(
        fetch_all=fetch_all,
        insert_if_absent=cast(Any, object()),
    )

    assert (
        await repository.claim(
            worker_id="replica-a",
            lease_seconds=30,
            test_now=test_now,
        )
        is None
    )

    statement, parameters = captured[0]
    assert statement.count("COALESCE(%(test_now)s::timestamptz, NOW())") == 2
    assert "make_interval(secs => %(lease_seconds)s)" in statement
    assert "'claim_id', %(claim_id)s::text" in statement
    assert "'lease_owner', %(worker_id)s::text" in statement
    assert statement.count("NOW()") == 3
    assert parameters["test_now"] == test_now
    assert parameters["lease_seconds"] == 30


async def test_semantic_turn_replay_is_ordered_and_principal_request_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, Mapping[str, object]]] = []

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        del self
        captured.append((statement, parameters))
        return [
            {
                "value": {
                    "event_sequence": sequence,
                    "event": "semantic_turn_result",
                    "request_id": "request-1",
                    "principal_id": "operator-1",
                    "projection_id": f"projection-{sequence}",
                    "data": {"status": status},
                }
            }
            for sequence, status in ((1, "held"), (2, "answered"))
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    results = await store.replay_semantic_turn(
        principal_id="operator-1",
        request_id="request-1",
        after_sequence=0,
    )

    assert [result.sequence for result in results] == [1, 2]
    statement, parameters = captured[0]
    assert "value ->> 'principal_id' = %(principal_id)s" in statement
    assert "value ->> 'request_id' = %(request_id)s" in statement
    assert "ORDER BY (value ->> 'event_sequence')::bigint" in statement
    assert parameters["principal_id"] == "operator-1"
    assert parameters["request_id"] == "request-1"


async def test_missing_transport_projects_typed_held_result() -> None:
    store = _MemorySemanticStore()
    bridge = SemanticTurnBridge(
        store=store,
        builder=SemanticTurnEnvelopeBuilder(clock=lambda: datetime(2026, 8, 11, tzinfo=UTC)),
    )

    receipt = await bridge.append(_proposal())
    stream = await bridge.open(
        ConversationStreamRequest(
            operation="chat.stream",
            scope=PrincipalScope("operator-1", frozenset({"Reader"})),
            proposal_id=receipt.proposal_id,
        )
    )
    events = [event async for event in stream]

    assert receipt.response.body is not None
    assert cast(dict[str, object], receipt.response.body)["dispatch_status"] == "held"
    assert len(events) == 1
    semantic_result = cast(dict[str, object], events[0].data["semantic_result"])
    verification = cast(dict[str, object], events[0].data["verification"])
    assert events[0].event == "done"
    assert semantic_result["disposition"] == "held"
    assert semantic_result["reason_code"] == "semantic_transport_unavailable"
    assert "semantic_transport_unavailable" in cast(str, semantic_result["answer"])
    assert verification["status"] == "unverified"


def test_held_projection_identity_binds_request_and_terminal_result_digest() -> None:
    envelope = SemanticTurnEnvelopeBuilder(clock=lambda: datetime(2026, 8, 11, tzinfo=UTC)).build(
        _proposal()
    )

    first = _held_projection(envelope)
    retried = _held_projection(envelope)
    semantic_result = cast(dict[str, object], first["semantic_result"])
    encoded = json.dumps(
        semantic_result,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    result_digest = hashlib.sha256(encoded).hexdigest()

    assert first == retried
    assert first["projection_id"] == str(
        uuid5(_TEST_NAMESPACE, f"held\0{envelope['request_id']}\0{result_digest}")
    )


async def test_held_retry_reuses_one_terminal_projection() -> None:
    store = _MemorySemanticStore()
    bridge = SemanticTurnBridge(
        store=store,
        builder=SemanticTurnEnvelopeBuilder(clock=lambda: datetime(2026, 8, 11, tzinfo=UTC)),
    )

    first = await bridge.append(_proposal())
    retried = await bridge.append(_proposal())

    assert retried.proposal_id == first.proposal_id
    assert retried.duplicate is True
    assert len(store.results) == 1


async def test_result_collision_binds_request_principal_and_digest() -> None:
    captured: list[tuple[str, Mapping[str, object]]] = []

    async def fetch_all(
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        captured.append((statement, parameters))
        record = json.loads(cast(str, parameters["record"]))
        return [{"inserted": True, "value": {**record, "principal_id": "operator-1"}}]

    repository = PostgresSemanticTurnRepository(
        fetch_all=fetch_all,
        insert_if_absent=cast(Any, object()),
    )
    first = _projection(
        SemanticTurnEnvelopeBuilder(clock=lambda: datetime(2026, 8, 11, tzinfo=UTC)).build(
            _proposal()
        )
    )
    second = {**first, "request_id": "request-for-another-principal"}

    await repository.project(projection=first)
    await repository.project(projection=second)

    first_statement, first_parameters = captured[0]
    _, second_parameters = captured[1]
    normalized_statement = " ".join(first_statement.split())
    assert first_parameters["result_key"] != second_parameters["result_key"]
    assert "existing.value ->> 'request_id' = %(request_id)s" in normalized_statement
    assert "existing.value ->> 'principal_id' = owned_request.principal_id" in normalized_statement
    assert "existing.value ->> 'projection_digest' = %(projection_digest)s" in normalized_statement
    assert "'completed_at', %(recorded_at)s::text" in normalized_statement
    assert "EXISTS (SELECT 1 FROM accepted)" in normalized_statement


async def test_semantic_claim_transition_casts_json_text_values() -> None:
    captured: list[str] = []

    async def fetch_all(
        statement: str,
        _parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        captured.append(statement)
        return []

    repository = PostgresSemanticTurnRepository(
        fetch_all=fetch_all,
        insert_if_absent=cast(Any, object()),
    )

    assert await repository.mark_published(key="outbox-key", claim_id="claim-id") is False
    assert "'state', %(state)s::text" in captured[0]


async def test_semantic_replay_rejects_another_principal() -> None:
    store = _MemorySemanticStore()
    bridge = SemanticTurnBridge(
        store=store,
        builder=SemanticTurnEnvelopeBuilder(clock=lambda: datetime(2026, 8, 11, tzinfo=UTC)),
    )
    receipt = await bridge.append(_proposal())

    with pytest.raises(ConversationBoundaryError) as raised:
        await bridge.open(
            ConversationStreamRequest(
                operation="chat.stream",
                scope=PrincipalScope("operator-2", frozenset({"Owner"})),
                proposal_id=receipt.proposal_id,
            )
        )

    assert raised.value.status_code == 404


async def test_outbox_publish_failure_releases_claim_for_retry() -> None:
    store = _MemorySemanticStore()
    envelope = SemanticTurnEnvelopeBuilder(clock=lambda: datetime(2026, 8, 11, tzinfo=UTC)).build(
        _proposal()
    )
    await store.append_semantic_turn(
        principal_id="operator-1",
        idempotency_key="turn-retry-1",
        request_digest="digest",
        envelope=envelope,
    )
    publisher = _FailOncePublisher()
    drainer = SemanticTurnOutboxDrainer(store, publisher, "replica-a")

    assert await drainer.run_once() is False
    assert store.releases == 1
    assert await drainer.run_once() is True
    assert publisher.calls == 2
    assert store.published == 1


async def test_result_consumer_rejects_invalid_codec_payload() -> None:
    store = _MemorySemanticStore()
    envelope = SemanticTurnEnvelopeBuilder(clock=lambda: datetime(2026, 8, 11, tzinfo=UTC)).build(
        _proposal()
    )
    await store.append_semantic_turn(
        principal_id="operator-1",
        idempotency_key="turn-retry-1",
        request_digest="digest",
        envelope=envelope,
    )
    invalid = {**_projection(envelope), "unexpected": True}

    with pytest.raises(ContractValidationError):
        await SemanticTurnProjectionConsumer(store).consume(invalid)


async def test_answered_result_requires_complete_verified_evidence() -> None:
    store = _MemorySemanticStore()
    envelope = SemanticTurnEnvelopeBuilder(clock=lambda: datetime(2026, 8, 11, tzinfo=UTC)).build(
        _proposal()
    )
    await store.append_semantic_turn(
        principal_id="operator-1",
        idempotency_key="turn-retry-1",
        request_digest="digest",
        envelope=envelope,
    )

    with pytest.raises((ContractValidationError, ValidationError)):
        await SemanticTurnProjectionConsumer(store).consume(
            _projection(envelope, disposition="answered")
        )


async def test_valid_answered_result_projects_idempotently() -> None:
    store = _MemorySemanticStore()
    envelope = SemanticTurnEnvelopeBuilder(clock=lambda: datetime(2026, 8, 11, tzinfo=UTC)).build(
        _proposal()
    )
    await store.append_semantic_turn(
        principal_id="operator-1",
        idempotency_key="turn-retry-1",
        request_digest="digest",
        envelope=envelope,
    )
    projection = _projection(envelope, disposition="answered", answered_evidence=True)
    consumer = SemanticTurnProjectionConsumer(store)

    first = await consumer.consume(projection)
    duplicate = await consumer.consume(projection)

    assert first.duplicate is False
    assert duplicate.duplicate is True
    assert len(store.results) == 1


def test_legacy_semantic_result_without_answer_replays_as_unverified_limitation() -> None:
    projection = {
        "semantic_result": {
            "disposition": "held",
            "reason_code": "semantic_runtime_unavailable",
            "evidence_refs": [],
            "checks_completed": 0,
            "checks_total": 0,
        }
    }

    done = semantic_turn_runtime_module._done_event_data(projection)

    assert "predates terminal presentation support" in cast(str, done["answer"])
    verification = cast(dict[str, object], done["verification"])
    assert verification["status"] == "unverified"
    assert verification["reason_code"] == "semantic_answer_missing"


async def test_semantic_bridge_replays_results_in_sequence_order() -> None:
    store = _MemorySemanticStore()
    bridge = SemanticTurnBridge(
        store=store,
        builder=SemanticTurnEnvelopeBuilder(clock=lambda: datetime(2026, 8, 11, tzinfo=UTC)),
    )
    receipt = await bridge.append(_proposal())
    stored_turn = store.turns[receipt.proposal_id]
    store.results = {
        "late": StoredSemanticResult(
            2,
            "done",
            stored_turn.request_id,
            "operator-1",
            "late",
            _projection(stored_turn.envelope, disposition="answered", answered_evidence=True),
            False,
        ),
        "early": StoredSemanticResult(
            1,
            "done",
            stored_turn.request_id,
            "operator-1",
            "early",
            _projection(stored_turn.envelope, disposition="held"),
            False,
        ),
    }

    stream = await bridge.open(
        ConversationStreamRequest(
            operation="chat.stream",
            scope=PrincipalScope("operator-1", frozenset({"Reader"})),
            proposal_id=receipt.proposal_id,
        )
    )

    assert [event.event_id async for event in stream] == ["1", "2"]


async def test_semantic_bridge_waits_for_delayed_terminal_projection() -> None:
    store = _MemorySemanticStore()
    bridge = SemanticTurnBridge(
        store=store,
        publisher=cast(Any, object()),
        result_source=cast(Any, object()),
        builder=SemanticTurnEnvelopeBuilder(clock=lambda: datetime.now(UTC)),
        retry_seconds=0.01,
    )
    receipt = await bridge.append(_proposal())
    stored_turn = store.turns[receipt.proposal_id]

    async def project_after_transport_delay() -> None:
        await asyncio.sleep(0.02)
        await SemanticTurnProjectionConsumer(store).consume(
            _projection(stored_turn.envelope, disposition="answered", answered_evidence=True)
        )

    projection_task = asyncio.create_task(project_after_transport_delay())
    stream = await bridge.open(
        ConversationStreamRequest(
            operation="chat.stream",
            scope=PrincipalScope("operator-1", frozenset({"Reader"})),
            proposal_id=receipt.proposal_id,
        )
    )
    events = [event async for event in stream]
    await projection_task

    assert len(events) == 1
    assert events[0].event == "done"


async def test_semantic_bridge_deadline_projects_typed_hold() -> None:
    store = _MemorySemanticStore()
    now = datetime.now(UTC)
    bridge = SemanticTurnBridge(
        store=store,
        publisher=cast(Any, object()),
        result_source=cast(Any, object()),
        builder=SemanticTurnEnvelopeBuilder(clock=lambda: now),
        retry_seconds=0.01,
    )
    receipt = await bridge.append(
        _proposal(
            body={
                "prompt": "Show the current incident evidence.",
                "deadline_at": (now + timedelta(seconds=0.02)).isoformat(),
            }
        )
    )

    stream = await bridge.open(
        ConversationStreamRequest(
            operation="chat.stream",
            scope=PrincipalScope("operator-1", frozenset({"Reader"})),
            proposal_id=receipt.proposal_id,
        )
    )
    events = [event async for event in stream]

    assert len(events) == 1
    assert events[0].event == "done"
    semantic_result = cast(dict[str, object], events[0].data["semantic_result"])
    assert semantic_result["disposition"] == "held"
    assert semantic_result["reason_code"] == "semantic_transport_unavailable"


async def test_semantic_adapter_delegates_reads_and_exposes_bridge_health() -> None:
    class ProjectionReader:
        def __init__(self) -> None:
            self.operations: list[str] = []

        async def read(self, query: ConversationQuery) -> ConversationResponse:
            self.operations.append(query.operation)
            return ConversationResponse(body={"mode": "azure-cli"})

    class Publisher:
        async def publish(
            self,
            topic: str,
            key: str,
            payload: Mapping[str, object],
        ) -> object:
            del topic, key, payload
            return object()

    class Source:
        def subscribe(
            self,
            topic: str,
            group_id: str,
        ) -> AsyncIterator[Mapping[str, object]]:
            del topic, group_id

            async def empty() -> AsyncIterator[Mapping[str, object]]:
                if False:
                    yield {}

            return empty()

    fallback = ProjectionReader()
    bridge = SemanticTurnBridge(
        store=_MemorySemanticStore(),
        publisher=Publisher(),
        result_source=Source(),
    )
    adapters = SemanticTurnConversationAdapters(
        bridge=bridge,
        fallback_projections=fallback,
        fallback_outbox=cast(Any, object()),
        fallback_streams=cast(Any, object()),
    )
    scope = PrincipalScope("operator-1", frozenset({"Reader"}))

    delegated = await adapters.read(ConversationQuery(operation="chat.history", scope=scope))
    health = await adapters.read(ConversationQuery(operation="chat.health", scope=scope))

    assert delegated.body == {"mode": "azure-cli"}
    assert fallback.operations == ["chat.history", "chat.health"]
    assert cast(dict[str, object], health.body)["semantic_bridge"] == {
        "available": False,
        "configured": True,
        "mode": "starting",
        "request_topic": "operator.semantic-turn.requests",
        "result_topic": "core.semantic-turn.projections",
    }


async def test_injected_result_consumer_starts_and_stops_with_bridge() -> None:
    store = _MemorySemanticStore()
    envelope = SemanticTurnEnvelopeBuilder(clock=lambda: datetime(2026, 8, 11, tzinfo=UTC)).build(
        _proposal()
    )
    await store.append_semantic_turn(
        principal_id="operator-1",
        idempotency_key="turn-retry-1",
        request_digest="digest",
        envelope=envelope,
    )
    consumed = asyncio.Event()

    class ResultSource:
        def subscribe(
            self,
            topic: str,
            group_id: str,
        ) -> AsyncIterator[Mapping[str, object]]:
            assert topic == "core.semantic-turn.projections"
            assert group_id == "operator-semantic-turn-v1"

            async def events() -> AsyncIterator[Mapping[str, object]]:
                yield _projection(envelope)
                consumed.set()
                await asyncio.Event().wait()

            return events()

    class Publisher:
        async def publish(
            self,
            topic: str,
            key: str,
            payload: Mapping[str, object],
        ) -> object:
            del topic, key, payload
            return object()

    bridge = SemanticTurnBridge(
        store=store,
        publisher=Publisher(),
        result_source=ResultSource(),
        retry_seconds=0.01,
    )

    await bridge.start()
    await asyncio.wait_for(consumed.wait(), timeout=1)
    assert bridge.workers_ready() is True
    assert bridge.health()["available"] is True
    await bridge.aclose()

    assert len(store.results) == 1
    assert bridge.workers_ready() is False


def test_production_composition_activates_semantic_bridge_only_with_transport(
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "models.json"
    model_path.write_text(
        '{"narrator":{"endpoint":"https://example.openai.azure.com",'
        '"deployment":"narrator","api_version":"2024-08-01-preview"}}',
        encoding="utf-8",
    )
    environment = {
        TENANT_ENV: "tenant",
        AUDIENCE_ENV: "audience",
        DATABASE_URL_ENV: "postgresql://example.invalid/fdai",
        DATABASE_ROLE_ENV: "fdai_operator",
        LOCAL_AZURE_NARRATOR_ENV: "1",
        "RUNTIME_ENV": "dev",
        "LLM_RESOLVED_MODELS_PATH": str(model_path),
        **{key: f"group-{index}" for index, key in enumerate(GROUP_ENV.values())},
    }

    class Publisher:
        async def publish(
            self,
            topic: str,
            key: str,
            payload: Mapping[str, object],
        ) -> object:
            del topic, key, payload
            return object()

    class Source:
        def subscribe(
            self,
            topic: str,
            group_id: str,
        ) -> AsyncIterator[Mapping[str, object]]:
            del topic, group_id

            async def empty() -> AsyncIterator[Mapping[str, object]]:
                if False:
                    yield {}

            return empty()

    default_runtime = ProductionOperatorComposition(
        verifier_factory=lambda _environment: (
            lambda _token: {
                "oid": "operator-1",
                "roles": ["Reader"],
            }
        )
    ).build_runtime(environment)
    semantic_runtime = ProductionOperatorComposition(
        verifier_factory=lambda _environment: (
            lambda _token: {
                "oid": "operator-1",
                "roles": ["Reader"],
            }
        ),
        semantic_event_publisher=Publisher(),
        semantic_result_source=Source(),
    ).build_runtime(environment)

    assert default_runtime.lifecycle is None
    assert isinstance(semantic_runtime.lifecycle, SemanticTurnBridge)
    semantic_conversation = semantic_runtime.route_families.conversation
    assert isinstance(semantic_conversation.projections, SemanticTurnConversationAdapters)
    assert semantic_conversation.projections is semantic_conversation.outbox
    assert semantic_conversation.projections is semantic_conversation.streams
    assert semantic_conversation.projections.fallback_streams.__class__.__name__ == (
        "PostgresConversationAdapters"
    )


async def test_production_composition_auto_binds_one_kafka_bus_and_owns_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class Bus:
        async def start(self) -> None:
            events.append("bus-start")

        async def aclose(self) -> None:
            events.append("bus-close")

        async def probe_readiness(self) -> bool:
            return True

        async def publish(
            self,
            topic: str,
            key: str,
            payload: Mapping[str, object],
        ) -> object:
            del topic, key, payload
            return object()

        def subscribe(
            self,
            topic: str,
            group_id: str,
        ) -> AsyncIterator[Mapping[str, object]]:
            del topic, group_id

            async def empty() -> AsyncIterator[Mapping[str, object]]:
                if False:
                    yield {}

            return empty()

    bus = Bus()
    monkeypatch.setattr(composition_module, "_build_semantic_bus", lambda _environment: bus)

    async def bridge_start(self: SemanticTurnBridge) -> None:
        events.append("bridge-start")

    async def bridge_close(self: SemanticTurnBridge) -> None:
        events.append("bridge-close")

    monkeypatch.setattr(SemanticTurnBridge, "start", bridge_start)
    monkeypatch.setattr(SemanticTurnBridge, "aclose", bridge_close)
    runtime = ProductionOperatorComposition(
        verifier_factory=lambda _environment: (
            lambda _token: {"oid": "operator-1", "roles": ["Reader"]}
        )
    ).build_runtime(
        {
            TENANT_ENV: "tenant",
            AUDIENCE_ENV: "audience",
            DATABASE_URL_ENV: "postgresql://example.invalid/fdai",
            DATABASE_ROLE_ENV: "fdai_operator",
            KAFKA_BOOTSTRAP_SERVERS_ENV: "example.servicebus.windows.net:9093",
            SEMANTIC_REQUEST_TOPIC_ENV: "semantic.requests",
            SEMANTIC_PROJECTION_TOPIC_ENV: "semantic.projections",
            SEMANTIC_CONSUMER_GROUP_ENV: "semantic-group",
            SEMANTIC_KAFKA_CLIENT_ID_ENV: "semantic-client",
            **{key: f"group-{index}" for index, key in enumerate(GROUP_ENV.values())},
        }
    )

    assert runtime.lifecycle is not None
    semantic = runtime.route_families.conversation.projections
    assert isinstance(semantic, SemanticTurnConversationAdapters)
    assert semantic.bridge.health() == {
        "available": False,
        "configured": True,
        "mode": "starting",
        "request_topic": "semantic.requests",
        "result_topic": "semantic.projections",
    }

    await runtime.lifecycle.start()
    await runtime.lifecycle.aclose()

    assert events == ["bus-start", "bridge-start", "bridge-close", "bus-close"]


def test_production_composition_rejects_semantic_transport_before_bus_without_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        composition_module,
        "_build_semantic_bus",
        lambda _environment: pytest.fail("bus MUST NOT be built without the durable store"),
    )

    with pytest.raises(RuntimeError, match="requires the authoritative PostgreSQL store"):
        ProductionOperatorComposition(
            verifier_factory=lambda _environment: (
                lambda _token: {"oid": "operator-1", "roles": ["Reader"]}
            )
        ).build_runtime(
            {
                TENANT_ENV: "tenant",
                AUDIENCE_ENV: "audience",
                KAFKA_BOOTSTRAP_SERVERS_ENV: "example.servicebus.windows.net:9093",
                SEMANTIC_REQUEST_TOPIC_ENV: "semantic.requests",
                SEMANTIC_PROJECTION_TOPIC_ENV: "semantic.projections",
                **{key: f"group-{index}" for index, key in enumerate(GROUP_ENV.values())},
            }
        )


async def test_semantic_lifecycle_closes_kafka_when_bridge_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class Bus:
        async def start(self) -> None:
            return None

        async def aclose(self) -> None:
            events.append("bus-close")

    class Bridge:
        async def start(self) -> None:
            return None

        async def aclose(self) -> None:
            events.append("bridge-close")
            raise RuntimeError("bridge close failed")

    lifecycle = composition_module._CompositeLifecycle((Bus(), Bridge()))

    with pytest.raises(RuntimeError, match="bridge close failed"):
        await lifecycle.aclose()

    assert events == ["bridge-close", "bus-close"]
