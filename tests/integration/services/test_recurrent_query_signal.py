from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.norns_recurrent_queries import _KEY, RecurrentQueryTracker
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.bragi import Bragi
from fdai.agents.mimir import Mimir
from fdai.agents.norns import Norns
from fdai.core.learning import PostTurnReviewInput, PostTurnReviewState, review_input_from_mapping
from fdai.core.ontology_platform.query_execution import (
    OntologyQueryPlanExecutor,
    QueryNodeResult,
)
from fdai.core.ontology_platform.query_values import QueryTable
from fdai.core.operator_memory import InMemoryOperatorMemoryStore
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.post_turn_review_ingress import PostTurnReviewRequestConsumer
from fdai.runtime.post_turn_review import build_post_turn_review_runtime
from fdai.shared.providers.event_bus import EventEnvelope
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_core_service.post_turn_procedure import (
    bound_procedure_projection,
    execution_receipt_digest,
    with_post_turn_procedure,
)
from fdai_operator_service.families.conversation.post_turn_review import (
    NonBlockingPostTurnReviewQueue,
    post_turn_review_input_from_projection,
)
from fdai_operator_service.postgres_semantic_turn_store import StoredSemanticResult
from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    canonical_json,
    content_digest,
)
from fdai_service_contracts.semantic_projection import semantic_projection_id
from fdai_service_contracts.semantic_turn import SemanticTurnRequest, SemanticTurnResult
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

_NOW = datetime(2026, 10, 19, 8, tzinfo=UTC)
_DIGEST = "sha256:" + "a" * 64


async def _stored(
    principal: str,
    *,
    value: object = "private-value",
    workload: bool = False,
    complete: bool = True,
) -> StoredSemanticResult:
    request = SemanticTurnRequest(
        utterance="Inspect the current evidence.",
        principal={
            "subject_id": principal,
            "roles": ["Reader"],
            "principal_kind": "workload" if workload else "human",
        },
        session_id=f"session-{principal}",
        turn_id=f"turn-{principal}",
        turn_sequence=1,
        locale="en",
        purpose="operations-review",
        deadline_at=_NOW + timedelta(seconds=30),
    )
    node = OntologyQueryNode(
        node_id=f"read-{principal}",
        kind=QueryNodeKind.FUNCTION,
        arguments_json=canonical_json({"function_name": "query.inventory", "selector": value}),
        output_kind="table",
    )
    body = {
        "schema_version": "1.0.0",
        "ontology_release_digest": _DIGEST,
        "semantic_catalog_digest": _DIGEST,
        "problem_frame_digest": _DIGEST,
        "purpose": request.purpose,
        "caller_role": "Reader",
        "nodes": [node.model_dump(mode="json")],
        "output_node_ids": (node.node_id,),
        "execution_authority": False,
    }
    plan = OntologyQueryPlan.model_validate({**body, "plan_digest": content_digest(body)})

    async def read(node: object, dependencies: object) -> QueryNodeResult:
        del node, dependencies
        return QueryNodeResult(
            QueryTable(
                rows=(),
                complete=complete,
                truncation_reason=None if complete else "source_incomplete",
            ),
            evidence_refs=("audit:query",),
        )

    execution = await OntologyQueryPlanExecutor(
        handlers={QueryNodeKind.FUNCTION: read}, now=lambda: _NOW
    ).execute(
        plan,
        expected_release_digest=_DIGEST,
        expected_manifest_digest=_DIGEST,
        expected_role="Reader",
        expected_purpose=request.purpose,
    )
    assert execution.status == "completed"
    details = with_post_turn_procedure({}, request, plan, execution)
    result = SemanticTurnResult(
        disposition="answered",
        reason_code="semantic_answer_verified",
        semantic_route="verified_query_plan",
        session_id=request.session_id,
        turn_id=request.turn_id,
        turn_sequence=1,
        ontology_release_digest=_DIGEST,
        principal_manifest_digest=_DIGEST,
        plan_digest=plan.plan_digest,
        execution_receipt_digest=execution_receipt_digest(execution),
        checks_completed=1,
        checks_total=1,
        evidence_refs=("audit:query",),
        answer="The evidence was inspected.",
    )
    return StoredSemanticResult(
        sequence=1,
        event="semantic_result",
        request_id=f"request-{principal}",
        principal_id=principal,
        projection_id=f"projection-{principal}",
        data={
            "recorded_at": _NOW.isoformat(),
            "semantic_result": result.model_dump(mode="json"),
            "payload": {"technical_details": details},
        },
        duplicate=False,
    )


