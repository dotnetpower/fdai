"""Deterministic answer-failure attribution and ontology adequacy review."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from fdai.core.conversation_assurance.models import TurnAssessmentInput


class FailureLayer(StrEnum):
    CONTEXT = "context"
    EVIDENCE = "evidence"
    ROUTING = "routing"
    RENDERING = "rendering"
    POLICY = "policy"
    RULE = "rule"
    ONTOLOGY_MAPPING = "ontology_mapping"
    ONTOLOGY_PROJECTION = "ontology_projection"
    ONTOLOGY_SCHEMA = "ontology_schema"
    DYNAMIC = "dynamic"
    UNKNOWN = "unknown"


class AdequacyCandidateKind(StrEnum):
    PROVIDER_MAPPING = "provider_mapping"
    PROJECTION_BINDING = "projection_binding"
    ONTOLOGY_DECLARATION = "ontology_declaration"
    RULE_CANDIDATE = "rule_candidate"
    DYNAMIC_MODEL = "dynamic_model"


class AdequacyReviewState(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    HELD = "held"
    READY = "ready"


@dataclass(frozen=True, slots=True)
class AnswerFailureAttribution:
    attribution_id: str
    turn_id: str
    reason_code: str
    layer: FailureLayer
    evidence_refs: tuple[str, ...]
    evidence_complete: bool | None
    route_id: str | None
    ontology_release: str | None
    graph_revision: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class OntologyAdequacyReview:
    review_id: str
    attribution_id: str
    state: AdequacyReviewState
    candidate_kind: AdequacyCandidateKind | None
    competency_question_digest: str
    ontology_release: str | None
    graph_revision: str | None
    evidence_refs: tuple[str, ...]
    reason_codes: tuple[str, ...]


class OntologyAdequacyInvestigator(Protocol):
    async def investigate(
        self,
        turn: TurnAssessmentInput,
        attribution: AnswerFailureAttribution,
    ) -> OntologyAdequacyReview: ...


class OntologyAdequacyReviewSink(Protocol):
    async def submit(self, review: OntologyAdequacyReview) -> None: ...


class HoldingOntologyAdequacyInvestigator:
    """Create an explicit hold until exact replay evidence is available."""

    async def investigate(
        self,
        turn: TurnAssessmentInput,
        attribution: AnswerFailureAttribution,
    ) -> OntologyAdequacyReview:
        return build_ontology_adequacy_review(
            attribution,
            question_digest=turn.question_digest,
            replay_reproduced=False,
            routing_verified=turn.verification_route_id is not None,
            identity_resolved=not turn.failed_claim_ids,
        )


def attribute_answer_failure(turn: TurnAssessmentInput) -> AnswerFailureAttribution:
    """Classify one terminal failure without assuming an ontology defect."""

    reason = turn.verification_reason_code.casefold()
    layer = _layer_for_reason(reason)
    material = "\0".join(
        (
            turn.turn_id,
            turn.answer_digest,
            turn.evidence_manifest_digest,
            reason,
            layer.value,
        )
    )
    return AnswerFailureAttribution(
        attribution_id="answer-failure:" + hashlib.sha256(material.encode()).hexdigest(),
        turn_id=turn.turn_id,
        reason_code=turn.verification_reason_code,
        layer=layer,
        evidence_refs=turn.evidence_refs,
        evidence_complete=turn.evidence_complete,
        route_id=turn.verification_route_id,
        ontology_release=turn.ontology_release,
        graph_revision=turn.graph_revision,
        reason=f"attributed_to_{layer.value}",
    )


def build_ontology_adequacy_review(
    attribution: AnswerFailureAttribution,
    *,
    question_digest: str,
    replay_reproduced: bool,
    routing_verified: bool,
    identity_resolved: bool,
) -> OntologyAdequacyReview:
    """Open a review only for reproduced, well-grounded ontology-owned gaps."""

    candidate_kind = _candidate_kind(attribution.layer)
    reasons: list[str] = []
    if candidate_kind is None:
        state = AdequacyReviewState.NOT_APPLICABLE
        reasons.append("failure_owned_by_other_layer")
    else:
        if attribution.evidence_complete is not True:
            reasons.append("evidence_incomplete")
        if not routing_verified:
            reasons.append("routing_unverified")
        if not identity_resolved:
            reasons.append("identity_unresolved")
        if not replay_reproduced:
            reasons.append("gap_not_reproduced")
        if attribution.ontology_release is None:
            reasons.append("ontology_release_unavailable")
        if attribution.graph_revision is None:
            reasons.append("graph_revision_unavailable")
        state = AdequacyReviewState.HELD if reasons else AdequacyReviewState.READY
    identity = "\0".join(
        (
            attribution.attribution_id,
            question_digest,
            candidate_kind.value if candidate_kind is not None else "none",
            state.value,
        )
    )
    return OntologyAdequacyReview(
        review_id="ontology-adequacy:" + hashlib.sha256(identity.encode()).hexdigest(),
        attribution_id=attribution.attribution_id,
        state=state,
        candidate_kind=candidate_kind,
        competency_question_digest=question_digest,
        ontology_release=attribution.ontology_release,
        graph_revision=attribution.graph_revision,
        evidence_refs=attribution.evidence_refs,
        reason_codes=tuple(sorted(reasons)) if reasons else ("adequacy_review_ready",),
    )


def _layer_for_reason(reason: str) -> FailureLayer:
    if reason == "verification_reason_unavailable":
        return FailureLayer.UNKNOWN
    mappings = (
        (FailureLayer.DYNAMIC, ("dynamic_", "trajectory_", "simulation_", "active_model_")),
        (
            FailureLayer.ONTOLOGY_SCHEMA,
            ("unknown_object_type", "unknown_link_type", "ontology_schema"),
        ),
        (
            FailureLayer.ONTOLOGY_PROJECTION,
            ("ontology_projection", "link_declaration_missing", "projection_binding"),
        ),
        (FailureLayer.ONTOLOGY_MAPPING, ("unmapped_", "unclassified_", "ontology_mapping")),
        (FailureLayer.RULE, ("unknown_cited_rule", "no_grounded_citation", "rule_")),
        (FailureLayer.POLICY, ("policy_", "approval_", "authority_denied", "intentional_hold")),
        (FailureLayer.ROUTING, ("invalid_query", "invalid_arguments", "intent_", "capability_")),
        (
            FailureLayer.RENDERING,
            (
                "answer_text_",
                "screen_claim_",
                "quality_",
                "evidence_invalid",
                "manifest_invalid",
            ),
        ),
        (
            FailureLayer.CONTEXT,
            (
                "prior_context_",
                "ordinal_",
                "ambiguous_",
                "incident_anchor_",
                "resource_selector_",
            ),
        ),
        (
            FailureLayer.EVIDENCE,
            (
                "provider_",
                "source_",
                "evidence_",
                "snapshot_incomplete",
                "_unavailable",
                "_stale",
            ),
        ),
    )
    for layer, markers in mappings:
        if any(marker in reason for marker in markers):
            return layer
    return FailureLayer.UNKNOWN


def _candidate_kind(layer: FailureLayer) -> AdequacyCandidateKind | None:
    return {
        FailureLayer.ONTOLOGY_MAPPING: AdequacyCandidateKind.PROVIDER_MAPPING,
        FailureLayer.ONTOLOGY_PROJECTION: AdequacyCandidateKind.PROJECTION_BINDING,
        FailureLayer.ONTOLOGY_SCHEMA: AdequacyCandidateKind.ONTOLOGY_DECLARATION,
        FailureLayer.RULE: AdequacyCandidateKind.RULE_CANDIDATE,
        FailureLayer.DYNAMIC: AdequacyCandidateKind.DYNAMIC_MODEL,
    }.get(layer)


__all__ = [
    "AdequacyCandidateKind",
    "AdequacyReviewState",
    "AnswerFailureAttribution",
    "FailureLayer",
    "HoldingOntologyAdequacyInvestigator",
    "OntologyAdequacyInvestigator",
    "OntologyAdequacyReview",
    "OntologyAdequacyReviewSink",
    "attribute_answer_failure",
    "build_ontology_adequacy_review",
]
