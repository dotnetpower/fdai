"""Exercise adaptive answers through the real semantic planner, verifier, and read executor."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from threading import Event
from types import SimpleNamespace

import pytest
from fdai.core.conversation.adaptive_call_scope import run_scoped_model
from fdai.core.conversation.conversation_preflight import (
    ContextDependency,
    ConversationPreflightProposal,
    ConversationPreflightResult,
    GeneralKnowledgeDraft,
    GeneralKnowledgeSignal,
    OperationalSignal,
    SocialAct,
)
from fdai.core.conversation.semantic_planning_cascade import NO_T2_ESCALATION_POLICY
from fdai.core.conversation.semantic_planning_models import SemanticPlanningOutcome
from fdai.core.conversation.semantic_runtime import (
    SemanticConversationRuntime,
    _run_planning_with_cancellation,
)
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import OntologyQueryPlanExecutor, QueryNodeResult
from fdai_service_contracts.ontology_query import (
    EvidenceAuthority,
    OntologyQueryNode,
    QueryNodeKind,
    content_digest,
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

_MODEL_DIGEST = "sha256:" + ("a" * 64)


@pytest.mark.parametrize("cancel_mode", ["request", "parent"])
async def test_planning_cancellation_stops_thread_owned_provider(cancel_mode: str) -> None:
    owner_loop = asyncio.get_running_loop()
    provider_started = asyncio.Event()
    provider_stopped = asyncio.Event()
    worker_stopped = Event()
    cancelled = asyncio.Event()

    async def provider() -> None:
        provider_started.set()
        try:
            await asyncio.Future()
        finally:
            provider_stopped.set()

    def operation() -> SemanticPlanningOutcome:
        provider_call = asyncio.run_coroutine_threadsafe(
            run_scoped_model(provider),
            owner_loop,
        )
        try:
            provider_call.result(timeout=2)
        finally:
            worker_stopped.set()
        raise AssertionError("cancelled planning must not return")

    pending = asyncio.create_task(_run_planning_with_cancellation(operation, cancelled=cancelled))
    await asyncio.wait_for(provider_started.wait(), timeout=1)
    if cancel_mode == "request":
        cancelled.set()
    else:
        pending.cancel()

    with pytest.raises(asyncio.CancelledError):
        await pending
    assert provider_stopped.is_set()
    assert worker_stopped.wait(timeout=1)


async def test_planning_does_not_start_after_request_cancellation() -> None:
    cancelled = asyncio.Event()
    cancelled.set()
    called = False

    def operation() -> SemanticPlanningOutcome:
        nonlocal called
        called = True
        raise AssertionError("cancelled planning must not start")

    with pytest.raises(asyncio.CancelledError):
        await _run_planning_with_cancellation(operation, cancelled=cancelled)
    assert called is False


def _general_preflight_result(
    proposal: ConversationPreflightProposal,
    *,
    utterance: str,
) -> ConversationPreflightResult:
    return ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=_MODEL_DIGEST,
        prompt_digest=_MODEL_DIGEST,
        direct_response_profile_digest=_MODEL_DIGEST,
    )


def _general_proposal(
    *,
    answer: str,
    locale: str = "en",
    confidence: float = 0.99,
) -> ConversationPreflightProposal:
    return ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.NONE,
        context_dependency=ContextDependency.NONE,
        knowledge_signal=GeneralKnowledgeSignal.EXPLICIT,
        general_answer=GeneralKnowledgeDraft(
            locale=locale,
            answer=answer,
            profile_digest=_MODEL_DIGEST,
        ),
        confidence=confidence,
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


async def test_general_knowledge_preflight_keeps_the_adaptive_answer_path() -> None:
    manifest, _definition = _fixture()
    query_model = QueryModel(frame=_frame(), plan=None)
    adaptive_model = AnswerModel(
        answer={
            "sections": [
                {
                    "goal_id": "general-knowledge",
                    "text": "블루-그린은 일괄 전환하고 카나리는 점진적으로 확대합니다.",
                }
            ]
        }
    )

    class _GeneralKnowledgePreflight:
        def preflight(self, **kwargs: object) -> ConversationPreflightResult:
            utterance = kwargs["utterance"]
            assert isinstance(utterance, str)
            return _general_preflight_result(
                _general_proposal(
                    locale="ko",
                    answer="블루-그린은 일괄 전환하고 카나리는 점진적으로 확대합니다.",
                ),
                utterance=utterance,
            )

        def judge(self, **_kwargs: object) -> object:
            raise AssertionError("general knowledge must not enter semantic judgment")

    runtime = SemanticConversationRuntime(
        planner=query_service(
            query_model,
            manifest,
            semantic_judgment=_GeneralKnowledgePreflight(),
        ),
        executor=OntologyQueryPlanExecutor(handlers={}),
        adaptive_service=answer_service(adaptive_model),
    )

    result = await runtime.handle(
        utterance="블루-그린 배포와 카나리 배포의 장단점을 비교해 줘.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        locale="ko",
    )

    assert result.disposition == "advisory_response"
    assert result.adaptive_answer is not None
    assert result.adaptive_answer.goals[0].kind == "knowledge"
    assert result.adaptive_answer.quality_status == "limited"
    assert adaptive_model.calls == []
    assert (query_model.frame_calls, query_model.plan_calls) == (0, 0)


async def test_general_knowledge_cancellation_after_preflight_publishes_no_answer() -> None:
    manifest, _definition = _fixture()
    query_model = QueryModel(frame=_frame(), plan=None)
    cancelled = asyncio.Event()

    class _CancellingGeneralKnowledgePreflight:
        def preflight(self, **kwargs: object) -> ConversationPreflightResult:
            utterance = kwargs["utterance"]
            assert isinstance(utterance, str)
            cancelled.set()
            return _general_preflight_result(
                _general_proposal(
                    answer="Blue-green swaps environments; canary increases exposure gradually.",
                ),
                utterance=utterance,
            )

        def judge(self, **_kwargs: object) -> object:
            raise AssertionError("cancelled general knowledge must not enter semantic judgment")

    runtime = SemanticConversationRuntime(
        planner=query_service(
            query_model,
            manifest,
            semantic_judgment=_CancellingGeneralKnowledgePreflight(),
        ),
        executor=OntologyQueryPlanExecutor(handlers={}),
    )

    with pytest.raises(asyncio.CancelledError):
        await runtime.handle(
            utterance="Compare blue-green and canary.",
            prior_turns=(),
            principal=Principal(id="operator", role=Role.READER),
            cancelled=cancelled,
        )

    assert (query_model.frame_calls, query_model.plan_calls) == (0, 0)


async def test_parent_cancellation_stops_thread_owned_preflight() -> None:
    manifest, _definition = _fixture()
    query_model = QueryModel(frame=_frame(), plan=None)
    started = Event()
    stopped = Event()

    class _BlockingPreflight:
        def preflight(self, **kwargs: object) -> ConversationPreflightResult:
            cancelled = kwargs["cancelled"]
            assert isinstance(cancelled, asyncio.Event)
            started.set()
            while not cancelled.is_set():
                time.sleep(0.001)
            stopped.set()
            return ConversationPreflightResult(
                proposal=None,
                attempted=True,
                failure_kind="provider_unavailable",
            )

        def judge(self, **_kwargs: object) -> object:
            raise AssertionError("cancelled preflight must not enter semantic judgment")

    runtime = SemanticConversationRuntime(
        planner=query_service(
            query_model,
            manifest,
            semantic_judgment=_BlockingPreflight(),
        ),
        executor=OntologyQueryPlanExecutor(handlers={}),
    )
    pending = asyncio.create_task(
        runtime.handle(
            utterance="Compare blue-green and canary.",
            prior_turns=(),
            principal=Principal(id="operator", role=Role.READER),
        )
    )
    assert await asyncio.to_thread(started.wait, 1)
    pending.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(pending, timeout=1)
    assert stopped.wait(1)


async def test_general_knowledge_does_not_require_an_adaptive_answer_runtime() -> None:
    manifest, _definition = _fixture()
    query_model = QueryModel(frame=_frame(), plan=None)

    class _GeneralKnowledgePreflight:
        def preflight(self, **kwargs: object) -> ConversationPreflightResult:
            utterance = kwargs["utterance"]
            assert isinstance(utterance, str)
            return _general_preflight_result(
                _general_proposal(
                    answer="Blue-green swaps environments; canary increases exposure gradually.",
                ),
                utterance=utterance,
            )

        def judge(self, **_kwargs: object) -> object:
            raise AssertionError("general knowledge must not enter semantic judgment")

    runtime = SemanticConversationRuntime(
        planner=query_service(
            query_model,
            manifest,
            semantic_judgment=_GeneralKnowledgePreflight(),
        ),
        executor=OntologyQueryPlanExecutor(handlers={}),
    )

    result = await runtime.handle(
        utterance="Compare blue-green and canary.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
    )

    assert result.disposition == "advisory_response"
    assert result.adaptive_answer is not None
    assert result.adaptive_answer.answer.startswith("Blue-green")
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


async def test_failed_configured_preflight_falls_back_to_verified_semantic_planning() -> None:
    manifest, _definition = _fixture()
    query_model = QueryModel(frame=_frame(), plan=None)
    adaptive_model = AnswerModel(plan=answer_plan())
    judgment = SemanticJudgmentProposal(
        primary_intent="query.other",
        targets=(),
        requested_facets=(),
        confidence=0.98,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    )

    class _FailedPreflight:
        def preflight(self, **_kwargs: object) -> ConversationPreflightResult:
            return ConversationPreflightResult(
                proposal=None,
                attempted=True,
                failure_kind="malformed",
            )

        def judge(self, **_kwargs: object) -> object:
            return SimpleNamespace(
                accepted=True,
                observations=(),
                proposal=judgment,
                receipt=SimpleNamespace(
                    disposition=SimpleNamespace(value="accepted"),
                    tier=SimpleNamespace(value="t1"),
                ),
            )

    runtime = SemanticConversationRuntime(
        planner=query_service(
            query_model,
            manifest,
            semantic_judgment=_FailedPreflight(),
        ),
        executor=OntologyQueryPlanExecutor(handlers={}),
        adaptive_service=answer_service(adaptive_model),
    )

    result = await runtime.handle(
        utterance="Compare blue-green and canary.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
    )

    assert result.disposition == "unsupported"
    assert result.reason != "conversation_preflight_malformed"
    assert adaptive_model.calls == []
    assert (query_model.frame_calls, query_model.plan_calls) == (1, 1)


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


async def test_general_answer_without_adaptive_profile_is_restricted_to_bragi() -> None:
    manifest, _definition = _fixture()
    query_model = QueryModel(frame=_frame(), plan=None)

    class _BragiGeneralKnowledgePreflight:
        def preflight(self, **kwargs: object) -> ConversationPreflightResult:
            utterance = kwargs["utterance"]
            assert isinstance(utterance, str)
            return _general_preflight_result(
                _general_proposal(
                    answer="Blue-green swaps environments; canary increases exposure gradually.",
                ),
                utterance=utterance,
            )

        def judge(self, **_kwargs: object) -> object:
            raise RuntimeError("no verified Odin profile is available")

    runtime = SemanticConversationRuntime(
        planner=query_service(
            query_model,
            manifest,
            semantic_judgment=_BragiGeneralKnowledgePreflight(),
        ),
        executor=OntologyQueryPlanExecutor(handlers={}),
    )

    result = await runtime.handle(
        utterance="Compare blue-green and canary.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        target_agent="Odin",
    )

    assert result.disposition == "held"
    assert result.adaptive_answer is None
    assert result.reason == "semantic_planning_failed"


async def test_unverified_general_candidate_rechecks_typed_operational_judgment() -> None:
    manifest, definition = _fixture()
    query_model = QueryModel(frame=_frame(), plan=query_plan(definition))
    adaptive_model = AnswerModel(answer=_draft())

    class _MisclassifiedGeneralKnowledgePreflight:
        def preflight(self, **kwargs: object) -> ConversationPreflightResult:
            utterance = kwargs["utterance"]
            assert isinstance(utterance, str)
            return _general_preflight_result(
                _general_proposal(
                    answer="Blue-green swaps environments; canary increases exposure gradually.",
                    confidence=0.89,
                ),
                utterance=utterance,
            )

        def judge(self, **_kwargs: object) -> object:
            return SimpleNamespace(
                accepted=True,
                observations=(),
                proposal=SemanticJudgmentProposal(
                    primary_intent="read_state",
                    targets=(),
                    requested_facets=(),
                    confidence=0.99,
                    ambiguous=False,
                    action_posture="advise_only",
                    action_subject="none",
                    authority="candidate_only",
                    execution_authority=False,
                ),
                receipt=SimpleNamespace(
                    disposition=SimpleNamespace(value="accepted"),
                    tier=SimpleNamespace(value="t1"),
                ),
            )

    runtime = SemanticConversationRuntime(
        planner=query_service(
            query_model,
            manifest,
            semantic_judgment=_MisclassifiedGeneralKnowledgePreflight(),
        ),
        executor=OntologyQueryPlanExecutor(handlers={}),
        adaptive_service=answer_service(adaptive_model),
    )

    result = await runtime.handle(
        utterance="List current resources.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
    )

    assert result.reason != "general_answer_route_unverified"
    assert adaptive_model.calls == []
    assert (query_model.frame_calls, query_model.plan_calls) == (1, 1)


async def test_no_t2_campaign_keeps_general_knowledge_on_verified_path() -> None:
    manifest, definition = _fixture()
    query_model = QueryModel(frame=_frame(), plan=query_plan(definition))
    adaptive_model = AnswerModel(answer=_draft())

    class _GeneralKnowledgePreflight:
        def preflight(self, **kwargs: object) -> ConversationPreflightResult:
            utterance = kwargs["utterance"]
            assert isinstance(utterance, str)
            return _general_preflight_result(
                _general_proposal(
                    answer="Blue-green swaps environments; canary increases exposure gradually.",
                ),
                utterance=utterance,
            )

        def judge(self, **_kwargs: object) -> object:
            return SimpleNamespace(
                accepted=True,
                observations=(),
                proposal=SemanticJudgmentProposal(
                    primary_intent="read_state",
                    targets=(),
                    requested_facets=(),
                    confidence=0.99,
                    ambiguous=False,
                    action_posture="advise_only",
                    action_subject="none",
                    authority="candidate_only",
                    execution_authority=False,
                ),
                receipt=SimpleNamespace(
                    disposition=SimpleNamespace(value="accepted"),
                    tier=SimpleNamespace(value="t1"),
                ),
            )

    runtime = SemanticConversationRuntime(
        planner=query_service(
            query_model,
            manifest,
            semantic_judgment=_GeneralKnowledgePreflight(),
        ),
        executor=OntologyQueryPlanExecutor(handlers={}),
        adaptive_service=answer_service(adaptive_model),
    )

    result = await runtime.handle(
        utterance="Compare blue-green and canary.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        escalation_policy=NO_T2_ESCALATION_POLICY,
    )

    assert adaptive_model.calls == []
    assert (query_model.frame_calls, query_model.plan_calls) == (1, 1)
    assert result.adaptive_answer is None


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
