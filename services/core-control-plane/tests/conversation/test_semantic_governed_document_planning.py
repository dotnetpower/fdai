"""Semantic planning tests for governed document evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.core.conversation.semantic_governed_document_planning import (
    append_governed_document_plan,
    apply_document_evidence_requirement,
    compile_governed_document_plan,
    document_evidence_mode,
)
from fdai.core.conversation.semantic_judgment import (
    SemanticJudgmentBinding,
    SemanticJudgmentBoundary,
)
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_frame_core import build_semantic_frame
from fdai.core.conversation.semantic_planning_models import (
    SemanticFrameProposal,
    SemanticOutputShape,
    SemanticPlanningDisposition,
)
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import (
    OntologyQueryPlanVerifier,
    QueryManifest,
    build_query_manifest,
)
from fdai.core.ontology_platform.governed_document_queries import (
    GOVERNED_DOCUMENT_FUNCTION_NAME,
    GOVERNED_DOCUMENT_MEASURE_CONCEPT,
    governed_document_function_type,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release
from fdai_service_contracts.ontology_query import (
    QueryNodeKind,
    SemanticOperation,
    canonical_json,
)
from fdai_service_contracts.semantic_judgment import (
    SemanticDocumentEvidenceMode,
    SemanticJudgmentProposal,
    SemanticJudgmentTier,
)

DIGEST = "sha256:" + ("a" * 64)
NOW = datetime(2026, 9, 6, 5, 0, tzinfo=UTC)
UTTERANCE = "What does the uploaded recovery runbook require?"


class _ManifestProvider:
    def __init__(self, manifest: QueryManifest) -> None:
        self._manifest = manifest

    def manifest_for(self, *, principal: Principal, purpose: str) -> QueryManifest:
        assert principal.role is Role.READER
        assert purpose == "operations-review"
        return self._manifest


class _FrameModel:
    def __init__(self) -> None:
        self.frame_calls = 0
        self.plan_calls = 0

    def propose_frame(self, **_kwargs: Any) -> None:
        self.frame_calls += 1
        return None

    def propose_plan(self, **_kwargs: Any) -> None:
        self.plan_calls += 1
        return None


class _JudgmentModel:
    def judge(self, **_kwargs: Any) -> dict[str, object]:
        return {
            "primary_intent": GOVERNED_DOCUMENT_FUNCTION_NAME,
            "targets": [],
            "requested_facets": ["document_evidence"],
            "confidence": 0.99,
            "ambiguous": False,
            "document_evidence_mode": "explicit",
            "action_posture": "advise_only",
            "action_subject": "none",
            "execution_authority": False,
        }


def _manifest(*, bound: bool = True) -> QueryManifest:
    function = governed_document_function_type()
    release = build_ontology_release(function_types=(function,))
    return build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        functions=(function,),
        bound_function_names=(function.name,) if bound else (),
    )


def _proposal(
    *,
    output_shape: SemanticOutputShape = SemanticOutputShape.GOVERNED_DOCUMENT_EXCERPTS,
    requirements: tuple[str, ...] = ("governed_documents.explicit",),
) -> SemanticFrameProposal:
    return SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=(),
        measure_concepts=(GOVERNED_DOCUMENT_MEASURE_CONCEPT,),
        temporal_scope={},
        output_shape=output_shape,
        evidence_requirements=requirements,
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=0.99,
    )


def test_document_only_plan_uses_original_utterance_and_bound_function() -> None:
    proposal = _proposal()
    frame = build_semantic_frame(proposal, utterance=UTTERANCE, context=())

    plan = compile_governed_document_plan(
        frame=frame,
        utterance=UTTERANCE,
        manifest=_manifest(),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
        purpose="operations-review",
    )

    assert plan is not None
    assert plan.nodes[0].arguments == {
        "arguments": {
            "evidence_mode": "explicit",
            "query": UTTERANCE,
        },
        "dependency_arguments": {},
        "function_name": GOVERNED_DOCUMENT_FUNCTION_NAME,
    }
    assert plan.execution_authority is False


def test_document_plan_requires_available_function() -> None:
    proposal = _proposal()
    frame = build_semantic_frame(proposal, utterance=UTTERANCE, context=())

    assert (
        compile_governed_document_plan(
            frame=frame,
            utterance=UTTERANCE,
            manifest=_manifest(bound=False),
            verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
            purpose="operations-review",
        )
        is None
    )


def test_optional_document_mode_cannot_select_document_only_output() -> None:
    proposal = _proposal(requirements=("governed_documents.optional",))
    frame = build_semantic_frame(proposal, utterance=UTTERANCE, context=())

    assert (
        compile_governed_document_plan(
            frame=frame,
            utterance=UTTERANCE,
            manifest=_manifest(),
            verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
            purpose="operations-review",
        )
        is None
    )


def test_document_requirement_is_applied_without_replacing_primary_shape() -> None:
    proposal = _proposal(
        output_shape=SemanticOutputShape.SUBSCRIPTION_SERVICE_HEALTH,
        requirements=("authoritative_service_health",),
    )
    frame = build_semantic_frame(proposal, utterance=UTTERANCE, context=())
    judgment = SemanticJudgmentProposal(
        primary_intent="query.subscription_service_health",
        targets=(),
        requested_facets=(),
        confidence=0.95,
        ambiguous=False,
        document_evidence_mode=SemanticDocumentEvidenceMode.OPTIONAL,
        action_subject="none",
    )

    updated, updated_frame = apply_document_evidence_requirement(
        proposal,
        frame,
        judgment=judgment,
        utterance=UTTERANCE,
        context=(),
    )

    assert updated.output_shape is SemanticOutputShape.SUBSCRIPTION_SERVICE_HEALTH
    assert updated.evidence_requirements == (
        "authoritative_service_health",
        "governed_documents.optional",
    )
    assert document_evidence_mode(updated_frame) is SemanticDocumentEvidenceMode.OPTIONAL


def test_none_document_judgment_removes_untrusted_frame_requirement() -> None:
    proposal = _proposal(
        output_shape=SemanticOutputShape.SUBSCRIPTION_SERVICE_HEALTH,
        requirements=("authoritative_service_health", "governed_documents.required"),
    )
    frame = build_semantic_frame(proposal, utterance=UTTERANCE, context=())
    judgment = SemanticJudgmentProposal(
        primary_intent="query.subscription_service_health",
        targets=(),
        requested_facets=(),
        confidence=0.95,
        ambiguous=False,
        document_evidence_mode=SemanticDocumentEvidenceMode.NONE,
        action_subject="none",
    )

    updated, updated_frame = apply_document_evidence_requirement(
        proposal,
        frame,
        judgment=judgment,
        utterance=UTTERANCE,
        context=(),
    )

    assert updated.evidence_requirements == ("authoritative_service_health",)
    assert document_evidence_mode(updated_frame) is None


def test_missing_or_none_judgment_without_document_requirement_is_a_noop() -> None:
    proposal = _proposal(
        output_shape=SemanticOutputShape.SUBSCRIPTION_SERVICE_HEALTH,
        requirements=("authoritative_service_health",),
    )
    frame = build_semantic_frame(proposal, utterance=UTTERANCE, context=())
    none_judgment = SemanticJudgmentProposal(
        primary_intent="query.subscription_service_health",
        targets=(),
        requested_facets=(),
        confidence=0.95,
        ambiguous=False,
        document_evidence_mode=SemanticDocumentEvidenceMode.NONE,
        action_subject="none",
    )

    assert apply_document_evidence_requirement(
        proposal,
        frame,
        judgment=None,
        utterance=UTTERANCE,
        context=(),
    ) == (proposal, frame)
    assert apply_document_evidence_requirement(
        proposal,
        frame,
        judgment=none_judgment,
        utterance=UTTERANCE,
        context=(),
    ) == (proposal, frame)


def test_document_compiler_ignores_non_document_output_shape() -> None:
    proposal = _proposal(output_shape=SemanticOutputShape.SUBSCRIPTION_SERVICE_HEALTH)
    frame = build_semantic_frame(proposal, utterance=UTTERANCE, context=())

    assert (
        compile_governed_document_plan(
            frame=frame,
            utterance=UTTERANCE,
            manifest=_manifest(),
            verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
            purpose="operations-review",
        )
        is None
    )


def test_schema_validated_judgment_selects_document_plan_without_second_model_call() -> None:
    model = _FrameModel()
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_JudgmentModel(),
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(_manifest()),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
        semantic_judgment=judgment,
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance=UTTERANCE,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "governed_document_excerpts"
    assert outcome.plan is not None
    assert outcome.plan.nodes[0].arguments["function_name"] == GOVERNED_DOCUMENT_FUNCTION_NAME
    assert model.frame_calls == 0
    assert model.plan_calls == 0


def test_append_document_plan_recomputes_digest_and_keeps_existing_output() -> None:
    explicit = _proposal()
    frame = build_semantic_frame(explicit, utterance=UTTERANCE, context=())
    base = compile_governed_document_plan(
        frame=frame,
        utterance=UTTERANCE,
        manifest=_manifest(),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
        purpose="operations-review",
    )
    assert base is not None
    optional = build_semantic_frame(
        _proposal(
            output_shape=SemanticOutputShape.SUBSCRIPTION_SERVICE_HEALTH,
            requirements=("governed_documents.optional",),
        ),
        utterance=UTTERANCE,
        context=(),
    )

    augmented = append_governed_document_plan(
        base.model_copy(
            update={
                "nodes": (),
                "output_node_ids": (),
            }
        ),
        frame=optional,
        utterance=UTTERANCE,
        manifest=_manifest(),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
        purpose="operations-review",
    )

    assert augmented is not None
    assert augmented.plan_digest != base.plan_digest
    assert augmented.output_node_ids == ("governed-documents",)


def test_append_noops_without_document_mode_and_for_explicit_document_plan() -> None:
    explicit_frame = build_semantic_frame(_proposal(), utterance=UTTERANCE, context=())
    base = compile_governed_document_plan(
        frame=explicit_frame,
        utterance=UTTERANCE,
        manifest=_manifest(),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
        purpose="operations-review",
    )
    assert base is not None
    no_document_frame = build_semantic_frame(
        _proposal(
            output_shape=SemanticOutputShape.SUBSCRIPTION_SERVICE_HEALTH,
            requirements=("authoritative_service_health",),
        ),
        utterance=UTTERANCE,
        context=(),
    )

    assert (
        append_governed_document_plan(
            base,
            frame=no_document_frame,
            utterance=UTTERANCE,
            manifest=_manifest(),
            verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
            purpose="operations-review",
        )
        is base
    )
    assert (
        append_governed_document_plan(
            base,
            frame=explicit_frame,
            utterance=UTTERANCE,
            manifest=_manifest(),
            verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
            purpose="operations-review",
        )
        is base
    )


def test_append_reports_optional_binding_unavailable() -> None:
    explicit_frame = build_semantic_frame(_proposal(), utterance=UTTERANCE, context=())
    base = compile_governed_document_plan(
        frame=explicit_frame,
        utterance=UTTERANCE,
        manifest=_manifest(),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
        purpose="operations-review",
    )
    assert base is not None
    optional_frame = build_semantic_frame(
        _proposal(
            output_shape=SemanticOutputShape.SUBSCRIPTION_SERVICE_HEALTH,
            requirements=("governed_documents.optional",),
        ),
        utterance=UTTERANCE,
        context=(),
    )

    assert (
        append_governed_document_plan(
            base.model_copy(update={"nodes": (), "output_node_ids": ()}),
            frame=optional_frame,
            utterance=UTTERANCE,
            manifest=_manifest(bound=False),
            verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
            purpose="operations-review",
        )
        is None
    )


@pytest.mark.parametrize("defect", ("duplicate", "mismatch", "reserved_id"))
def test_append_rejects_conflicting_existing_document_nodes(defect: str) -> None:
    explicit_frame = build_semantic_frame(_proposal(), utterance=UTTERANCE, context=())
    base = compile_governed_document_plan(
        frame=explicit_frame,
        utterance=UTTERANCE,
        manifest=_manifest(),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
        purpose="operations-review",
    )
    assert base is not None
    optional_frame = build_semantic_frame(
        _proposal(
            output_shape=SemanticOutputShape.SUBSCRIPTION_SERVICE_HEALTH,
            requirements=("governed_documents.optional",),
        ),
        utterance=UTTERANCE,
        context=(),
    )
    if defect == "duplicate":
        second = base.nodes[0].model_copy(update={"node_id": "second-documents"})
        plan = base.model_copy(
            update={
                "nodes": (*base.nodes, second),
                "output_node_ids": (*base.output_node_ids, second.node_id),
            }
        )
    elif defect == "mismatch":
        plan = base
    else:
        non_document = base.nodes[0].model_copy(
            update={
                "arguments_json": canonical_json(
                    {
                        "function_name": "query.other",
                        "arguments": {},
                        "dependency_arguments": {},
                    }
                )
            }
        )
        plan = base.model_copy(update={"nodes": (non_document,)})

    with pytest.raises(ValueError, match="multiple|does not match|already contains"):
        append_governed_document_plan(
            plan,
            frame=optional_frame,
            utterance=UTTERANCE,
            manifest=_manifest(),
            verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
            purpose="operations-review",
        )


def test_append_reuses_matching_document_function_with_a_different_node_id() -> None:
    explicit = _proposal()
    explicit_frame = build_semantic_frame(explicit, utterance=UTTERANCE, context=())
    base = compile_governed_document_plan(
        frame=explicit_frame,
        utterance=UTTERANCE,
        manifest=_manifest(),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
        purpose="operations-review",
    )
    assert base is not None
    optional_frame = build_semantic_frame(
        _proposal(
            output_shape=SemanticOutputShape.SUBSCRIPTION_SERVICE_HEALTH,
            requirements=("governed_documents.optional",),
        ),
        utterance=UTTERANCE,
        context=(),
    )
    existing = base.nodes[0].model_copy(
        update={
            "node_id": "existing-documents",
            "arguments_json": canonical_json(
                {
                    "function_name": GOVERNED_DOCUMENT_FUNCTION_NAME,
                    "arguments": {
                        "query": UTTERANCE,
                        "evidence_mode": "optional",
                    },
                    "dependency_arguments": {},
                }
            ),
        }
    )
    existing_plan = base.model_copy(
        update={
            "nodes": (existing,),
            "output_node_ids": (existing.node_id,),
        }
    )

    reused = append_governed_document_plan(
        existing_plan,
        frame=optional_frame,
        utterance=UTTERANCE,
        manifest=_manifest(),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
        purpose="operations-review",
    )

    assert reused is existing_plan


@pytest.mark.parametrize(
    "requirements",
    (
        ("governed_documents.optional", "governed_documents.required"),
        ("governed_documents.invalid",),
        ("governed_documents.none",),
    ),
)
def test_document_mode_rejects_noncanonical_frame_requirements(
    requirements: tuple[str, ...],
) -> None:
    frame = build_semantic_frame(
        _proposal(requirements=requirements),
        utterance=UTTERANCE,
        context=(),
    )

    with pytest.raises(ValueError, match="at most one|invalid|omit"):
        document_evidence_mode(frame)


def test_document_plan_rejects_blank_search_query() -> None:
    frame = build_semantic_frame(_proposal(), utterance=UTTERANCE, context=())

    with pytest.raises(ValueError, match="search query"):
        compile_governed_document_plan(
            frame=frame,
            utterance=" ",
            manifest=_manifest(),
            verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
            purpose="operations-review",
        )
