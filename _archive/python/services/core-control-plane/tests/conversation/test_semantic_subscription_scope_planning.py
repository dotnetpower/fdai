"""Semantic planning tests for server-owned subscription identity."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.core.conversation.conversation_preflight_targets import (
    collection_summary_exact_target_requested,
    named_subscription_requested,
)
from fdai.core.conversation.semantic_judgment import (
    SemanticJudgmentBinding,
    SemanticJudgmentBoundary,
)
from fdai.core.conversation.semantic_operational_summary_planning import (
    build_function_backed_summary_frame,
)
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_frame import build_semantic_frame
from fdai.core.conversation.semantic_planning_frame_checks import (
    deterministic_pre_frame_selection,
)
from fdai.core.conversation.semantic_planning_models import (
    SemanticFrameProposal,
    SemanticOutputShape,
    SemanticPlanningDisposition,
)
from fdai.core.conversation.semantic_subscription_scope_planning import (
    compile_subscription_scope_plan,
)
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import (
    OntologyQueryPlanVerifier,
    QueryManifest,
    build_query_manifest,
)
from fdai.core.ontology_platform.service_health_queries import service_health_function_type
from fdai.core.ontology_platform.subscription_scope_queries import (
    SUBSCRIPTION_SCOPE_FUNCTION_NAME,
    SUBSCRIPTION_SCOPE_MEASURE_CONCEPTS,
    subscription_scope_function_type,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release
from fdai_service_contracts.ontology_query import (
    QueryNodeKind,
    SemanticOperation,
    SemanticProblemFrame,
)
from fdai_service_contracts.semantic_judgment import (
    SemanticJudgmentProposal,
    SemanticJudgmentTier,
)


@pytest.mark.parametrize(
    "utterance",
    (
        "현재 구독",
        "내 구독",
        "이 구독",
        "그 구독",
        "subscription 상태를 보여줘",
        "subscription 정보를 보여줘",
        "subscription 세부 정보를 보여줘",
        "subscription 리소스를 보여줘",
        "subscription 구성을 보여줘",
        "subscription 좀 알려줘",
        "subscription 정보도 보여줘",
        "제 subscription 상태를 보여줘",
        "지금 subscription 상태를 보여줘",
        "subscription 알려줘",
        "subscription 보여줘",
        "subscription 확인해줘",
        "subscription 뭐야",
        "subscription 자세히 알려줘",
        "subscription 다시 보여줘",
        "subscription 조회해줘",
        "subscription 알려주세요",
        "subscription 보여주세요",
        "subscription 부탁드립니다",
        "subscription 알려줄래?",
        "subscription 보여줄래?",
        "Show the current subscription please.",
        "무슨구독인지 알려줘",
        "어느구독을 보여줘",
        "어떤구독이야",
        "subscription 의 상태를 보여줘",
        "현재 subscription 상태를 보여줘",
    ),
)
def test_generic_korean_subscription_scope_is_not_treated_as_a_name(utterance: str) -> None:
    assert not named_subscription_requested(utterance)


def test_actual_korean_subscription_name_remains_named_scope() -> None:
    assert named_subscription_requested("고객운영 구독")
    assert named_subscription_requested("subscription 고객운영")
    assert named_subscription_requested("동해 구독의 Service Health를 보여줘.")
    assert named_subscription_requested("운영구독 상태를 보여줘.")


def test_collection_summary_detects_source_target_without_confusing_type_filter() -> None:
    assert collection_summary_exact_target_requested(
        "Show the state of db-prod.",
        subject_constraints=("Resource",),
    )
    assert collection_summary_exact_target_requested(
        "Show the state of dbprod.",
        subject_constraints=("Resource",),
    )
    assert collection_summary_exact_target_requested(
        "Show dbprod status.",
        subject_constraints=("Resource", "dbprod"),
    )
    assert collection_summary_exact_target_requested(
        "동해 상태를 보여줘.",
        subject_constraints=("Resource", "동해"),
    )
    assert not collection_summary_exact_target_requested(
        "Show application-service resources.",
        subject_constraints=("Resource", "application-service"),
        catalog_constraints=frozenset({"application-service"}),
    )
    assert not collection_summary_exact_target_requested(
        "Show non-running resources.",
        subject_constraints=("Resource",),
    )
    assert not collection_summary_exact_target_requested(
        "리소스 상태를 보여줘.",
        subject_constraints=("Resource",),
    )
    assert not collection_summary_exact_target_requested(
        "Show the state of all resources.",
        subject_constraints=("Resource",),
    )
    assert not collection_summary_exact_target_requested(
        "Show the state of resources.",
        subject_constraints=("Resource",),
    )
    assert not collection_summary_exact_target_requested(
        "What is the current power state of each existing virtual machine in the authorized scope?",
        subject_constraints=("Resource",),
    )


DIGEST = "sha256:" + ("a" * 64)
NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)


class _ManifestProvider:
    def __init__(self, manifest: QueryManifest) -> None:
        self._manifest = manifest

    def manifest_for(self, *, principal: Principal, purpose: str) -> QueryManifest:
        assert principal.role is Role.READER
        assert purpose == "operations-review"
        return self._manifest


class _FrameModel:
    def __init__(self) -> None:
        self.calls = 0

    def propose_frame(self, **_kwargs: Any) -> dict[str, object]:
        self.calls += 1
        return {
            "operation": "select",
            "subject_constraints": ["current Azure subscription"],
            "measure_concepts": list(SUBSCRIPTION_SCOPE_MEASURE_CONCEPTS),
            "temporal_scope": {},
            "output_shape": "subscription_scope_identity",
            "evidence_requirements": [SUBSCRIPTION_SCOPE_FUNCTION_NAME],
            "unresolved_terms": [],
            "clarification_requirements": [],
            "clarification": None,
            "investigation": None,
            "confidence": 0.98,
        }

    def propose_plan(self, **_kwargs: Any) -> None:
        return None


class _JudgmentModel:
    def __init__(self) -> None:
        self.calls = 0

    def judge(self, **_kwargs: Any) -> dict[str, object]:
        self.calls += 1
        return {
            "primary_intent": SUBSCRIPTION_SCOPE_FUNCTION_NAME,
            "targets": [],
            "requested_facets": ["subscription_identity"],
            "confidence": 0.98,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
            "execution_authority": False,
        }


class _LowConfidenceJudgmentModel(_JudgmentModel):
    def judge(self, **kwargs: Any) -> dict[str, object]:
        proposal = super().judge(**kwargs)
        proposal["confidence"] = 0.4
        return proposal


def _frame() -> SemanticProblemFrame:
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("current Azure subscription",),
        measure_concepts=SUBSCRIPTION_SCOPE_MEASURE_CONCEPTS,
        temporal_scope={},
        output_shape=SemanticOutputShape.SUBSCRIPTION_SCOPE_IDENTITY,
        evidence_requirements=(SUBSCRIPTION_SCOPE_FUNCTION_NAME,),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=0.98,
    )
    return build_semantic_frame(
        proposal,
        utterance="arbitrary words interpreted only by semantic judgment",
        context=(),
    )


def test_subscription_scope_summary_rejects_requested_other_subscription() -> None:
    utterance = "Show subscription other-sub."
    target = "other-sub"
    start = utterance.index(target)
    judgment = SemanticJudgmentProposal.model_validate(
        {
            "primary_intent": SUBSCRIPTION_SCOPE_FUNCTION_NAME,
            "targets": [
                {
                    "kind": "subscription",
                    "value": target,
                    "canonical_value": None,
                    "source_start": start,
                    "source_end": start + len(target),
                }
            ],
            "requested_facets": ["subscription_identity"],
            "confidence": 0.98,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
            "execution_authority": False,
        }
    )

    result = build_function_backed_summary_frame(
        judgment,
        utterance=utterance,
        context=(),
        descriptors=_manifest().descriptors,
        inventory_query_language=None,
    )

    assert result is None


def test_service_health_summary_rejects_requested_other_subscription() -> None:
    utterance = "Show Service Health for subscription prod."
    target = "prod"
    start = utterance.index(target)
    judgment = SemanticJudgmentProposal.model_validate(
        {
            "primary_intent": "query.subscription_service_health",
            "targets": [
                {
                    "kind": "subscription",
                    "value": target,
                    "canonical_value": None,
                    "source_start": start,
                    "source_end": start + len(target),
                }
            ],
            "requested_facets": ["service_health"],
            "confidence": 0.98,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
            "execution_authority": False,
        }
    )

    result = build_function_backed_summary_frame(
        judgment,
        utterance=utterance,
        context=(),
        descriptors=_manifest(include_unrelated=True).descriptors,
        inventory_query_language=None,
    )

    assert result is None


def test_subscription_summary_requires_an_accepted_judgment() -> None:
    judgment = SemanticJudgmentProposal.model_validate(
        {
            "primary_intent": SUBSCRIPTION_SCOPE_FUNCTION_NAME,
            "targets": [],
            "requested_facets": ["subscription_identity"],
            "confidence": 0.4,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
            "execution_authority": False,
        }
    )

    result = deterministic_pre_frame_selection(
        judgment=judgment,
        judgment_accepted=False,
        utterance="Show the current Azure subscription.",
        context=(),
        descriptors=_manifest(include_unrelated=True).descriptors,
    )

    assert result is None


@pytest.mark.parametrize(
    ("primary_intent", "utterance"),
    [
        (SUBSCRIPTION_SCOPE_FUNCTION_NAME, "Show subscription named prod."),
        ("query.subscription_service_health", "Show Service Health for the prod subscription."),
        ("query.subscription_service_health", "고객운영 구독의 Service Health를 보여줘."),
        ("query.subscription_service_health", "고객운영 subscription의 Service Health를 보여줘."),
    ],
)
def test_targetless_summary_rejects_named_subscription_in_source(
    primary_intent: str,
    utterance: str,
) -> None:
    judgment = SemanticJudgmentProposal.model_validate(
        {
            "primary_intent": primary_intent,
            "targets": [],
            "requested_facets": ["subscription"],
            "confidence": 0.98,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
            "execution_authority": False,
        }
    )

    result = build_function_backed_summary_frame(
        judgment,
        utterance=utterance,
        context=(),
        descriptors=_manifest(include_unrelated=True).descriptors,
        inventory_query_language=None,
    )

    assert result is None


def test_low_confidence_subscription_judgment_cannot_fall_back_to_model_summary() -> None:
    judgment_model = _LowConfidenceJudgmentModel()
    frame_model = _FrameModel()
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=judgment_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=frame_model,
        manifests=_ManifestProvider(_manifest(include_unrelated=True)),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
        semantic_judgment=judgment,
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="Show the current Azure subscription.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.reason == "semantic_operational_judgment_required"
    assert outcome.plan is None
    assert judgment_model.calls == 1
    assert frame_model.calls == 1


def _manifest(*, bound: bool = True, include_unrelated: bool = False) -> QueryManifest:
    function = subscription_scope_function_type()
    functions = (function, service_health_function_type()) if include_unrelated else (function,)
    release = build_ontology_release(function_types=functions)
    return build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        functions=functions,
        bound_function_names=tuple(item.name for item in functions) if bound else (),
    )


def test_subscription_scope_plan_uses_no_input_server_function() -> None:
    frame = _frame()
    manifest = _manifest()

    plan = compile_subscription_scope_plan(
        frame=frame,
        manifest=manifest,
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
        purpose="operations-review",
    )

    assert plan is not None
    assert plan.execution_authority is False
    assert len(plan.nodes) == 1
    assert plan.nodes[0].kind is QueryNodeKind.FUNCTION
    assert plan.nodes[0].arguments == {
        "arguments": {},
        "dependency_arguments": {},
        "function_name": SUBSCRIPTION_SCOPE_FUNCTION_NAME,
    }


def test_subscription_scope_plan_requires_bound_function_and_exact_operation() -> None:
    frame = _frame()

    assert (
        compile_subscription_scope_plan(
            frame=frame,
            manifest=_manifest(bound=False),
            verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
            purpose="operations-review",
        )
        is None
    )


def test_schema_validated_judgment_builds_subscription_frame_without_frame_model() -> None:
    judgment_model = _JudgmentModel()
    frame_model = _FrameModel()
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=judgment_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=frame_model,
        manifests=_ManifestProvider(_manifest(include_unrelated=True)),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
        semantic_judgment=judgment,
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="opaque wording with no keyword routing contract",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert judgment_model.calls == 1
    assert frame_model.calls == 0
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "subscription_scope_identity"
    assert outcome.plan is not None
    assert outcome.plan.nodes[0].arguments["function_name"] == SUBSCRIPTION_SCOPE_FUNCTION_NAME
