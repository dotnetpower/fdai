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


class ConversationStage(StrEnum):
    """Ordered stages used to attribute structural conversation failures."""

    CONTEXT_FRAMING = "context_framing"
    ROUTING = "routing"
    EVIDENCE_RETRIEVAL = "evidence_retrieval"
    TOOL_EXECUTION = "tool_execution"
    SYNTHESIS = "synthesis"
    RENDERING = "rendering"
    TRANSPORT = "transport"


class StageOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


_STAGE_ORDER = tuple(ConversationStage)
_MAX_STRUCTURAL_EVIDENCE_REFS = 64


@dataclass(frozen=True, slots=True)
class StructuralStageObservation:
    """Record one content-free stage outcome from a completed turn trace."""

    stage: ConversationStage
    outcome: StageOutcome
    reason_code: str
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.reason_code.strip() or len(self.reason_code) > 256:
            raise ValueError("stage observation reason_code MUST be bounded and non-empty")
        if len(self.evidence_refs) > _MAX_STRUCTURAL_EVIDENCE_REFS:
            raise ValueError("stage observation evidence_refs exceeds the bounded cap")
        if any(not item.strip() or len(item) > 1_024 for item in self.evidence_refs):
            raise ValueError("stage observation evidence_refs MUST be bounded and non-empty")


@dataclass(frozen=True, slots=True)
class StructuralFailureAttribution:
    """Bind one failed answer to its earliest failed pipeline stage."""

    attribution_id: str
    turn_id: str
    root_stage: ConversationStage | None
    contributing_stages: tuple[ConversationStage, ...]
    failed_rubrics: tuple[str, ...]
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    channel_kind: str | None = None
    locale: str | None = None
    route_id: str | None = None


@dataclass(frozen=True, slots=True)
class StructuralFailureSummary:
    """Aggregate content-free root-cause counts for one evaluated batch."""

    total_failures: int
    root_stage_counts: tuple[tuple[ConversationStage, int], ...]
    failed_rubric_counts: tuple[tuple[str, int], ...]
    reason_code_counts: tuple[tuple[str, int], ...]
    channel_counts: tuple[tuple[str, int], ...]
    locale_counts: tuple[tuple[str, int], ...]
    route_counts: tuple[tuple[str, int], ...]
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


def attribute_structural_failure(
    *,
    turn_id: str,
    answer_digest: str,
    observations: tuple[StructuralStageObservation, ...],
    failed_rubrics: tuple[str, ...] = (),
    channel_kind: str | None = None,
    locale: str | None = None,
    route_id: str | None = None,
) -> StructuralFailureAttribution:
    """Select the earliest observed failed stage without inferring from answer prose."""

    if not turn_id.strip() or not answer_digest.strip():
        raise ValueError("structural attribution identity fields MUST be non-empty")
    for label, value in (
        ("channel_kind", channel_kind),
        ("locale", locale),
        ("route_id", route_id),
    ):
        if value is not None and (not value.strip() or len(value) > 256):
            raise ValueError(f"structural attribution {label} MUST be bounded and non-empty")
    by_stage: dict[ConversationStage, StructuralStageObservation] = {}
    for observation in observations:
        if observation.stage in by_stage:
            raise ValueError("structural attribution stages MUST be unique")
        by_stage[observation.stage] = observation
    contributing = tuple(
        stage
        for stage in _STAGE_ORDER
        if stage in by_stage
        and by_stage[stage].outcome in {StageOutcome.FAILED, StageOutcome.UNAVAILABLE}
    )
    root_stage = contributing[0] if contributing else None
    normalized_rubrics = tuple(sorted(set(failed_rubrics)))
    reason_codes = tuple(by_stage[stage].reason_code for stage in contributing)
    evidence_refs = tuple(
        dict.fromkeys(
            evidence_ref for stage in contributing for evidence_ref in by_stage[stage].evidence_refs
        )
    )
    material = "\0".join(
        (
            turn_id,
            answer_digest,
            root_stage.value if root_stage is not None else "none",
            *(stage.value for stage in contributing),
            *normalized_rubrics,
            *reason_codes,
            *evidence_refs,
            channel_kind or "",
            locale or "",
            route_id or "",
        )
    )
    return StructuralFailureAttribution(
        attribution_id="structural-failure:" + hashlib.sha256(material.encode()).hexdigest(),
        turn_id=turn_id,
        root_stage=root_stage,
        contributing_stages=contributing,
        failed_rubrics=normalized_rubrics,
        reason_codes=reason_codes,
        evidence_refs=evidence_refs,
        channel_kind=channel_kind,
        locale=locale,
        route_id=route_id,
    )


def aggregate_structural_failures(
    attributions: tuple[StructuralFailureAttribution, ...],
) -> StructuralFailureSummary:
    """Count root stages, failed rubrics, and reasons without retaining answer content."""

    stage_counts: dict[ConversationStage, int] = {}
    rubric_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    channel_counts: dict[str, int] = {}
    locale_counts: dict[str, int] = {}
    route_counts: dict[str, int] = {}
    for attribution in attributions:
        if attribution.root_stage is not None:
            stage_counts[attribution.root_stage] = stage_counts.get(attribution.root_stage, 0) + 1
        for rubric in attribution.failed_rubrics:
            rubric_counts[rubric] = rubric_counts.get(rubric, 0) + 1
        for reason in attribution.reason_codes:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        for value, counts in (
            (attribution.channel_kind, channel_counts),
            (attribution.locale, locale_counts),
            (attribution.route_id, route_counts),
        ):
            if value is not None:
                counts[value] = counts.get(value, 0) + 1
    return StructuralFailureSummary(
        total_failures=sum(item.root_stage is not None for item in attributions),
        root_stage_counts=tuple(
            (stage, stage_counts[stage]) for stage in _STAGE_ORDER if stage in stage_counts
        ),
        failed_rubric_counts=tuple(
            sorted(rubric_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        reason_code_counts=tuple(
            sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        channel_counts=tuple(sorted(channel_counts.items(), key=lambda item: (-item[1], item[0]))),
        locale_counts=tuple(sorted(locale_counts.items(), key=lambda item: (-item[1], item[0]))),
        route_counts=tuple(sorted(route_counts.items(), key=lambda item: (-item[1], item[0]))),
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
    "ConversationStage",
    "FailureLayer",
    "HoldingOntologyAdequacyInvestigator",
    "OntologyAdequacyInvestigator",
    "OntologyAdequacyReview",
    "OntologyAdequacyReviewSink",
    "StageOutcome",
    "StructuralFailureAttribution",
    "StructuralFailureSummary",
    "StructuralStageObservation",
    "aggregate_structural_failures",
    "attribute_answer_failure",
    "attribute_structural_failure",
    "build_ontology_adequacy_review",
]
