"""Each stage reserves its worst case before dispatch, so no stage starves a later one."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fdai.core.conversation import turn_reservations
from fdai.core.conversation.adaptive_call_scope import call_scoped_provider
from fdai.core.conversation.model_observation import ConversationModelObservation
from fdai.core.conversation.turn_reservations import (
    BUDGET_RESERVED_EXCEEDED,
    TURN_CANCELLED,
    PlannedStage,
    ReservationPlan,
    StageCost,
    TurnReservationHeldError,
    TurnReservationLedger,
    TurnStage,
    bind_turn_reservations,
    plan_capacity,
    semantic_reservation_plan,
    shadow_reservation_plan,
)
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.delivery.azure.llm.semantic_question_form import (
    AzureOpenAIQuestionFormConfig,
    AzureOpenAIQuestionFormModel,
)

from tests.conversation.test_semantic_reasoning_shadow import _Model, _quoted_form, _run

_CALL = StageCost(1, 100, 10, 1.0)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _plan() -> ReservationPlan:
    return ReservationPlan(
        (
            PlannedStage(TurnStage.JUDGMENT, _CALL, max_calls=2),
            PlannedStage(TurnStage.FRAME, _CALL),
            PlannedStage(TurnStage.PLAN, _CALL),
            PlannedStage(TurnStage.ANSWER_AUTHOR, StageCost(1, 900, 900, 9.0), conditional=True),
        )
    )


def _exact() -> StageCost:
    # Judgment, frame, and plan at their worst case, and nothing to spare.
    return StageCost(3, 300, 30, 3.0)


def test_a_stage_reserves_only_when_every_mandatory_stage_ahead_still_fits() -> None:
    ledger = TurnReservationLedger(_exact(), _plan(), clock=_Clock())

    record = ledger.reserve(TurnStage.JUDGMENT)

    assert record.charged == _CALL
    assert ledger.remaining() == StageCost(2, 200, 20, 2.0)


@pytest.mark.parametrize(
    "short",
    [
        StageCost(2, 300, 30, 3.0),
        StageCost(3, 299, 30, 3.0),
        StageCost(3, 300, 29, 3.0),
        StageCost(3, 300, 30, 2.9),
    ],
)
def test_one_unit_short_in_any_dimension_holds_before_any_call(short: StageCost) -> None:
    ledger = TurnReservationLedger(short, _plan(), clock=_Clock())

    with pytest.raises(TurnReservationHeldError) as held:
        ledger.reserve(TurnStage.JUDGMENT)

    assert held.value.reason == f"{BUDGET_RESERVED_EXCEEDED}:judgment"
    assert ledger.records == [] and ledger.holds == [held.value.reason]


def test_a_judgment_repair_cannot_spend_the_frame_and_plan_reservations() -> None:
    ledger = TurnReservationLedger(_exact(), _plan(), clock=_Clock())
    ledger.reconcile(ledger.reserve(TurnStage.JUDGMENT))

    with pytest.raises(TurnReservationHeldError, match="judgment"):
        ledger.reserve(TurnStage.JUDGMENT)

    ledger.reconcile(ledger.reserve(TurnStage.FRAME))
    ledger.reconcile(ledger.reserve(TurnStage.PLAN))
    assert ledger.holds == [f"{BUDGET_RESERVED_EXCEEDED}:judgment"]


def test_call_limits_and_unplanned_stages_hold_with_their_typed_reasons() -> None:
    roomy = StageCost(99, 9_999, 9_999, 99.0)
    ledger = TurnReservationLedger(roomy, _plan(), clock=_Clock())
    ledger.reserve(TurnStage.JUDGMENT)
    ledger.reserve(TurnStage.JUDGMENT)

    with pytest.raises(TurnReservationHeldError, match="judgment:calls"):
        ledger.reserve(TurnStage.JUDGMENT)
    with pytest.raises(TurnReservationHeldError, match="form:unplanned"):
        ledger.reserve(TurnStage.FORM)


def test_a_conditional_stage_reserves_only_when_it_runs() -> None:
    capacity = _exact() + StageCost(1, 900, 900, 9.0)
    ledger = TurnReservationLedger(_exact(), _plan(), clock=_Clock())
    for stage in (TurnStage.JUDGMENT, TurnStage.FRAME, TurnStage.PLAN):
        ledger.reconcile(ledger.reserve(stage))

    with pytest.raises(TurnReservationHeldError, match="answer_author"):
        ledger.reserve(TurnStage.ANSWER_AUTHOR)
    assert TurnReservationLedger(capacity, _plan()).reserve(TurnStage.ANSWER_AUTHOR)


def test_a_failed_call_keeps_its_whole_reservation_charged() -> None:
    ledger = TurnReservationLedger(_exact(), _plan(), clock=_Clock())
    record = ledger.reserve(TurnStage.JUDGMENT, StageCost(1, 40, 10))

    ledger.fail(record)

    assert record.status == "failed" and ledger.spent == _CALL
    with pytest.raises(ValueError, match="once"):
        ledger.reconcile(record)


def test_reconciliation_charges_measured_usage_and_keeps_an_overrun() -> None:
    clock = _Clock()
    ledger = TurnReservationLedger(StageCost(9, 9_999, 9_999, 99.0), _plan(), clock=clock)
    smaller = ledger.reserve(TurnStage.JUDGMENT, StageCost(1, 40, 10))
    clock.now = 0.5
    ledger.reconcile(smaller, output_tokens=4)
    larger = ledger.reserve(TurnStage.JUDGMENT, StageCost(1, 40, 10))
    clock.now = 3.0
    ledger.reconcile(larger, output_tokens=25)

    assert (smaller.status, smaller.charged) == ("reconciled", StageCost(1, 40, 4, 0.5))
    assert larger.status == "overrun"
    assert larger.charged == StageCost(1, 100, 25, 2.5)


async def test_a_cancelled_turn_reserves_nothing_more() -> None:
    ledger = TurnReservationLedger(_exact(), _plan(), clock=_Clock())
    async with bind_turn_reservations(ledger):
        assert turn_reservations.reserve_call("semantic-judgment", input_bytes=10, output_tokens=1)

    with pytest.raises(TurnReservationHeldError) as held:
        ledger.reserve(TurnStage.FRAME)
    assert held.value.reason == TURN_CANCELLED


def test_a_continuation_pass_reserves_from_the_same_ledger_and_a_new_turn_starts_fresh() -> None:
    plan = ReservationPlan((PlannedStage(TurnStage.FORM, _CALL, max_calls=3),))
    first_turn = TurnReservationLedger(plan_capacity(plan), plan, clock=_Clock())
    for _ in range(3):
        first_turn.reconcile(first_turn.reserve(TurnStage.FORM))

    with pytest.raises(TurnReservationHeldError, match="form:calls"):
        first_turn.reserve(TurnStage.FORM)
    later_turn = TurnReservationLedger(plan_capacity(plan), plan, clock=_Clock())
    assert later_turn.reserve(TurnStage.FORM).stage is TurnStage.FORM


def test_every_reviewed_plan_holds_its_own_worst_case() -> None:
    for plan in (
        semantic_reservation_plan(),
        shadow_reservation_plan(form_passes=3, repairs_per_pass=1, concept_calls=16),
    ):
        ledger = TurnReservationLedger(plan_capacity(plan), plan)
        for item in plan.stages:
            for _ in range(item.max_calls):
                ledger.reserve(item.stage)
        assert ledger.remaining() == StageCost()


async def test_the_provider_scope_holds_before_sending_and_reconciles_after() -> None:
    sent: list[str] = []

    async def operation() -> str:
        sent.append("sent")
        return "ok"

    ledger = TurnReservationLedger(_exact(), _plan(), clock=_Clock())
    async with bind_turn_reservations(ledger):
        result, reservation = await call_scoped_provider(
            operation, request={"m": 1}, output_tokens=10, stage="semantic-judgment"
        )
        assert result == "ok" and reservation is not None
        reservation.record(
            ConversationModelObservation("m", {"completion_tokens": 3}, {"kind": "judgment"})
        )
        with pytest.raises(TurnReservationHeldError):
            await call_scoped_provider(
                operation,
                request={"m": "x" * 400},
                output_tokens=10,
                stage="semantic-judgment",
            )

    assert sent == ["sent"]
    assert ledger.records[0].status == "reconciled"
    assert ledger.records[0].charged.output_tokens == 3


async def test_a_failed_provider_request_keeps_its_reservation() -> None:
    async def failing() -> str:
        raise RuntimeError("provider failed")

    ledger = TurnReservationLedger(_exact(), _plan(), clock=_Clock())
    async with bind_turn_reservations(ledger):
        with pytest.raises(RuntimeError):
            await call_scoped_provider(
                failing, request={}, output_tokens=1, stage="semantic-judgment"
            )

    assert [item.status for item in ledger.records] == ["failed"]


async def test_without_a_ledger_or_a_reviewed_label_nothing_is_reserved() -> None:
    async def operation() -> str:
        return "ok"

    assert await call_scoped_provider(operation, request={}, output_tokens=1) == ("ok", None)
    assert await call_scoped_provider(
        operation, request={}, output_tokens=1, stage="unreviewed-label"
    ) == ("ok", None)


class _Identity:
    async def get_token(self, audience: str) -> Any:
        return SimpleNamespace(token="not-a-real-token")


async def test_a_held_stage_stops_candidate_failover_without_any_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    target = ModelRequestTarget(
        endpoint="https://example.com",
        deployment="example-model",
        api_version="2024-06-01",
        auth_audience="https://example.com/.default",
        binding_id="binding-form",
    )
    adapter = AzureOpenAIQuestionFormModel(
        identity=_Identity(),  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        config=AzureOpenAIQuestionFormConfig(
            candidates=(target, target),
            form_system_prompt="Return the closed question form.",
            concept_system_prompt="Choose concepts.",
        ),
    )
    plan = ReservationPlan((PlannedStage(TurnStage.FORM, StageCost(1, 10, 10)),))
    ledger = TurnReservationLedger(plan_capacity(plan), plan)

    async with bind_turn_reservations(ledger):
        proposal = await adapter.propose_form(
            utterance="list my VMs", context=(), locale="en", pass_index=0, prior_goals=()
        )

    assert proposal is None
    assert requests == []
    assert ledger.holds == [f"{BUDGET_RESERVED_EXCEEDED}:form"]


class _ReservingModel(_Model):
    """Reserve each form call through the provider scope, as the adapter does."""

    async def propose_form(self, **kwargs: Any) -> dict[str, Any] | None:
        # A request far above the shadow's whole capacity, as an oversized context would be.
        size = len(json.dumps(kwargs, default=str)) + 10_000_000
        turn_reservations.reserve_call("semantic-question-form", input_bytes=size, output_tokens=1)
        return await super().propose_form(**kwargs)


async def test_the_shadow_reserves_from_its_own_ledger_and_reports_a_hold() -> None:
    within = await _run(_Model([_quoted_form()], {}))
    held = await _run(_ReservingModel([_quoted_form()], {}))

    assert not any(note.startswith(BUDGET_RESERVED_EXCEEDED) for note in within.notes)
    assert f"{BUDGET_RESERVED_EXCEEDED}:form" in held.notes
    assert turn_reservations._LEDGER.get() is None


def test_every_shadow_stage_admits_every_call_the_shadow_can_reach() -> None:
    from fdai.core.conversation.semantic_reasoning_direction import MAX_DIRECTION_QUESTIONS

    plan = shadow_reservation_plan(form_passes=3, repairs_per_pass=1, concept_calls=16)
    limits = {item.stage: item.max_calls for item in plan.stages}

    assert turn_reservations.DIRECTION_QUESTIONS_PER_PASS == MAX_DIRECTION_QUESTIONS
    # Four passes (three form passes and the review repair pass), each with a first reader
    # and a tie-break per directional relation.
    assert limits[TurnStage.DIRECTION_READER] == 4 * MAX_DIRECTION_QUESTIONS * 2
    assert limits[TurnStage.BLIND_REVIEW] == 4
    ledger = TurnReservationLedger(plan_capacity(plan), plan)
    for _ in range(2 * 2):  # Two disputed relations: two first readers and two tie-breaks.
        ledger.reserve(TurnStage.DIRECTION_READER)
    assert ledger.holds == []
