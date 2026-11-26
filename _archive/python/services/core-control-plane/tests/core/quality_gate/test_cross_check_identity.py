"""Cross-check agreement binds exact JSON, not Python equality or shared mutable inputs."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

import pytest
from fdai.core.quality_gate._verification import cross_check_candidate
from fdai.core.quality_gate.gate import (
    QualityCandidate,
    QualityGate,
    QualityGateConfig,
    QualityOutcome,
)
from fdai.core.quality_gate.rubric import RubricOutput
from fdai.core.quality_gate.testing import InMemoryGroundingSource, StaticVerifier
from pydantic import ValidationError


@dataclass
class Model:
    model_id: str
    params: Mapping[str, Any]
    calls: int = 0

    async def propose(self, candidate: QualityCandidate) -> tuple[str, Mapping[str, Any]]:
        self.calls += 1
        return candidate.action_type, self.params


def candidate(params: dict[str, Any]) -> QualityCandidate:
    return QualityCandidate(
        action_type="example.action",
        target_resource_ref="example/resource",
        params=params,
        cited_rule_ids=(),
        confidence_signals={"verified": 0.9},
    )


@pytest.mark.parametrize(
    ("expected", "proposed"),
    [
        ({"enabled": True}, {"enabled": 1}),
        ({"enabled": False}, {"enabled": 0}),
        ({"enabled": True}, {"enabled": 1.0}),
        ({"enabled": False}, {"enabled": 0.0}),
        ({"count": 1}, {"count": 1.0}),
        ({"count": 0.0}, {"count": -0.0}),
        ({"nested": {"enabled": True}}, {"nested": {"enabled": 1}}),
        ({"items": [True, False]}, {"items": [1, 0]}),
    ],
)
async def test_python_aliases_never_fabricate_two_model_agreement(
    expected: dict[str, Any], proposed: dict[str, Any]
) -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(Model("one", proposed), Model("two", proposed)),
        grounding=InMemoryGroundingSource({}),
        config=QualityGateConfig(require_grounding=False),
    )
    decision = await gate.evaluate(candidate(expected))
    assert decision.outcome is not QualityOutcome.ELIGIBLE
    assert not any(vote.agreed for vote in decision.model_votes)


async def test_exact_json_agreement_ignores_object_key_order() -> None:
    expected = {"nested": {"enabled": True, "count": 1}, "items": [None, "value"]}
    proposed = {"items": [None, "value"], "nested": {"count": 1, "enabled": True}}
    models = (Model("one", proposed), Model("two", proposed))
    result = await cross_check_candidate(candidate(expected), models)
    assert result.agree_count == 2
    assert all(model.calls == 1 for model in models)


@pytest.mark.parametrize(
    ("expected", "proposed"),
    [
        ({"items": [True]}, {"items": (True,)}),
        ({"items": (True,)}, {"items": [True]}),
        ({"nested": {"items": [1]}}, {"nested": {"items": (1,)}}),
    ],
)
async def test_normalization_cannot_turn_non_json_tuples_into_agreement(
    expected: dict[str, Any], proposed: dict[str, Any]
) -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(Model("one", proposed), Model("two", proposed)),
        grounding=InMemoryGroundingSource({}),
        config=QualityGateConfig(require_grounding=False),
    )
    decision = await gate.evaluate(candidate(expected))
    assert decision.outcome is not QualityOutcome.ELIGIBLE
    assert not decision.model_votes


@pytest.mark.parametrize("invalid", [{1: "value"}, {"nested": {True: "value"}}])
async def test_non_string_json_keys_cannot_be_admitted_as_matching_params(invalid) -> None:
    with pytest.raises(ValidationError) as raised:
        await cross_check_candidate(
            candidate(invalid), (Model("one", invalid), Model("two", invalid))
        )
    assert any(error["type"] == "string_type" for error in raised.value.errors())


async def test_models_receive_independent_inputs_and_cannot_mutate_the_original() -> None:
    seen: list[object] = []
    first_changed = asyncio.Event()

    class ChangingModel:
        model_id = "one"

        async def propose(self, value: QualityCandidate) -> tuple[str, Mapping[str, Any]]:
            value.params["nested"]["enabled"] = False
            value.confidence_signals["verified"] = 1.0  # type: ignore[index]
            first_changed.set()
            return value.action_type, value.params

    class ReadingModel:
        model_id = "two"

        async def propose(self, value: QualityCandidate) -> tuple[str, Mapping[str, Any]]:
            await first_changed.wait()
            seen.append(value.params["nested"]["enabled"])
            return value.action_type, value.params

    original = candidate({"nested": {"enabled": True}})
    result = await cross_check_candidate(original, (ChangingModel(), ReadingModel()))
    assert original.params == {"nested": {"enabled": True}}
    assert original.confidence_signals == {"verified": 0.9}
    assert seen == [True]
    assert result.agree_count == 1


@pytest.mark.parametrize("change", ["params", "confidence"])
async def test_caller_drift_during_model_await_holds_instead_of_rebinding(change: str) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    original = candidate({"enabled": True})

    class WaitingModel:
        def __init__(self, model_id: str) -> None:
            self.model_id = model_id

        async def propose(self, value: QualityCandidate) -> tuple[str, Mapping[str, Any]]:
            entered.set()
            await release.wait()
            return value.action_type, value.params

    pending = asyncio.create_task(
        cross_check_candidate(original, (WaitingModel("one"), WaitingModel("two")))
    )
    await entered.wait()
    if change == "params":
        original.params["enabled"] = 1
    else:
        original.confidence_signals["verified"] = 1.0  # type: ignore[index]
    release.set()
    with pytest.raises(ValueError, match="candidate.*changed"):
        await pending


async def test_completed_proposal_is_frozen_before_a_slower_model_finishes() -> None:
    proposal = {"value": "original"}
    first_returned = asyncio.Event()

    class FirstModel:
        model_id = "one"

        async def propose(self, value: QualityCandidate) -> tuple[str, Mapping[str, Any]]:
            first_returned.set()
            return value.action_type, proposal

    class SecondModel:
        model_id = "two"

        async def propose(self, value: QualityCandidate) -> tuple[str, Mapping[str, Any]]:
            await first_returned.wait()
            proposal["value"] = "changed"
            return value.action_type, {"value": "original"}

    result = await cross_check_candidate(
        candidate({"value": "original"}), (FirstModel(), SecondModel())
    )
    assert result.agree_count == 2


@pytest.mark.parametrize("change", ["params", "confidence", "nonfinite", "nonjson"])
async def test_later_rubric_cannot_change_a_cross_checked_candidate(change: str) -> None:
    expected = {"enabled": True}

    class ChangingRubric:
        async def score(self, value: QualityCandidate) -> RubricOutput:
            if change == "params":
                value.params["enabled"] = False
            elif change == "confidence":
                value.confidence_signals["verified"] = 1.0  # type: ignore[index]
            elif change == "nonfinite":
                value.params["enabled"] = float("nan")
            else:
                value.params["enabled"] = object()
            return RubricOutput()

    original = replace(candidate(expected), reasoning_trace="test grounded reasoning")
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(Model("one", expected), Model("two", expected)),
        grounding=InMemoryGroundingSource({}),
        config=QualityGateConfig(require_grounding=False),
        rubric_evaluator=ChangingRubric(),
    )
    decision = await gate.evaluate(original)
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert original.params == {"enabled": True}
    assert original.confidence_signals == {"verified": 0.9}
    assert decision.candidate.params == {"enabled": True}


async def test_caller_change_during_rubric_await_cannot_rebind_a_decision() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    expected = {"enabled": True}
    original = replace(candidate(dict(expected)), reasoning_trace="test grounded reasoning")

    class WaitingRubric:
        async def score(self, value: QualityCandidate) -> RubricOutput:
            entered.set()
            await release.wait()
            return RubricOutput()

    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(Model("one", expected), Model("two", expected)),
        grounding=InMemoryGroundingSource({}),
        config=QualityGateConfig(require_grounding=False),
        rubric_evaluator=WaitingRubric(),
    )
    pending = asyncio.create_task(gate.evaluate(original))
    await entered.wait()
    original.params["enabled"] = False
    release.set()
    decision = await pending
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert decision.candidate.params == {"enabled": True}


async def test_returned_decision_does_not_share_the_callers_nested_arguments() -> None:
    expected = {"nested": {"enabled": True}}
    original = candidate(expected)
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(Model("one", expected), Model("two", expected)),
        grounding=InMemoryGroundingSource({}),
        config=QualityGateConfig(require_grounding=False),
    )
    decision = await gate.evaluate(original)
    assert decision.outcome is QualityOutcome.ELIGIBLE
    original.params["nested"]["enabled"] = False
    assert decision.candidate.params == {"nested": {"enabled": True}}


async def test_cancellation_during_later_rubric_propagates_and_cleans_up() -> None:
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    expected = {"enabled": True}

    class BlockingRubric:
        async def score(self, value: QualityCandidate) -> RubricOutput:
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            return RubricOutput()

    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(Model("one", expected), Model("two", expected)),
        grounding=InMemoryGroundingSource({}),
        config=QualityGateConfig(require_grounding=False),
        rubric_evaluator=BlockingRubric(),
    )
    pending = asyncio.create_task(
        gate.evaluate(replace(candidate(expected), reasoning_trace="test reasoning"))
    )
    await entered.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert cancelled.is_set()


@pytest.mark.parametrize("change", ["params", "confidence"])
async def test_final_identity_guard_rejects_json_key_alias_during_later_await(change: str) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    expected = {"1": "value"}
    original = replace(
        candidate(dict(expected)),
        confidence_signals={"1": 0.9},
        reasoning_trace="test reasoning",
    )

    class WaitingRubric:
        async def score(self, value: QualityCandidate) -> RubricOutput:
            entered.set()
            await release.wait()
            return RubricOutput()

    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(Model("one", expected), Model("two", expected)),
        grounding=InMemoryGroundingSource({}),
        config=QualityGateConfig(require_grounding=False),
        rubric_evaluator=WaitingRubric(),
    )
    pending = asyncio.create_task(gate.evaluate(original))
    await entered.wait()
    if change == "params":
        original.params.clear()
        original.params[1] = "value"  # type: ignore[index]
    else:
        original.confidence_signals.clear()  # type: ignore[attr-defined]
        original.confidence_signals[1] = 0.9  # type: ignore[index]
    release.set()
    decision = await pending
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert decision.candidate.params == expected
    assert decision.candidate.confidence_signals == {"1": 0.9}