async def _review(principal: str) -> PostTurnReviewInput:
    wire = post_turn_review_input_from_projection(await _stored(principal))
    assert wire is not None
    return review_input_from_mapping(wire.to_wire_mapping())


async def test_actual_plan_receipt_reaches_the_existing_discovery_input_once() -> None:
    store = InMemoryStateStore()
    runtime = build_post_turn_review_runtime(
        state_store=store, operator_memory=InMemoryOperatorMemoryStore(), now=lambda: _NOW
    )
    bus = InMemoryBus(registry=load_pantheon())
    bragi = Bragi()
    bragi.bind_bus(bus)
    norns = Norns(
        operational_state_store=store,
        post_turn_review=runtime.coordinator,
        clock=lambda: _NOW,
    )
    norns.bind_bus(bus)
    mimir = Mimir()
    mimir.bind_bus(bus)
    bus.subscribe("object.post-turn-review", "Norns", norns.on_typed_message)
    bus.subscribe("object.rule-candidate", "Mimir", mimir.on_typed_message)
    ingress = PostTurnReviewRequestConsumer(bragi)
    provider = InMemoryEventBus()

    class Consent:
        async def read_post_turn_review_consent(self, *, principal_id: str) -> bool:
            return principal_id != "opted-out"

    class Relay:
        async def publish(self, topic: str, key: str, payload: object) -> object:
            return await ingress.handle(
                bus=provider, envelope=EventEnvelope(topic, key, payload, None)
            )

    queue = NonBlockingPostTurnReviewQueue(source=Consent(), publisher=Relay())
    for index in range(4):
        queue.enqueue_terminal(await _stored(f"human-{index}", value=f"value-{index}"))
        assert await queue.drain_once()
    assert bus.messages_on("object.rule-candidate") == []
    queue.enqueue_terminal(await _stored("human-0"))
    queue.enqueue_terminal(await _stored("opted-out"))
    assert await queue.drain_once()
    assert await queue.drain_once()
    assert bus.messages_on("object.rule-candidate") == []
    queue.enqueue_terminal(await _stored("human-4"))
    assert await queue.drain_once()
    candidates = bus.messages_on("object.rule-candidate")
    assert len(candidates) == 1
    assert candidates[0].principal == "Norns"
    assert candidates[0].payload["source_signal"] == "console.recurrent_query"
    assert candidates[0].payload["evidence"]["distinct_principal_count"] == 5
    assert candidates[0].payload["evidence"]["tool_names"] == ["query.inventory"]
    assert norns.health()["recurrent_queries"]["available"] is True
    assert mimir.health()["catalog_review"]["pending_candidates"] == 1
    assert bus.handler_errors == 0
    assert bus.messages_on("object.rule") == []
    records = await runtime.reviews.list()
    assert len(records) == 5
    assert all(record.state is PostTurnReviewState.INELIGIBLE for record in records)
    assert "human-" not in json.dumps(candidates[0].payload)
    assert queue.snapshot.skipped == 1
    assert all(
        message.payload["review"]["operator_body"] is None
        and message.payload["review"]["assistant_body"] is None
        for message in bus.messages_on("object.post-turn-review")
    )
    assert {item.topic for item in bus.published} == {
        "object.post-turn-review",
        "object.rule-candidate",
    }
    queue.enqueue_terminal(await _stored("human-4"))
    assert await queue.drain_once()
    assert len(bus.messages_on("object.rule-candidate")) == 1


async def test_fingerprint_ignores_values_principals_and_node_ids_but_preserves_types() -> None:
    first = post_turn_review_input_from_projection(await _stored("alice", value="private-first"))
    second = post_turn_review_input_from_projection(await _stored("bob", value="private-second"))
    number = post_turn_review_input_from_projection(await _stored("carol", value=7))
    assert first is not None and second is not None and number is not None
    assert first.procedure_fingerprint == second.procedure_fingerprint
    assert first.procedure_fingerprint != number.procedure_fingerprint
    assert first.principal_scope != second.principal_scope
    assert "private-first" not in first.model_dump_json()


@pytest.mark.parametrize(
    "field",
    [
        "principal_scope",
        "turn_id",
        "plan_digest",
        "execution_receipt_digest",
        "ontology_release_digest",
    ],
)
async def test_operator_rejects_receipts_from_another_result(field: str) -> None:
    stored = await _stored("alice")
    data = dict(stored.data)
    payload = dict(data["payload"])
    details = dict(payload["technical_details"])
    receipt = dict(details["post_turn_procedure"])
    receipt[field] = "other-turn" if field == "turn_id" else "sha256:" + "b" * 64
    details["post_turn_procedure"] = receipt
    payload["technical_details"] = details
    data["payload"] = payload
    with pytest.raises(ValueError, match="MUST match"):
        post_turn_review_input_from_projection(replace(stored, data=data))


