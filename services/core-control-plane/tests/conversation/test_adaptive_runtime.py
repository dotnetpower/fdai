"""Exercise adaptive answers through the real semantic planner, verifier, and read executor."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from fdai.core.conversation.conversation_preflight import (
    ContextDependency,
    ConversationPreflightProposal,
    ConversationPreflightResult,
    OperationalSignal,
    SocialAct,
)
from fdai.core.conversation.semantic_planning_cascade import NO_T2_ESCALATION_POLICY
from fdai.core.conversation.semantic_runtime import SemanticConversationRuntime
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import OntologyQueryPlanExecutor, QueryNodeResult
from fdai_service_contracts.ontology_query import (
    EvidenceAuthority,
    OntologyQueryNode,
    QueryNodeKind,
)
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

from tests.conversation.test_adaptive_service import (
    _draft,
    _review,
)
from tests.conversation.test_adaptive_service import (
    _Model as AnswerModel,
)
from tests.conversation.test_adaptive_service import (
    _plan as answer_plan,
)
from tests.conversation.test_adaptive_service import (
    _service as answer_service,
)
from tests.conversation.test_semantic_planning import (
    NOW,
    _fixture,
    _frame,
)
from tests.conversation.test_semantic_planning import (
    _Model as QueryModel,
)
from tests.conversation.test_semantic_planning import (
    _plan as query_plan,
)
from tests.conversation.test_semantic_planning import (
    _service as query_service,
)


@pytest.mark.parametrize("available", [True, False])
async def test_adaptive_example_uses_verified_query_runtime_without_widening_authority(
    available: bool,
) -> None:
    manifest, definition = _fixture()
    query_model = QueryModel(frame=_frame(), plan=query_plan(definition))
    reads: list[str] = []

    async def handler(
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        reads.append(node.node_id)
        assert dependencies == {}
        if not available:
            raise ValueError("Synthetic source unavailable")
        return QueryNodeResult(
            value={"recorded_configuration": {"revisions": 2, "traffic_policy": "weighted"}},
            evidence_refs=("inventory:verified-example",),
            authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
        )

    draft = {
        "sections": [
            {"goal_id": "explain", "text": "A canary gradually moves traffic."},
            {
                "goal_id": "example",
                "text": "The verified example has weighted traffic configuration.",
            },
        ]
    }
    model = AnswerModel(
        plan=answer_plan(example=True),
        answer=draft,
        review={**_review(), "supported_goal_ids": ["explain", "example"]},
    )
    runtime = SemanticConversationRuntime(
        planner=query_service(query_model, manifest),
        executor=OntologyQueryPlanExecutor(
            handlers={QueryNodeKind.OBJECT_SET: handler}, now=lambda: NOW
        ),
        adaptive_service=answer_service(model),
    )
    result = await runtime.handle(
        utterance="Hello, compare deployment strategies with an environment example.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
    )
    assert result.disposition == "advisory_response"
    assert result.execution is None
    assert result.execution_authority is False
    assert result.adaptive_answer is not None
    assert result.adaptive_answer.goals[0].status == "answered"
    assert result.adaptive_answer.goals[1].status == ("answered" if available else "unavailable")
    assert result.adaptive_answer.goals[1].evidence_refs == (
        ("inventory:verified-example",) if available else ()
    )
    assert reads == ["resources"]
    assert (query_model.frame_calls, query_model.plan_calls) == (1, 1)
    assert "canary" in result.adaptive_answer.answer


async def test_general_explanation_does_not_require_query_planning_or_a_provider_read() -> None:
    manifest, definition = _fixture()
    query_model = QueryModel(frame=_frame(), plan=query_plan(definition))
    model = AnswerModel(plan=answer_plan(), answer=_draft(), review=_review())
    runtime = SemanticConversationRuntime(
        planner=query_service(query_model, manifest),
        executor=OntologyQueryPlanExecutor(handlers={}),
        adaptive_service=answer_service(model),
    )
    result = await runtime.handle(
        utterance="Compare blue-green and canary.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
    )
    assert result.disposition == "advisory_response"
    assert (query_model.frame_calls, query_model.plan_calls) == (0, 0)


async def test_explicit_operational_preflight_bypasses_adaptive_planning() -> None:
    manifest, _definition = _fixture()
    query_model = QueryModel(frame=None, plan=None)
    adaptive_model = AnswerModel(plan=answer_plan(), answer=_draft(), review=_review())
    judgment = SemanticJudgmentProposal(
        primary_intent="create.document",
        targets=(),
        requested_facets=("resource_inventory", "subscription", "complete_content", "download"),
        confidence=0.98,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    )

    class _OperationalJudgment:
        def preflight(self, **_kwargs: object) -> ConversationPreflightResult:
            return ConversationPreflightResult(
                proposal=ConversationPreflightProposal(
                    social_act=SocialAct.NONE,
                    operational_signal=OperationalSignal.EXPLICIT,
                    context_dependency=ContextDependency.NONE,
                    confidence=0.99,
                )
            )

        def judge(self, **_kwargs: object) -> object:
            from types import SimpleNamespace

            return SimpleNamespace(
                accepted=True,
                observations=(),
                proposal=judgment,
                receipt=SimpleNamespace(
                    disposition=SimpleNamespace(value="accepted"),
                    tier=SimpleNamespace(value="t1"),
                ),
            )

    async def handler(
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        assert dependencies == {}
        return QueryNodeResult(
            value={"unexpected": node.node_id},
            evidence_refs=("inventory:verified",),
            authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
        )

    runtime = SemanticConversationRuntime(
        planner=query_service(
            query_model,
            manifest,
            semantic_judgment=_OperationalJudgment(),
        ),
        executor=OntologyQueryPlanExecutor(
            handlers={QueryNodeKind.OBJECT_SET: handler},
            now=lambda: NOW,
        ),
        adaptive_service=answer_service(adaptive_model),
    )

    result = await runtime.handle(
        utterance="Create a complete subscription inventory document.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
    )

    assert result.disposition == "answered"
    assert adaptive_model.calls == []
    assert (query_model.frame_calls, query_model.plan_calls) == (0, 0)


async def test_classifier_outage_does_not_retry_the_request_through_the_legacy_model() -> None:
    manifest, definition = _fixture()
    query_model = QueryModel(frame=_frame(), plan=query_plan(definition))
    runtime = SemanticConversationRuntime(
        planner=query_service(query_model, manifest),
        executor=OntologyQueryPlanExecutor(handlers={}),
        adaptive_service=answer_service(AnswerModel()),
    )
    result = await runtime.handle(
        utterance="Compare blue-green and canary.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
    )
    assert result.disposition == "held"
    assert result.reason == "adaptive_planning_unavailable"
    assert (query_model.frame_calls, query_model.plan_calls) == (0, 0)


async def test_general_answer_remains_available_without_an_operational_store() -> None:
    runtime = SemanticConversationRuntime(
        adaptive_service=answer_service(
            AnswerModel(
                plan=answer_plan(example=True),
                answer=_draft(),
                review=_review(),
            )
        ),
        verified_unavailable_reason="semantic_ontology_store_unavailable",
    )
    result = await runtime.handle(
        utterance="Compare blue-green and canary with an example.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
    )
    assert result.disposition == "advisory_response"
    assert result.adaptive_answer is not None
    assert result.adaptive_answer.goals[0].status == "answered"
    assert result.adaptive_answer.goals[1].status == "unavailable"
    assert result.adaptive_answer.goals[1].limitation == "semantic_ontology_store_unavailable"
    assert result.execution is None


async def test_operational_requests_still_hold_when_the_store_is_missing() -> None:
    runtime = SemanticConversationRuntime(
        adaptive_service=answer_service(
            AnswerModel(
                plan={
                    "route": "legacy",
                    "social_act": "greeting",
                    "context_dependency": "none",
                    "action_requested": False,
                    "goals": [],
                }
            )
        ),
        verified_unavailable_reason="semantic_ontology_store_unavailable",
    )
    result = await runtime.handle(
        utterance="Hello, show current resource status.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
    )
    assert result.disposition == "held"
    assert result.reason == "semantic_ontology_store_unavailable"
    assert result.adaptive_answer is None
    assert len(result.planning.model_observations) == 1


async def test_no_t2_policy_bypasses_the_injected_adaptive_reviewer() -> None:
    manifest, definition = _fixture()
    query_model = QueryModel(frame=_frame(), plan=query_plan(definition))
    model = AnswerModel(plan=answer_plan(), answer=_draft(), review=_review())
    runtime = SemanticConversationRuntime(
        planner=query_service(query_model, manifest),
        executor=OntologyQueryPlanExecutor(handlers={}),
        adaptive_service=answer_service(model),
    )
    result = await runtime.handle(
        utterance="Read the current state.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        escalation_policy=NO_T2_ESCALATION_POLICY,
    )
    assert model.calls == []
    assert (query_model.frame_calls, query_model.plan_calls) == (1, 1)
    assert result.adaptive_answer is None


@pytest.mark.parametrize("explanation", [False, True])
async def test_governed_draft_keeps_plan_observations_without_duplicate_usage(
    explanation: bool,
) -> None:
    manifest, _ = _fixture()
    query_model = QueryModel(
        frame=_frame(operation="action_draft", output_shape="action_draft"),
        plan=None,
    )
    model = AnswerModel(
        plan={
            **answer_plan(),
            "action_requested": True,
            **({} if explanation else {"route": "legacy", "goals": []}),
        },
        answer=_draft(),
        review=_review(),
    )
    runtime = SemanticConversationRuntime(
        planner=query_service(query_model, manifest),
        executor=OntologyQueryPlanExecutor(handlers={}),
        adaptive_service=answer_service(model),
    )
    result = await runtime.handle(
        utterance="Explain rollout strategies and prepare a draft.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
    )
    assert result.disposition == "action_draft"
    assert (result.adaptive_answer is not None) is explanation
    assert (query_model.frame_calls, query_model.plan_calls) == (1, 0)
    assert len(result.planning.model_observations) == (3 if explanation else 1)
    assert result.execution_authority is False
