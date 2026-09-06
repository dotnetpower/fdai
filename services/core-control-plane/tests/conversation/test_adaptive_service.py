"""Connected adaptive answer tests with deterministic injected models and verified reads."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

import pytest
from fdai.core.conversation.adaptive_models import (
    DEFAULT_ADAPTIVE_POLICY,
    AdaptiveEvidence,
    AdaptivePlan,
    AdaptivePolicy,
)
from fdai.core.conversation.adaptive_prompt import ConversationProfile
from fdai.core.conversation.adaptive_service import AdaptiveConversationService, AdaptiveDeferred
from fdai.core.conversation.model_observation import (
    ConversationModelObservation,
    ConversationModelResponse,
)
from fdai_service_contracts.ontology_query import EvidenceAuthority

_PROMPTS = {
    stage: f"Reviewed {stage} instructions."
    for stage in ("plan", "answer", "review", "refine", "verify")
}


def _plan(*, example: bool = False, required: bool = False) -> dict[str, object]:
    goals: list[dict[str, object]] = [
        {
            "goal_id": "explain",
            "kind": "knowledge",
            "question": "Compare rollout strategies.",
            "required": True,
        }
    ]
    if example:
        goals.append(
            {
                "goal_id": "example",
                "kind": "operational" if required else "environment_example",
                "question": "Read verified deployment configuration.",
                "required": required,
            }
        )
    return {
        "route": "adaptive",
        "social_act": "greeting",
        "context_dependency": "none",
        "action_requested": False,
        "goals": goals,
    }


def _draft(
    text: str = "Blue-green switches traffic; canary shifts it gradually.",
) -> dict[str, object]:
    return {"sections": [{"goal_id": "explain", "text": text}]}


def _review(*, safe: bool = True, complete: bool = True) -> dict[str, object]:
    return {
        "safe": safe,
        "complete": complete,
        "supported_goal_ids": ["explain"],
        "issues": [] if safe and complete else ["Improve the requested comparison."],
    }


class _Model:
    def __init__(self, **replies: Mapping[str, object] | None) -> None:
        self.replies = replies
        self.calls: list[dict[str, object]] = []

    async def complete(
        self,
        *,
        stage: str,
        system_prompt: str,
        payload: Mapping[str, object],
        schema: Mapping[str, object],
        escalated: bool = False,
    ) -> ConversationModelResponse | None:
        self.calls.append(
            {
                "stage": stage,
                "prompt": system_prompt,
                "payload": payload,
                "schema": schema,
                "escalated": escalated,
            }
        )
        reply = self.replies.get(stage)
        if reply is None:
            return None
        return ConversationModelResponse(
            proposal=reply,
            observation=ConversationModelObservation(
                model="reviewer-test" if stage in {"review", "verify"} else "author-test",
                usage={"total_tokens": 100},
                trace_call={},
            ),
        )


def _profile(
    agent: str, locale: str, relationship: Mapping[str, object] | None
) -> ConversationProfile:
    return ConversationProfile(
        agent=agent, locale=locale, role_directive="Explain without execution authority."
    )


def _service(
    model: _Model, policy: AdaptivePolicy = DEFAULT_ADAPTIVE_POLICY
) -> AdaptiveConversationService:
    return AdaptiveConversationService(
        model=model,
        profile_resolver=_profile,
        prompts=_PROMPTS,
        policy=policy,
    )


async def _unavailable(question: str) -> AdaptiveEvidence:
    return AdaptiveEvidence(status="unavailable", limitation="source_not_configured")


async def _run(
    model: _Model,
    *,
    reader=_unavailable,
    allow_refinement: bool = True,
    cancelled: asyncio.Event | None = None,
    policy: AdaptivePolicy = DEFAULT_ADAPTIVE_POLICY,
):
    return await _service(model, policy).respond(
        utterance="안녕, 블루-그린과 카나리를 비교해 줘.",
        history=(),
        locale="ko",
        target_agent="Bragi",
        relationship=None,
        read_evidence=reader,
        allow_refinement=allow_refinement,
        cancelled=cancelled,
    )


@pytest.mark.asyncio
async def test_general_explanation_uses_no_operational_query() -> None:
    model = _Model(plan=_plan(), answer=_draft(), review=_review())
    reads: list[str] = []

    async def reader(question: str) -> AdaptiveEvidence:
        reads.append(question)
        return await _unavailable(question)

    result = await _run(model, reader=reader)
    assert result is not None
    assert result.answer.quality_status == "passed"
    assert "canary" in result.answer.answer
    assert result.answer.goals[0].evidence_refs == ()
    assert result.answer.execution_authority is False
    assert reads == []
    assert [call["stage"] for call in model.calls] == ["plan", "answer", "review"]


@pytest.mark.asyncio
async def test_missing_optional_example_does_not_replace_the_answer_with_a_hold() -> None:
    result = await _run(_Model(plan=_plan(example=True), answer=_draft(), review=_review()))
    assert result is not None
    assert "canary" in result.answer.answer
    assert result.answer.goals[0].status == "answered"
    assert result.answer.goals[1].status == "unavailable"
    assert result.answer.goals[1].limitation == "source_not_configured"


@pytest.mark.asyncio
async def test_verified_example_uses_only_server_supplied_references() -> None:
    draft = _draft()
    draft["sections"] = [
        {"goal_id": "explain", "text": "A canary shifts traffic gradually."},
        {"goal_id": "example", "text": "The recorded example uses weighted traffic."},
    ]
    review = {**_review(), "supported_goal_ids": ["explain", "example"]}

    async def reader(question: str) -> AdaptiveEvidence:
        return AdaptiveEvidence(
            status="answered",
            content='{"weighted_traffic":true}',
            evidence_refs=("configuration:example",),
            authorities=(EvidenceAuthority.SERVER_INVENTORY_GRAPH,),
        )

    result = await _run(
        _Model(plan=_plan(example=True), answer=draft, review=review), reader=reader
    )
    assert result is not None
    assert result.answer.goals[1].status == "answered"
    assert result.answer.goals[1].evidence_refs == ("configuration:example",)
    assert result.answer.goals[0].evidence_refs == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("required", [False, True])
@pytest.mark.parametrize("missing_section", [False, True])
async def test_verified_evidence_without_supported_prose_preserves_the_general_answer(
    required: bool,
    missing_section: bool,
) -> None:
    async def reader(question: str) -> AdaptiveEvidence:
        return AdaptiveEvidence(
            status="answered",
            content='{"weighted_traffic":true}',
            evidence_refs=("configuration:example",),
            authorities=(EvidenceAuthority.SERVER_INVENTORY_GRAPH,),
        )

    draft = _draft()
    review = _review()
    if missing_section:
        review["supported_goal_ids"] = ["explain", "example"]
    else:
        draft["sections"] = [
            {"goal_id": "explain", "text": "A canary shifts traffic gradually."},
            {"goal_id": "example", "text": "Unsupported interpretation of the evidence."},
        ]
    result = await _run(
        _Model(plan=_plan(example=True, required=required), answer=draft, review=review),
        reader=reader,
        allow_refinement=False,
    )
    assert result is not None
    assert "canary" in result.answer.answer
    assert "Unsupported interpretation" not in result.answer.answer
    assert result.answer.goals[1].status == ("held" if required else "unavailable")
    assert result.answer.goals[1].limitation == "adaptive_goal_not_supported"
    assert result.answer.goals[1].evidence_refs == ()


@pytest.mark.asyncio
async def test_catalog_declarations_cannot_be_presented_as_environment_examples() -> None:
    async def reader(question: str) -> AdaptiveEvidence:
        return AdaptiveEvidence(
            status="answered",
            content='{"declaration":"Resource can have revisions"}',
            evidence_refs=("catalog:Resource",),
            authorities=(EvidenceAuthority.SERVER_ONTOLOGY_MANIFEST,),
        )

    model = _Model(
        plan=_plan(example=True),
        answer={
            "sections": [
                {"goal_id": "explain", "text": "Canary moves traffic gradually."},
                {"goal_id": "example", "text": "Your service has a configured canary."},
            ]
        },
        review={**_review(), "supported_goal_ids": ["explain", "example"]},
    )
    result = await _run(model, reader=reader)
    assert result is not None
    assert "Your service" not in result.answer.answer
    assert result.answer.goals[1].status == "unavailable"
    assert result.answer.goals[1].limitation == "environment_example_requires_runtime_evidence"


@pytest.mark.asyncio
async def test_required_operational_hold_cannot_become_a_model_invented_fact() -> None:
    draft = {
        "sections": [
            {"goal_id": "explain", "text": "A canary shifts traffic gradually."},
            {"goal_id": "example", "text": "The service is healthy."},
        ]
    }
    model = _Model(
        plan=_plan(example=True, required=True),
        answer=draft,
        review={**_review(), "supported_goal_ids": ["explain", "example"]},
    )
    result = await _run(model, allow_refinement=False)
    assert result is not None
    assert "service is healthy" not in result.answer.answer
    assert result.answer.goals[1].status == "held"
    assert result.answer.quality_status == "limited"


@pytest.mark.asyncio
async def test_unsafe_draft_gets_one_refinement_and_independent_verification() -> None:
    model = _Model(
        plan=_plan(),
        answer=_draft("Unconfirmed operational claims."),
        review=_review(safe=False),
        refine=_draft(),
        verify=_review(),
    )
    result = await _run(model)
    assert result is not None
    assert result.answer.refinements == 1
    assert result.answer.quality_status == "passed"
    assert "Unconfirmed" not in result.answer.answer
    assert [call["stage"] for call in model.calls] == [
        "plan",
        "answer",
        "review",
        "refine",
        "verify",
    ]
    assert [call["escalated"] for call in model.calls] == [False, False, False, True, False]


@pytest.mark.asyncio
async def test_review_issues_require_refinement_even_when_coverage_is_complete() -> None:
    model = _Model(
        plan=_plan(),
        answer=_draft("The comparison needs clearer tradeoffs."),
        review={**_review(), "issues": ["Explain rollback and traffic tradeoffs more clearly."]},
        refine=_draft(),
        verify=_review(),
    )
    result = await _run(model)
    assert result is not None
    assert result.answer.refinements == 1
    assert result.answer.quality_status == "passed"
    assert "canary" in result.answer.answer
    assert [call["stage"] for call in model.calls] == [
        "plan",
        "answer",
        "review",
        "refine",
        "verify",
    ]


@pytest.mark.asyncio
async def test_no_t2_profile_preserves_a_safe_but_incomplete_answer() -> None:
    model = _Model(plan=_plan(), answer=_draft(), review=_review(complete=False), refine=_draft())
    result = await _run(model, allow_refinement=False)
    assert result is not None
    assert result.answer.quality_status == "limited"
    assert [call["stage"] for call in model.calls] == ["plan", "answer", "review"]


@pytest.mark.asyncio
async def test_an_unreviewed_answer_never_masquerades_as_verified() -> None:
    result = await _run(_Model(plan=_plan(), answer=_draft("Unreviewed content")))
    assert result is not None
    assert result.answer.quality_status == "limited"
    assert "Unreviewed content" not in result.answer.answer
    assert all(goal.status != "answered" for goal in result.answer.goals)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value", [("action_requested", True), ("context_dependency", "pending_decision")]
)
async def test_action_and_pending_decision_continue_through_existing_governed_path(
    field, value
) -> None:
    model = _Model(plan={**_plan(), field: value})
    result = await _run(model)
    assert isinstance(result, AdaptiveDeferred)
    assert [call["stage"] for call in model.calls] == ["plan"]


@pytest.mark.asyncio
async def test_cancelled_turn_makes_no_model_call() -> None:
    cancelled = asyncio.Event()
    cancelled.set()
    model = _Model(plan=_plan())
    with pytest.raises(asyncio.CancelledError):
        await _run(model, cancelled=cancelled)
    assert model.calls == []


@pytest.mark.asyncio
async def test_cancellation_interrupts_an_active_model_before_its_deadline() -> None:
    started = asyncio.Event()
    stopped = asyncio.Event()
    cancelled = asyncio.Event()

    class SlowModel(_Model):
        async def complete(self, **kwargs):
            started.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()

    task = asyncio.create_task(_run(SlowModel(), cancelled=cancelled))
    await asyncio.wait_for(started.wait(), timeout=1)
    cancelled.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=0.2)
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_unknown_goal_in_draft_cannot_leak_unreviewed_sections() -> None:
    model = _Model(
        plan=_plan(),
        answer={"sections": [{"goal_id": "invented", "text": "Made-up answer"}]},
        review=_review(),
    )
    result = await _run(model, allow_refinement=False)
    assert result is not None
    assert "Made-up" not in result.answer.answer
    assert result.answer.quality_status == "limited"


def test_plan_rejects_duplicate_goals_and_required_optional_examples() -> None:
    plan = _plan(example=True)
    goal = {
        "goal_id": "example",
        "kind": "environment_example",
        "question": "Read",
        "required": True,
    }
    with pytest.raises(ValueError):
        AdaptivePlan.model_validate({**plan, "goals": [goal]})


def test_required_knowledge_cannot_silently_select_an_operational_only_route() -> None:
    proposal = {**_plan(), "route": "legacy"}
    with pytest.raises(ValueError, match="knowledge goals require the adaptive route"):
        AdaptivePlan.model_validate(proposal)
    assert AdaptivePlan.model_validate({**proposal, "action_requested": True}).action_requested
    assert (
        AdaptivePlan.model_validate(
            {
                **proposal,
                "context_dependency": "pending_decision",
            }
        ).context_dependency
        == "pending_decision"
    )
