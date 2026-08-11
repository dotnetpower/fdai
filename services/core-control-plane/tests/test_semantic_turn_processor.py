"""Focused Core semantic-turn v1.2 processor and lifecycle tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from types import MappingProxyType, SimpleNamespace
from typing import Any, cast

import pytest
from fdai.core.conversation.semantic_runtime import (
    SemanticTurnResult as RuntimeSemanticTurnResult,
)
from fdai.core.conversation.session import Principal, Role, Turn
from fdai.core.ontology_platform import QueryPlanExecution
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_core_service.semantic_turn_consumer import (
    StateStoreSemanticTurnResultStore,
    consume_semantic_turns,
    semantic_turn_binding_from_config,
)
from fdai_core_service.semantic_turn_processor import (
    SemanticTurnProcessor,
    SemanticTurnRejectedError,
)
from fdai_service_contracts.ontology_query import (
    GoalEvidenceMode,
    GoalTaskReceipt,
    TaskStatus,
)

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
RELEASE_DIGEST = "sha256:" + ("a" * 64)
MANIFEST_DIGEST = "sha256:" + ("b" * 64)
PLAN_DIGEST = "sha256:" + ("c" * 64)


class _Runtime:
    def __init__(
        self,
        result: RuntimeSemanticTurnResult | None = None,
        *,
        failure: Exception | None = None,
        wait_for_cancel: bool = False,
    ) -> None:
        self.result = result or _runtime_result("held")
        self.failure = failure
        self.wait_for_cancel = wait_for_cancel
        self.calls = 0
        self.principals: list[Principal] = []
        self.prior_turns: tuple[Turn, ...] = ()

    async def handle(
        self,
        *,
        utterance: str,
        prior_turns: tuple[Turn, ...],
        principal: Principal,
        cancelled: asyncio.Event | None = None,
    ) -> RuntimeSemanticTurnResult:
        assert utterance == "Show current operations evidence."
        self.calls += 1
        self.principals.append(principal)
        self.prior_turns = prior_turns
        if self.failure is not None:
            raise self.failure
        if self.wait_for_cancel:
            assert cancelled is not None
            await cancelled.wait()
            return _runtime_result("cancelled")
        return self.result


def _request(
    *,
    roles: list[str] | None = None,
    purpose: str = "operations-review",
    deadline_at: datetime | None = None,
    cancelled: bool = False,
    idempotency_key: str = "semantic-turn-1",
    prior_turns: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "1.2.0",
        "request_id": "00000000-0000-0000-0000-000000000101",
        "correlation_id": "semantic-correlation-1",
        "idempotency_key": idempotency_key,
        "resource_ref": "operator-conversation:example",
        "request_kind": "semantic_query",
        "requested_at": NOW.isoformat(),
        "semantic_turn": {
            "utterance": "Show current operations evidence.",
            "principal": {
                "subject_id": "operator-1",
                "roles": roles or ["Reader"],
            },
            "session_id": "session-1",
            "turn_id": "turn-1",
            "turn_sequence": 3,
            "locale": "en",
            "purpose": purpose,
            "deadline_at": (deadline_at or NOW + timedelta(seconds=30)).isoformat(),
            "prior_turns": prior_turns or [],
            "cancelled": cancelled,
            "execution_authority": False,
        },
    }


def _processor(
    runtime: _Runtime | None,
    *,
    now: Any = lambda: NOW,
) -> SemanticTurnProcessor:
    return SemanticTurnProcessor(
        runtime=runtime,
        results=StateStoreSemanticTurnResultStore(InMemoryStateStore()),
        now=now,
    )


def _projection(encoded: bytes) -> dict[str, Any]:
    loaded = json.loads(encoded)
    assert isinstance(loaded, dict)
    return cast(dict[str, Any], loaded)


def _runtime_result(disposition: str) -> RuntimeSemanticTurnResult:
    plan = SimpleNamespace(
        ontology_release_digest=RELEASE_DIGEST,
        semantic_catalog_digest=MANIFEST_DIGEST,
        plan_digest=PLAN_DIGEST,
    )
    planning = SimpleNamespace(plan=plan, manifest_digest=MANIFEST_DIGEST)
    if disposition != "answered":
        return RuntimeSemanticTurnResult(
            disposition=cast(Any, disposition),
            reason="provider detail must not escape",
            planning=cast(Any, planning),
        )
    receipt = GoalTaskReceipt(
        task_id="query:resources",
        goal_id="resources",
        intent="object_set",
        capability="query.object_set",
        evidence_mode=GoalEvidenceMode.OPERATIONAL,
        status=TaskStatus.COMPLETED,
        duration_ms=5,
        evidence_refs=("inventory:evidence-1",),
        started_at=NOW,
        completed_at=NOW,
    )
    execution = QueryPlanExecution(
        plan_digest=PLAN_DIGEST,
        status="completed",
        results=MappingProxyType({}),
        receipts=(receipt,),
        output_node_ids=("resources",),
    )
    return RuntimeSemanticTurnResult(
        disposition="answered",
        reason="semantic_execution_completed",
        planning=cast(Any, planning),
        execution=execution,
        intent_graph={"schema_version": 2, "goals": []},
        intent_graph_evidence={"status": "completed", "goals": []},
    )


async def test_malformed_semantic_request_goes_to_dlq() -> None:
    bus = InMemoryEventBus()
    await bus.publish("operator.request", "bad", {"schema_version": "1.2.0"})

    await consume_semantic_turns(
        bus=bus,
        request_topic="operator.request",
        projection_topic="operator.projection",
        group_id="core-semantic",
        processor=_processor(None),
        stop=asyncio.Event(),
    )

    dlq = [item async for item in bus.subscribe("operator.request.dlq", "assert")]
    assert len(dlq) == 1
    assert dlq[0].payload["reason"] == "semantic_turn_rejected"


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        (["Reader"], Role.READER),
        (["Reader", "Contributor"], Role.CONTRIBUTOR),
        (["Reader", "Approver"], Role.APPROVER),
        (["BreakGlass", "Owner"], Role.OWNER),
    ],
)
async def test_authenticated_role_order_selects_highest_ordinary_role(
    roles: list[str],
    expected: Role,
) -> None:
    runtime = _Runtime()

    await _processor(runtime).process(_request(roles=roles))

    assert runtime.principals[0].role is expected


async def test_break_glass_only_and_caller_purpose_widening_are_rejected() -> None:
    processor = _processor(_Runtime())

    with pytest.raises(SemanticTurnRejectedError, match="semantic_break_glass_only"):
        await processor.process(_request(roles=["BreakGlass"]))
    with pytest.raises(SemanticTurnRejectedError, match="semantic_purpose_not_allowed"):
        await processor.process(_request(purpose="execution"))


async def test_prior_turns_map_to_existing_turn_without_content_rewrite() -> None:
    runtime = _Runtime()

    await _processor(runtime).process(
        _request(
            prior_turns=[
                {"role": "user", "content": "Earlier question"},
                {"role": "assistant", "content": "Earlier answer"},
            ]
        )
    )

    assert [(turn.direction, turn.content) for turn in runtime.prior_turns] == [
        ("inbound", "Earlier question"),
        ("outbound", "Earlier answer"),
    ]
    assert [turn.turn_id for turn in runtime.prior_turns] == [
        "turn-1:prior:0",
        "turn-1:prior:1",
    ]
    assert all(turn.timestamp == NOW for turn in runtime.prior_turns)


async def test_expired_deadline_and_pre_cancel_never_call_runtime() -> None:
    runtime = _Runtime()
    processor = _processor(runtime)

    expired = _projection(await processor.process(_request(deadline_at=NOW - timedelta(seconds=1))))
    cancelled = _projection(
        await _processor(runtime).process(_request(cancelled=True, idempotency_key="cancelled"))
    )

    assert expired["semantic_result"]["reason_code"] == "semantic_deadline_exceeded"
    assert cancelled["status"] == "cancelled"
    assert runtime.calls == 0


async def test_deadline_and_cancellation_interrupt_inflight_runtime() -> None:
    timeout_runtime = _Runtime(wait_for_cancel=True)
    realtime = datetime.now(UTC)
    timed_out = await _processor(
        timeout_runtime,
        now=lambda: datetime.now(UTC),
    ).process(_request(deadline_at=realtime + timedelta(milliseconds=20)))

    cancel_runtime = _Runtime(wait_for_cancel=True)
    cancel_event = asyncio.Event()
    pending = asyncio.create_task(
        _processor(cancel_runtime).process(
            _request(idempotency_key="inflight-cancel"),
            cancelled=cancel_event,
        )
    )
    await asyncio.sleep(0)
    cancel_event.set()
    cancelled = await pending

    assert _projection(timed_out)["semantic_result"]["reason_code"] == (
        "semantic_deadline_exceeded"
    )
    assert _projection(cancelled)["status"] == "cancelled"


async def test_duplicate_returns_exact_prior_projection_without_reexecution() -> None:
    runtime = _Runtime(_runtime_result("answered"))
    processor = _processor(runtime)
    request = _request()

    first = await processor.process(request)
    second = await processor.process(request)

    assert second == first
    assert runtime.calls == 1


async def test_answered_projection_requires_complete_exact_evidence() -> None:
    answered = _projection(
        await _processor(_Runtime(_runtime_result("answered"))).process(_request())
    )
    semantic = answered["semantic_result"]

    assert answered["status"] == "answered"
    assert semantic["ontology_release_digest"] == RELEASE_DIGEST
    assert semantic["principal_manifest_digest"] == MANIFEST_DIGEST
    assert semantic["plan_digest"] == PLAN_DIGEST
    assert semantic["execution_receipt_digest"].startswith("sha256:")
    assert semantic["evidence_refs"] == ["inventory:evidence-1"]
    assert semantic["checks_completed"] == semantic["checks_total"] == 1
    assert semantic["execution_authority"] is False


async def test_answered_runtime_without_evidence_is_held() -> None:
    runtime_result = _runtime_result("answered")
    assert runtime_result.execution is not None
    incomplete_execution = QueryPlanExecution(
        plan_digest=runtime_result.execution.plan_digest,
        status="completed",
        results=runtime_result.execution.results,
        receipts=tuple(
            receipt.model_copy(update={"evidence_refs": ()})
            for receipt in runtime_result.execution.receipts
        ),
        output_node_ids=runtime_result.execution.output_node_ids,
    )
    incomplete = RuntimeSemanticTurnResult(
        disposition="answered",
        reason=runtime_result.reason,
        planning=runtime_result.planning,
        execution=incomplete_execution,
        intent_graph=runtime_result.intent_graph,
        intent_graph_evidence=runtime_result.intent_graph_evidence,
    )

    projection = _projection(await _processor(_Runtime(incomplete)).process(_request()))

    assert projection["status"] == "held"
    assert projection["semantic_result"]["reason_code"] == "semantic_evidence_incomplete"


async def test_unavailable_and_internal_failure_are_detail_free_holds() -> None:
    unavailable = _projection(await _processor(None).process(_request()))
    failed = _projection(
        await _processor(_Runtime(failure=RuntimeError("secret provider response"))).process(
            _request(idempotency_key="failed")
        )
    )

    assert unavailable["semantic_result"]["reason_code"] == "semantic_runtime_unavailable"
    assert failed["semantic_result"]["reason_code"] == "semantic_runtime_failed"
    assert "secret" not in json.dumps(failed)


async def test_consumer_publishes_projection_and_dlqs_publish_failure() -> None:
    class _FailingProjectionBus(InMemoryEventBus):
        fail_projection = False

        async def publish(
            self,
            topic: str,
            key: str,
            payload: Mapping[str, Any],
        ) -> PublishReceipt:
            if self.fail_projection and topic == "operator.projection":
                raise RuntimeError("synthetic publish failure")
            return await super().publish(topic, key, payload)

    bus = _FailingProjectionBus()
    await bus.publish("operator.request", "one", _request(idempotency_key="one"))
    await consume_semantic_turns(
        bus=bus,
        request_topic="operator.request",
        projection_topic="operator.projection",
        group_id="core-semantic",
        processor=_processor(None),
        stop=asyncio.Event(),
    )
    projections = [item async for item in bus.subscribe("operator.projection", "assert")]
    assert projections[0].payload["status"] == "held"

    await bus.publish("operator.request", "two", _request(idempotency_key="two"))
    bus.fail_projection = True
    await consume_semantic_turns(
        bus=bus,
        request_topic="operator.request",
        projection_topic="operator.projection",
        group_id="core-semantic",
        processor=_processor(None),
        stop=asyncio.Event(),
    )
    dlq = [item async for item in bus.subscribe("operator.request.dlq", "assert")]
    assert dlq[-1].payload["reason"] == "semantic_turn_publish_failed"


def test_runtime_binding_is_optional_explicit_and_rejects_partial_transport() -> None:
    state_store = InMemoryStateStore()

    assert (
        semantic_turn_binding_from_config(
            state_store=state_store,
            runtime=None,
            config={},
        )
        is None
    )
    with pytest.raises(RuntimeError, match="topics MUST be configured together"):
        semantic_turn_binding_from_config(
            state_store=state_store,
            runtime=None,
            config={"FDAI_SEMANTIC_TURN_REQUEST_TOPIC": "operator.request"},
        )
    binding = semantic_turn_binding_from_config(
        state_store=state_store,
        runtime=None,
        config={
            "FDAI_SEMANTIC_TURN_REQUEST_TOPIC": "operator.request",
            "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC": "operator.projection",
        },
    )
    assert binding is not None
    assert binding.available is False
    assert binding.unavailable_reason == "semantic_runtime_unavailable"