async def test_tracker_replica_cas_and_restart_preserve_distinct_principal_count() -> None:
    class BarrierStore(InMemoryStateStore):
        def __init__(self) -> None:
            super().__init__()
            self.reads = 0
            self.ready = asyncio.Event()

        async def read_state(self, key: str):
            value = await super().read_state(key)
            if self.reads < 5:
                self.reads += 1
                if self.reads == 5:
                    self.ready.set()
                await self.ready.wait()
            return value

    store = BarrierStore()
    trackers = [RecurrentQueryTracker(store=store, now=lambda: _NOW) for _ in range(5)]
    reviews = [await _review(f"human-{index}") for index in range(5)]
    outcomes = await asyncio.gather(
        *(tracker.observe(review) for tracker, review in zip(trackers, reviews, strict=True))
    )
    signals = [signal for signal, _reason in outcomes if signal is not None]
    assert signals and len({signal.signal_id for signal in signals}) == 1
    restarted = RecurrentQueryTracker(store=store, now=lambda: _NOW)
    recovered, reason = await restarted.observe(reviews[0])
    assert recovered == signals[0] and reason == "pending"
    await restarted.mark_queued(signals[0])
    assert await trackers[0].observe(reviews[1]) == (None, "already_queued")


@pytest.mark.parametrize(
    "offset,reason", [(-7 * 86400, "expired_observation"), (1, "future_observation")]
)
async def test_tracker_does_not_count_expired_or_future_observations(
    offset: int, reason: str
) -> None:
    tracker = RecurrentQueryTracker(store=InMemoryStateStore(), now=lambda: _NOW)
    review = replace(await _review("alice"), completed_at=_NOW + timedelta(seconds=offset))
    assert await tracker.observe(review) == (None, reason)


@pytest.mark.parametrize("options", [{"workload": True}, {"complete": False}])
async def test_workloads_and_incomplete_evidence_do_not_supply_a_recurrent_shape(
    options: dict[str, bool],
) -> None:
    stored = await _stored("alice", **options)
    review = post_turn_review_input_from_projection(stored)
    assert review is not None and review.procedure_fingerprint is None
    assert (
        stored.data["payload"]["technical_details"]["post_turn_procedure"]["kind"] == "unavailable"
    )


async def test_legacy_hints_cannot_supply_a_fingerprint_or_claimed_repeat_count() -> None:
    stored = await _stored("alice")
    data = dict(stored.data)
    data["payload"] = {
        "post_turn_review": {
            "procedure_fingerprint": "query-shape-v1:" + "a" * 64,
            "repeated_procedure_count": 10000,
        }
    }
    review = post_turn_review_input_from_projection(replace(stored, data=data))
    assert review is not None
    assert review.procedure_fingerprint is None
    assert review.repeated_procedure_count == 0


async def test_tagged_fingerprint_without_a_source_receipt_does_not_count() -> None:
    tracker = RecurrentQueryTracker(store=InMemoryStateStore(), now=lambda: _NOW)
    review = replace(await _review("alice"), procedure_receipt=None, repeated_procedure_count=10000)
    assert await tracker.observe(review) == (None, "source_absent")


@pytest.mark.parametrize("field", ["tool_receipts", "repeated_procedure_count"])
async def test_source_receipts_cannot_be_paired_with_contradictory_review_metadata(
    field: str,
) -> None:
    review = await _review("alice")
    with pytest.raises(ValueError, match="MUST match"):
        replace(review, **{field: () if field == "tool_receipts" else 10000})


async def test_one_principal_cannot_supply_five_independent_observations() -> None:
    tracker = RecurrentQueryTracker(store=InMemoryStateStore(), now=lambda: _NOW)
    review = await _review("alice")
    for index in range(8):
        signal, reason = await tracker.observe(replace(review, review_id=f"review-{index}"))
        assert signal is None and reason == "observed"


@pytest.mark.parametrize("age", [timedelta(0), timedelta(days=7) - timedelta(microseconds=1)])
async def test_rolling_week_includes_now_and_the_microsecond_above_its_lower_bound(
    age: timedelta,
) -> None:
    tracker = RecurrentQueryTracker(store=InMemoryStateStore(), now=lambda: _NOW)
    review = replace(await _review("alice"), completed_at=_NOW - age)
    assert await tracker.observe(review) == (None, "observed")


