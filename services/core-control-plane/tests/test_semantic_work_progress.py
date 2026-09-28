"""Work progress emission: the plan-time pin, turn budget telemetry, and context receipts."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fdai.core.conversation.adaptive_call_scope import AdaptiveBudgetExceededError
from fdai.core.conversation.adaptive_models import DEFAULT_ADAPTIVE_POLICY
from fdai.core.conversation.adaptive_service import AdaptiveBudgetTelemetry, _Budget
from fdai.core.conversation.model_observation import ConversationModelObservation
from fdai.core.conversation.semantic_runtime import _resolve_progress_observer
from fdai.core.conversation.work_progress import (
    bind_semantic_work_progress_publisher,
    publish_work_progress_pin,
    record_semantic_work_progress,
)
from fdai.core.ontology_platform.query_execution import QueryNodeProgress
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai_core_service.semantic_turn_consumer import consume_semantic_turns
from fdai_core_service.semantic_work_progress_projection import work_progress_payload
from fdai_service_contracts import QueryNodeKind, SemanticQueryProgress
from fdai_service_contracts.ontology_query import OntologyQueryNode
from fdai_service_contracts.semantic_work_progress import (
    SemanticWorkProgress,
    TurnBudgetTelemetry,
    WorkProgressShape,
    parse_context_receipts,
)

from tests.test_semantic_turn_processor import (
    NOW,
    _processor,
    _projection,
    _request,
    _Runtime,
    _runtime_result,
)


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def _observation(total_tokens: int) -> ConversationModelObservation:
    return ConversationModelObservation(
        model="author-test",
        usage={"total_tokens": total_tokens},
        trace_call={},
    )


def _plan(*nodes: tuple[str, tuple[str, ...]]) -> Any:
    return SimpleNamespace(
        nodes=tuple(SimpleNamespace(node_id=node_id, depends_on=deps) for node_id, deps in nodes)
    )


def _payload_budget(telemetry: AdaptiveBudgetTelemetry | None) -> dict[str, object] | None:
    fields = work_progress_payload(
        shape=None,
        turn_budget=telemetry,
        context_receipts=(),
        as_of=NOW,
    )
    budget = fields.get("turn_budget")
    if budget is None:
        return None
    TurnBudgetTelemetry.model_validate(budget)
    return cast(dict[str, object], budget)


def test_budget_reports_measured_tokens_and_keeps_unmeasured_reservations() -> None:
    clock = _Clock()
    budget = _Budget(DEFAULT_ADAPTIVE_POLICY, clock=clock)
    measured = budget.reserve(1000, 4096, 0)
    budget.observe(measured, _observation(900))
    budget.reserve(2000, 4096, 0)
    clock.value = 3.25

    telemetry = budget.telemetry()

    assert telemetry == AdaptiveBudgetTelemetry(
        calls=2,
        max_calls=5,
        tokens_used=900,
        tokens_reserved=6096,
        max_tokens=48000,
        elapsed_ms=3250,
        max_elapsed_ms=60000,
        complete=False,
        exhaustion_reason=None,
    )
    assert _payload_budget(telemetry) == {
        "schema_version": 1,
        "model_calls": {"used": 2, "reserved": 0, "maximum": 5},
        "tokens": {"used": 900, "reserved": 6096, "maximum": 48000},
        "elapsed_ms": {"used": 3250, "reserved": 0, "maximum": 60000},
        "as_of": NOW.isoformat(timespec="milliseconds"),
        "complete": False,
    }


def test_observed_token_overshoot_is_the_exhaustion_reason() -> None:
    budget = _Budget(DEFAULT_ADAPTIVE_POLICY, clock=_Clock())
    reservation = budget.reserve(1000, 4096, 0)

    with pytest.raises(AdaptiveBudgetExceededError):
        budget.observe(reservation, _observation(50_000))

    telemetry = budget.telemetry()
    assert telemetry is not None
    assert (telemetry.tokens_used, telemetry.exhaustion_reason) == (50_000, "tokens")
    assert _payload_budget(telemetry) is not None


def test_a_later_overshoot_replaces_an_earlier_call_limit_as_the_reason() -> None:
    budget = _Budget(DEFAULT_ADAPTIVE_POLICY, clock=_Clock())
    for _ in range(3):
        budget.observe(budget.reserve(100, 256, 0), _observation(100))
    with pytest.raises(AdaptiveBudgetExceededError):
        budget.reserve(100, 256, 2)
    reservation = budget.reserve(100, 256, 0)
    with pytest.raises(AdaptiveBudgetExceededError):
        budget.observe(reservation, _observation(60_000))

    telemetry = budget.telemetry()
    assert telemetry is not None
    assert budget.limit_hits == ["model_calls", "tokens"]
    assert telemetry.exhaustion_reason == "tokens"
    assert _payload_budget(telemetry) is not None


def test_a_call_limit_without_overshoot_is_reported_as_model_calls() -> None:
    budget = _Budget(DEFAULT_ADAPTIVE_POLICY, clock=_Clock())
    for _ in range(5):
        budget.observe(budget.reserve(100, 256, 0), _observation(100))
    with pytest.raises(AdaptiveBudgetExceededError):
        budget.reserve(100, 256, 0)

    telemetry = budget.telemetry()
    assert telemetry is not None
    assert (telemetry.calls, telemetry.exhaustion_reason) == (5, "model_calls")
    assert _payload_budget(telemetry) is not None


def test_a_passed_deadline_is_noticed_after_it_passes() -> None:
    clock = _Clock()
    budget = _Budget(DEFAULT_ADAPTIVE_POLICY, clock=clock)
    clock.value = 60.82

    with pytest.raises(AdaptiveBudgetExceededError):
        budget.reserve(100, 256, 0)

    telemetry = budget.telemetry()
    assert telemetry is not None
    assert (telemetry.elapsed_ms, telemetry.exhaustion_reason) == (60_820, "deadline")
    assert _payload_budget(telemetry) is not None


def test_a_governed_timeout_ends_the_turn_by_deadline_even_on_the_boundary() -> None:
    clock = _Clock()
    budget = _Budget(DEFAULT_ADAPTIVE_POLICY, clock=clock)
    budget.observe(budget.reserve(100, 256, 0), _observation(100))
    with pytest.raises(AdaptiveBudgetExceededError):
        budget.reserve(100, 256, 5)
    clock.value = 60.0

    budget.end_turn(TimeoutError())

    telemetry = budget.telemetry()
    assert telemetry is not None
    assert (telemetry.elapsed_ms, telemetry.exhaustion_reason) == (60_000, "deadline")


def test_tokens_and_time_over_together_have_no_v1_representation() -> None:
    clock = _Clock()
    budget = _Budget(DEFAULT_ADAPTIVE_POLICY, clock=clock)
    reservation = budget.reserve(1000, 4096, 0)
    clock.value = 61.0
    with pytest.raises(AdaptiveBudgetExceededError):
        budget.observe(reservation, _observation(50_000))

    assert budget.telemetry() is None
    assert _payload_budget(budget.telemetry()) is None


async def test_the_first_pin_is_recorded_and_published_once() -> None:
    published: list[WorkProgressShape] = []

    async def publish(shape: WorkProgressShape) -> None:
        published.append(shape)

    with (
        bind_semantic_work_progress_publisher(publish),
        record_semantic_work_progress() as recorder,
    ):
        await publish_work_progress_pin(_plan(("a", ()), ("b", ()), ("c", ("a", "b"))))
        await publish_work_progress_pin(_plan(("other", ())))

    expected = WorkProgressShape(density="procedural", waves=2, planned_reads=3)
    assert recorder.shape == expected
    assert published == [expected]


async def test_an_unbounded_plan_is_not_pinned_and_publication_is_best_effort() -> None:
    async def fail(_shape: WorkProgressShape) -> None:
        raise RuntimeError("broker unavailable")

    chain = tuple((f"n{index}", (f"n{index - 1}",) if index else ()) for index in range(9))
    with bind_semantic_work_progress_publisher(fail), record_semantic_work_progress() as recorder:
        await publish_work_progress_pin(_plan(*chain))
        assert recorder.shape is None
        await publish_work_progress_pin(_plan(("only", ())))

    assert recorder.shape == WorkProgressShape(density="compact", waves=1, planned_reads=1)


class _PinningRuntime(_Runtime):
    def __init__(
        self, result: Any = None, *, budget: AdaptiveBudgetTelemetry | None = None, **kw: Any
    ):
        super().__init__(result, **kw)
        self.budget = budget

    async def handle(self, **kwargs: Any) -> Any:
        await publish_work_progress_pin(_plan(("resources", ())))
        observer = _resolve_progress_observer(None)
        if observer is not None:
            await observer(
                QueryNodeProgress(
                    node=OntologyQueryNode(
                        node_id="resources",
                        kind=QueryNodeKind.OBJECT_SET,
                        output_kind="object_set",
                    ),
                    status="running",
                    started_at=NOW,
                    step_index=1,
                    step_total=1,
                )
            )
        result = await super().handle(**kwargs)
        return replace(result, turn_budget=self.budget)


_TELEMETRY = AdaptiveBudgetTelemetry(
    calls=3,
    max_calls=5,
    tokens_used=4382,
    tokens_reserved=0,
    max_tokens=48000,
    elapsed_ms=3136,
    max_elapsed_ms=60000,
    complete=True,
    exhaustion_reason=None,
)


async def test_projection_persists_the_pin_budget_and_applied_tier_receipt() -> None:
    runtime = _PinningRuntime(_runtime_result("answered"), budget=_TELEMETRY)

    encoded = await _processor(runtime).process(_request(conversation_model_tier="t2"))
    payload = _projection(encoded)["payload"]

    assert payload["work_progress_shape"] == {
        "schema_version": 1,
        "density": "compact",
        "waves": 1,
        "planned_reads": 1,
    }
    budget = TurnBudgetTelemetry.model_validate(payload["turn_budget"])
    assert budget.model_calls.used == 3
    assert "exhaustion_reason" not in payload["turn_budget"]
    (receipt,) = parse_context_receipts(payload["context_receipts"])
    assert (receipt.kind, receipt.preference, receipt.value.value) == (
        "operator_preference",
        "conversation_model_tier",
        "t2",
    )
    assert receipt.observed_at == NOW
    assert receipt.freshness == "fresh"


async def test_projection_reports_nothing_that_did_not_happen() -> None:
    encoded = await _processor(_Runtime(_runtime_result("answered"))).process(_request())
    payload = _projection(encoded)["payload"]

    assert "work_progress_shape" not in payload
    assert "turn_budget" not in payload
    assert "context_receipts" not in payload


async def test_a_deadline_hold_keeps_the_published_pin_without_unapplied_context() -> None:
    runtime = _PinningRuntime(wait_for_cancel=True)
    request = _request(
        conversation_model_tier="t1",
        deadline_at=NOW + timedelta(milliseconds=50),
    )

    encoded = await _processor(runtime).process(request)
    projection = _projection(encoded)

    assert projection["semantic_result"]["reason_code"] == "semantic_deadline_exceeded"
    assert projection["payload"]["work_progress_shape"]["density"] == "compact"
    assert "context_receipts" not in projection["payload"]
    assert "turn_budget" not in projection["payload"]


async def test_the_live_pin_precedes_the_first_node_progress_on_the_progress_topic() -> None:
    bus = InMemoryEventBus()
    await bus.publish("operator.request", "one", _request(idempotency_key="pin-order"))

    await consume_semantic_turns(
        bus=bus,
        request_topic="operator.request",
        projection_topic="operator.projection",
        group_id="core-semantic",
        processor=_processor(_PinningRuntime(_runtime_result("answered"))),
        stop=asyncio.Event(),
    )

    records = [
        item.payload async for item in bus.subscribe("core.semantic-turn.progress", "assert")
    ]
    pin = SemanticWorkProgress.model_validate(records[0])
    node = SemanticQueryProgress.model_validate(records[1])
    assert (pin.progress_sequence, node.progress_sequence) == (1, 2)
    assert pin.request_id == node.request_id
    assert pin.work_progress_shape.density == "compact"
    assert pin.execution_authority is False


def _read_runtime(model: Any) -> tuple[Any, list[str]]:
    from fdai.core.conversation.semantic_runtime import SemanticConversationRuntime
    from fdai.core.ontology_platform import OntologyQueryPlanExecutor, QueryNodeResult
    from fdai_service_contracts.ontology_query import EvidenceAuthority

    from tests.conversation.test_adaptive_service import _service as answer_service
    from tests.conversation.test_semantic_planning import NOW as PLAN_NOW
    from tests.conversation.test_semantic_planning import (
        _fixture,
        _frame,
    )
    from tests.conversation.test_semantic_planning import _Model as QueryModel
    from tests.conversation.test_semantic_planning import _plan as query_plan
    from tests.conversation.test_semantic_planning import _service as query_service

    manifest, definition = _fixture()
    reads: list[str] = []

    async def handler(node: OntologyQueryNode, dependencies: Any) -> QueryNodeResult:
        reads.append(node.node_id)
        return QueryNodeResult(
            value={"recorded_configuration": {"revisions": 2}},
            evidence_refs=("inventory:verified-example",),
            authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
        )

    runtime = SemanticConversationRuntime(
        planner=query_service(QueryModel(frame=_frame(), plan=query_plan(definition)), manifest),
        executor=OntologyQueryPlanExecutor(
            handlers={QueryNodeKind.OBJECT_SET: handler}, now=lambda: PLAN_NOW
        ),
        adaptive_service=answer_service(model),
    )
    return runtime, reads


async def test_adaptive_evidence_reads_are_never_pinned() -> None:
    from fdai.core.conversation.session import Principal, Role

    from tests.conversation.test_adaptive_service import _Model as AnswerModel
    from tests.conversation.test_adaptive_service import _plan as answer_plan
    from tests.conversation.test_adaptive_service import _review

    model = AnswerModel(
        plan=answer_plan(example=True),
        answer={"sections": [{"goal_id": "explain", "text": "A canary shifts traffic."}]},
        review=_review(),
    )
    runtime, reads = _read_runtime(model)

    with record_semantic_work_progress() as recorder:
        result = await runtime.handle(
            utterance="Hello, compare deployment strategies with an environment example.",
            prior_turns=(),
            principal=Principal(id="operator", role=Role.READER),
        )

    assert result.disposition == "advisory_response"
    assert reads == ["resources"]
    assert recorder.shape is None
    assert result.turn_budget is None


async def test_the_deferred_governed_plan_is_pinned_and_carries_its_turn_budget() -> None:
    from fdai.core.conversation.session import Principal, Role

    from tests.conversation.test_adaptive_service import _Model as AnswerModel
    from tests.conversation.test_adaptive_service import _plan as answer_plan

    runtime, reads = _read_runtime(
        AnswerModel(plan={**answer_plan(), "route": "legacy", "goals": []})
    )

    with record_semantic_work_progress() as recorder:
        result = await runtime.handle(
            utterance="Read the current state.",
            prior_turns=(),
            principal=Principal(id="operator", role=Role.READER),
        )

    assert result.disposition == "answered"
    assert reads == ["resources"]
    assert recorder.shape == WorkProgressShape(density="compact", waves=1, planned_reads=1)
    assert result.turn_budget is not None
    assert (result.turn_budget.calls, result.turn_budget.max_calls) == (1, 5)
    assert result.turn_budget.exhaustion_reason is None
    assert _payload_budget(result.turn_budget) is not None
