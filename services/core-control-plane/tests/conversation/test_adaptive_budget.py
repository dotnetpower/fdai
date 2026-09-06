"""Deterministic budget and degraded-answer coverage for adaptive conversations."""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest
from fdai.core.conversation.adaptive_models import AdaptiveEvidence, AdaptivePolicy
from fdai.core.conversation.adaptive_service import (
    AdaptiveConversationService,
    AdaptiveOutcome,
    AdaptiveUnavailable,
)
from fdai.core.conversation.model_observation import ConversationModelResponse
from fdai_service_contracts.ontology_query import EvidenceAuthority

from tests.conversation.test_adaptive_service import (
    _PROMPTS,
    _draft,
    _Model,
    _plan,
    _profile,
    _review,
    _unavailable,
)


class _Clock:
    value = 0.0

    def __call__(self) -> float:
        return self.value


class _TimedModel(_Model):
    def __init__(self, clock: _Clock, **replies: Mapping[str, object] | None) -> None:
        super().__init__(**replies)
        self.clock = clock

    async def complete(self, **kwargs) -> ConversationModelResponse | None:
        self.clock.value += 15 if kwargs["stage"] == "plan" else 10
        return await super().complete(**kwargs)


async def test_optional_reads_reserve_enough_turn_time_for_answer_and_review() -> None:
    clock = _Clock()
    plan = _plan(example=True)
    plan["goals"] = [
        {"goal_id": "explain", "kind": "knowledge", "question": "Compare", "required": True},
        {
            "goal_id": "example",
            "kind": "environment_example",
            "question": "Example one",
            "required": False,
        },
        {
            "goal_id": "second",
            "kind": "environment_example",
            "question": "Example two",
            "required": False,
        },
    ]
    model = _TimedModel(clock, plan=plan, answer=_draft(), review=_review())
    reads: list[str] = []

    async def read(question: str) -> AdaptiveEvidence:
        reads.append(question)
        clock.value += 5
        return AdaptiveEvidence(status="unavailable", limitation="source_unavailable")

    service = AdaptiveConversationService(
        model=model,
        profile_resolver=_profile,
        prompts=_PROMPTS,
        clock=clock,
    )
    result = await service.respond(
        utterance="Compare with examples",
        history=(),
        locale="en",
        target_agent="Bragi",
        relationship=None,
        read_evidence=read,
    )
    assert isinstance(result, AdaptiveOutcome)
    assert result.answer.goals[0].status == "answered"
    assert reads == ["Example one"]
    assert result.answer.goals[2].limitation == "adaptive_evidence_budget_exhausted"
    assert [call["stage"] for call in model.calls] == ["plan", "answer", "review"]


async def test_a_result_arriving_after_the_total_deadline_cannot_start_another_stage() -> None:
    clock = _Clock()
    model = _TimedModel(clock, plan=_plan(), answer=_draft(), review=_review())
    service = AdaptiveConversationService(
        model=model,
        profile_resolver=_profile,
        prompts=_PROMPTS,
        clock=clock,
        policy=AdaptivePolicy(total_seconds=10, per_stage_seconds=10),
    )
    result = await service.respond(
        utterance="Compare",
        history=(),
        locale="en",
        target_agent="Bragi",
        relationship=None,
        read_evidence=_unavailable,
    )
    assert isinstance(result, AdaptiveUnavailable)
    assert [call["stage"] for call in model.calls] == ["plan"]
    assert len(result.observations) == 1


async def test_failed_refinement_is_counted_and_never_retried() -> None:
    model = _Model(plan=_plan(), answer=_draft("Unsafe"), review=_review(safe=False))
    service = AdaptiveConversationService(model=model, profile_resolver=_profile, prompts=_PROMPTS)
    result = await service.respond(
        utterance="Compare",
        history=(),
        locale="en",
        target_agent="Bragi",
        relationship=None,
        read_evidence=_unavailable,
    )
    assert isinstance(result, AdaptiveOutcome)
    assert result.answer.refinements == 1
    assert result.answer.quality_status == "limited"
    assert "Unsafe" not in result.answer.answer
    assert [call["stage"] for call in model.calls] == ["plan", "answer", "review", "refine"]


async def test_oversized_context_is_rejected_before_any_model_call() -> None:
    model = _Model(plan=_plan())
    service = AdaptiveConversationService(model=model, profile_resolver=_profile, prompts=_PROMPTS)
    result = await service.respond(
        utterance="x" * 64000,
        history=(),
        locale="en",
        target_agent="Bragi",
        relationship=None,
        read_evidence=_unavailable,
    )
    assert isinstance(result, AdaptiveUnavailable)
    assert model.calls == []


@pytest.mark.parametrize("fence_length", [100, 11000])
async def test_fallback_evidence_budget_includes_markdown_delimiters(fence_length: int) -> None:
    content = json.dumps({"text": "`" * fence_length})

    async def read(question: str) -> AdaptiveEvidence:
        return AdaptiveEvidence(
            status="answered",
            content=content,
            evidence_refs=("configuration:example",),
            authorities=(EvidenceAuthority.SERVER_INVENTORY_GRAPH,),
        )

    service = AdaptiveConversationService(
        model=_Model(plan=_plan(example=True)),
        profile_resolver=_profile,
        prompts=_PROMPTS,
    )
    result = await service.respond(
        utterance="Compare with an example",
        history=(),
        locale="en",
        target_agent="Bragi",
        relationship=None,
        read_evidence=read,
    )
    assert isinstance(result, AdaptiveOutcome)
    assert len(result.answer.answer) <= 14000
    goal = result.answer.goals[1]
    if fence_length == 100:
        assert content in result.answer.answer
        assert goal.status == "answered"
    else:
        assert goal.status == "unavailable"
        assert goal.limitation == "adaptive_evidence_render_budget_exhausted"
        assert goal.evidence_refs == ()