async def test_source_shape_groups_are_independent() -> None:
    tracker = RecurrentQueryTracker(store=InMemoryStateStore(), now=lambda: _NOW, threshold=3)
    for index in range(4):
        stored = await _stored(f"human-{index}", value=1 if index % 2 else "one")
        wire = post_turn_review_input_from_projection(stored)
        assert wire is not None
        signal, _reason = await tracker.observe(review_input_from_mapping(wire.to_wire_mapping()))
        assert signal is None


async def test_closed_discovery_gate_preserves_the_inert_signal_until_reopened() -> None:
    store = InMemoryStateStore()
    bus = InMemoryBus(registry=load_pantheon())
    norns = Norns(operational_state_store=store, clock=lambda: _NOW)
    norns.bind_bus(bus)
    enabled = False
    norns.bind_candidate_publication_gate(lambda: enabled)
    for index in range(5):
        await norns._observe_recurrent_query(await _review(f"human-{index}"))
    assert bus.messages_on("object.rule-candidate") == []
    assert len(norns.pending_candidates) == 1
    enabled = True
    assert await norns.flush_candidates() == 1
    assert len(bus.messages_on("object.rule-candidate")) == 1
    assert bus.messages_on("object.action-run") == []


async def test_failed_owner_checkpoint_is_retried_before_signal_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    bus = InMemoryBus(registry=load_pantheon())
    norns = Norns(operational_state_store=store, clock=lambda: _NOW)
    norns.bind_bus(bus)
    for index in range(4):
        await norns._observe_recurrent_query(await _review(f"human-{index}"))
    persist = norns._persist_learning_state
    calls = 0

    async def fail_once() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("injected owner checkpoint failure")
        await persist()

    monkeypatch.setattr(norns, "_persist_learning_state", fail_once)
    fifth = await _review("human-4")
    with pytest.raises(RuntimeError, match="injected owner checkpoint"):
        await norns._observe_recurrent_query(fifth)
    assert bus.messages_on("object.rule-candidate") == []
    await norns._observe_recurrent_query(fifth)
    assert calls == 2
    assert len(bus.messages_on("object.rule-candidate")) == 1


@pytest.fixture
async def recurrent_postgres_stores() -> AsyncIterator[
    tuple[PostgresStateStore, PostgresStateStore]
]:
    dsn = os.environ.get("FDAI_DATABASE_URL")
    if not dsn:
        pytest.skip("isolated PostgreSQL is not configured")
    dsn = dsn.replace("postgresql+psycopg://", "postgresql://", 1)
    settings = conninfo_to_dict(dsn)
    if settings.get("host") not in {"127.0.0.1", "localhost", "::1"} or (
        os.environ.get("GITHUB_ACTIONS") != "true" and settings.get("port") != "5433"
    ):
        pytest.fail("recurrent-query tests require the isolated loopback validation database")
    schema = f"recurrent_query_test_{uuid.uuid4().hex}"
    async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=5) as connection:
        await connection.execute("SET statement_timeout = '15s'")
        await connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        await connection.execute(
            sql.SQL("CREATE TABLE {}.state_kv (LIKE public.state_kv INCLUDING ALL)").format(
                sql.Identifier(schema)
            )
        )
    config = PostgresStateStoreConfig(dsn=make_conninfo(dsn, options=f"-c search_path={schema}"))
    stores = (PostgresStateStore(config=config), PostgresStateStore(config=config))
    try:
        yield stores
    finally:
        for store in stores:
            await store.aclose()
        async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=5) as connection:
            await connection.execute("SET statement_timeout = '15s'")
            await connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


@pytest.mark.integration
async def test_postgres_replicas_retain_one_pending_signal_and_queued_restart(
    recurrent_postgres_stores: tuple[PostgresStateStore, PostgresStateStore],
) -> None:
    first, second = recurrent_postgres_stores
    trackers = [
        RecurrentQueryTracker(store=first if index % 2 else second, now=lambda: _NOW)
        for index in range(5)
    ]
    reviews = [await _review(f"human-{index}") for index in range(5)]
    outcomes = await asyncio.gather(
        *(tracker.observe(review) for tracker, review in zip(trackers, reviews, strict=True))
    )
    signals = [signal for signal, _reason in outcomes if signal is not None]
    assert signals and len({signal.signal_id for signal in signals}) == 1
    restarted = RecurrentQueryTracker(store=second, now=lambda: _NOW)
    recovered, _reason = await restarted.observe(reviews[0])
    assert recovered == signals[0]
    await restarted.mark_queued(signals[0])
    assert await trackers[0].observe(reviews[1]) == (None, "already_queued")


