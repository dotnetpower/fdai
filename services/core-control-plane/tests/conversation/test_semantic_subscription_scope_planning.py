"""Semantic planning tests for server-owned subscription identity."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fdai.core.conversation.semantic_judgment import (
    SemanticJudgmentBinding,
    SemanticJudgmentBoundary,
)
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_frame import build_semantic_frame
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
from fdai_service_contracts.semantic_judgment import SemanticJudgmentTier

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
    def propose_frame(self, **_kwargs: Any) -> dict[str, object]:
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


def _manifest(*, bound: bool = True) -> QueryManifest:
    function = subscription_scope_function_type()
    release = build_ontology_release(function_types=(function,))
    return build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        functions=(function,),
        bound_function_names=(function.name,) if bound else (),
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


def test_schema_validated_judgment_precedes_subscription_plan_selection() -> None:
    judgment_model = _JudgmentModel()
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
        model=_FrameModel(),
        manifests=_ManifestProvider(_manifest()),
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
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "subscription_scope_identity"
    assert outcome.plan is not None
    assert outcome.plan.nodes[0].arguments["function_name"] == SUBSCRIPTION_SCOPE_FUNCTION_NAME
