"""Deterministic budget and degraded-answer coverage for adaptive conversations."""

from __future__ import annotations

import json
import logging
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


async def test_stage_timing_reports_real_elapsed_work_without_prompt_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = _Clock()
    service = AdaptiveConversationService(
        model=_TimedModel(clock, plan=_plan(), answer=_draft(), review=_review()),
        profile_resolver=_profile,
        prompts=_PROMPTS,
        clock=clock,
    )
    with caplog.at_level(logging.INFO):
        await service.respond(
            utterance="PRIVATE-QUESTION-CONTENT",
            history=(),
            locale="en",
            target_agent="Bragi",
            relationship=None,
            read_evidence=_unavailable,
        )
    records = [r for r in caplog.records if r.message == "adaptive_stage_completed"]
    assert [r.stage for r in records] == ["plan", "answer", "review"]
    assert [r.duration_ms for r in records] == [15000, 10000, 10000]
    assert [r.remaining_ms for r in records] == [45000, 35000, 25000]
    assert all(r.status == "completed" for r in records)
    assert "PRIVATE-QUESTION-CONTENT" not in caplog.text


async def test_schema_cache_reuses_compilation_without_sharing_mutable_provider_input() -> None:
    from fdai.core.conversation.adaptive_service import _stage_schema_json

    from tests.conversation.test_adaptive_service import _run

    _stage_schema_json.cache_clear()
    model = _Model(plan=_plan(), answer=_draft(), review=_review())
    await _run(model)
    assert _stage_schema_json.cache_info().misses == 3
    model.calls[0]["schema"]["properties"].clear()
    await _run(model)
    assert _stage_schema_json.cache_info().misses == 3
    assert _stage_schema_json.cache_info().hits == 3
    assert "goals" in model.calls[3]["schema"]["properties"]


async def test_initial_knowledge_draft_removes_one_call_but_keeps_independent_review() -> None:
    from tests.conversation.test_adaptive_service import _run

    model = _Model(plan={**_plan(), "draft": _draft()}, review=_review())
    result = await _run(model)
    assert isinstance(result, AdaptiveOutcome)
    assert "canary" in result.answer.answer
    assert [call["stage"] for call in model.calls] == ["plan", "review"]
    assert "draft" not in model.calls[1]["payload"]["plan"]


@pytest.mark.parametrize(
    "change",
    [
        {"route": "legacy", "action_requested": True},
        {"context_dependency": "pending_decision"},
        {
            "goals": [
                {
                    "goal_id": "explain",
                    "kind": "knowledge",
                    "question": "Explain",
                    "required": True,
                },
                {
                    "goal_id": "example",
                    "kind": "environment_example",
                    "question": "Example",
                    "required": False,
                },
            ]
        },
        {"draft": {"sections": [{"goal_id": "wrong", "text": "Unsupported"}]}},
    ],
)
def test_initial_draft_cannot_bypass_evidence_or_action_boundaries(change) -> None:
    from fdai.core.conversation.adaptive_models import AdaptivePlan

    with pytest.raises(ValueError):
        AdaptivePlan.model_validate({**_plan(), "draft": _draft(), **change})


@pytest.mark.parametrize("dependency", ["none", "active_thread"])
async def test_review_context_omits_history_only_after_typed_independence(dependency: str) -> None:
    model = _Model(
        plan={**_plan(), "context_dependency": dependency},
        answer=_draft(),
        review=_review(complete=False),
        refine=_draft(),
        verify=_review(),
    )
    service = AdaptiveConversationService(model=model, profile_resolver=_profile, prompts=_PROMPTS)
    history = ({"role": "user", "content": "Earlier context " * 100},)
    result = await service.respond(
        utterance="Compare rollout strategies",
        history=history,
        locale="en",
        target_agent="Bragi",
        relationship=None,
        read_evidence=_unavailable,
    )
    assert isinstance(result, AdaptiveOutcome)
    for call in model.calls:
        if call["stage"] in {"plan", "answer"}:
            assert call["payload"]["history"] == list(history)
        else:
            assert ("history" in call["payload"]) is (dependency == "active_thread")
            assert call["payload"]["utterance"] == "Compare rollout strategies"
            assert call["payload"]["draft"]["sections"]


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