async def test_optional_procedure_metadata_cannot_overflow_an_existing_answer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stored = await _stored("alice")
    projection = {
        **stored.data,
        "schema_version": "1.4.0",
        "request_id": stored.request_id,
        "correlation_id": "correlation-1",
        "idempotency_key": "semantic-turn-1",
        "status": "answered",
        "evidence_digest": content_digest(stored.data["semantic_result"]),
    }
    projection["projection_id"] = semantic_projection_id(projection)
    original_semantic = dict(projection["semantic_result"])
    size = len(
        json.dumps(projection, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()
    )
    assert bound_procedure_projection(projection, maximum_bytes=size) == size
    assert (
        projection["payload"]["technical_details"]["post_turn_procedure"]["kind"]
        == "verified_ontology_query_shape"
    )
    reduced = bound_procedure_projection(projection, maximum_bytes=size - 1)
    assert reduced <= size - 1
    assert projection["semantic_result"] == original_semantic
    assert "post_turn_procedure" not in projection["payload"]["technical_details"]
    assert projection["projection_id"] == semantic_projection_id(projection)
    assert "post_turn_procedure_unavailable" in caplog.text
    assert "post_turn_procedure" in stored.data["payload"]["technical_details"]


@pytest.mark.parametrize("threshold", [True, 0, 1, 21, 5.0])
def test_invalid_threshold_is_rejected_even_without_a_durable_binding(threshold: object) -> None:
    with pytest.raises(ValueError, match="threshold MUST"):
        Norns(recurrent_query_threshold=threshold)


@pytest.mark.parametrize(
    "change",
    [
        {"revision": True},
        {"threshold": 2},
        {"unexpected": "private-test-value"},
        {"shapes": {"query-shape-v1:" + "a" * 64: {"queued": True}}},
    ],
)
async def test_persisted_state_corruption_or_binding_drift_cannot_create_a_signal(
    change: dict[str, object],
) -> None:
    store = InMemoryStateStore()
    await store.write_state(
        _KEY, {"schema_version": "1.0.0", "revision": 1, "threshold": 5, "shapes": {}, **change}
    )
    tracker = RecurrentQueryTracker(store=store, now=lambda: _NOW)
    with pytest.raises(ValueError) as error:
        await tracker.observe(await _review("alice"))
    assert "private-test-value" not in str(error.value)


@pytest.mark.parametrize("expired", [False, True])
async def test_shape_capacity_is_explicit_and_expired_shapes_can_be_reclaimed(
    expired: bool,
) -> None:
    store = InMemoryStateStore()
    review = await _review("alice")
    completed = _NOW - timedelta(days=7) if expired else _NOW
    observations = [
        {
            "principal_scope": review.principal_scope,
            "completed_at": completed.isoformat(),
            "review_id": "retained-review",
        }
    ]
    shapes = {
        f"query-shape-v1:{index:064x}": {"observations": observations} for index in range(128)
    }
    assert review.procedure_fingerprint not in shapes
    await store.write_state(
        _KEY, {"schema_version": "1.0.0", "revision": 1, "threshold": 5, "shapes": shapes}
    )
    tracker = RecurrentQueryTracker(store=store, now=lambda: _NOW)
    if expired:
        assert await tracker.observe(review) == (None, "observed")
        state = await store.read_state(_KEY)
        assert state is not None and len(state["shapes"]) == 1
    else:
        with pytest.raises(RuntimeError, match="capacity exhausted"):
            await tracker.observe(review)


async def test_contention_stops_at_the_explicit_retry_budget() -> None:
    class RejectStore(InMemoryStateStore):
        attempts = 0

        async def write_state_if_absent(self, key: str, value: object) -> bool:
            self.attempts += 1
            return False

    store = RejectStore()
    tracker = RecurrentQueryTracker(store=store, now=lambda: _NOW)
    with pytest.raises(RuntimeError, match="contention budget exhausted"):
        await tracker.observe(await _review("alice"))
    assert store.attempts == 16


async def test_owner_observation_has_a_total_deadline() -> None:
    class HangingStore(InMemoryStateStore):
        async def read_state(self, key: str):
            await asyncio.Event().wait()

    norns = Norns(
        operational_state_store=HangingStore(),
        clock=lambda: _NOW,
        provider_timeout_seconds=0.02,
    )
    with pytest.raises(TimeoutError):
        await norns._observe_recurrent_query(await _review("alice"))


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), True])
def test_owner_deadline_rejects_non_finite_or_boolean_bindings(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout MUST"):
        Norns(provider_timeout_seconds=timeout)
