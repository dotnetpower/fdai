"""Deterministic declaration-to-perspective applicability for question cases."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class QuestionPerspective(StrEnum):
    """Reviewed operational lenses that a question case may exercise."""

    RESOURCE = "resource"
    SERVICE = "service"
    OPERATION = "operation"
    POLICY = "policy"
    BUSINESS = "business"
    CAUSAL = "causal"
    ACTION = "action"


class QuestionEvidencePosture(StrEnum):
    """Evidence condition that the terminal answer must preserve."""

    FRESH = "fresh"
    STALE = "stale"
    INCOMPLETE = "incomplete"
    CONFLICTING = "conflicting"
    UNAVAILABLE = "unavailable"


class QuestionAnchorKind(StrEnum):
    """Server-owned context required to execute one question case."""

    NONE = "none"
    SELECTED_OBJECT = "selected_object"
    SELECTED_INCIDENT = "selected_incident"
    SERVER_SCOPE = "server_scope"


class QuestionExpectedPosture(StrEnum):
    """Allowed terminal behavior for one deterministic question case."""

    ANSWER = "answer"
    CLARIFY = "clarify"
    HOLD = "hold"
    UNSUPPORTED = "unsupported"
    ACTION_DRAFT = "action_draft"


class QuestionCapabilityFamily(StrEnum):
    """Minimum verified semantic capability required by a question case."""

    DECLARATION = "declaration"
    OBJECT_SET = "object_set"
    TOPOLOGY = "topology"
    POLICY_REFERENCE = "policy_reference"
    EVIDENCE_JOIN = "evidence_join"
    ACTION_DRAFT = "action_draft"


class QuestionRuleState(StrEnum):
    """Policy authority posture for Rule declaration question cases."""

    NOT_APPLICABLE = "not_applicable"
    ACTIVE = "active"
    COLLECTED = "collected"


class QuestionEntityState(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    EXACT = "exact"
    AMBIGUOUS = "ambiguous"
    MISSING = "missing"


class QuestionTemporalState(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    ALIGNED = "aligned"
    STALE_BASELINE = "stale_baseline"
    PARTIAL_CURRENT = "partial_current"


class QuestionCausalResult(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    SUPPORTED = "supported"
    REFUTED = "refuted"
    COMPETING = "competing"
    UNRESOLVED = "unresolved"


class QuestionPresentationShape(StrEnum):
    DEFAULT = "default"
    TABLE = "table"
    TIMELINE = "timeline"


@dataclass(frozen=True, slots=True)
class QuestionInvestigationPosture:
    entity_state: QuestionEntityState = QuestionEntityState.NOT_APPLICABLE
    temporal_state: QuestionTemporalState = QuestionTemporalState.NOT_APPLICABLE
    causal_result: QuestionCausalResult = QuestionCausalResult.NOT_APPLICABLE
    presentation_shape: QuestionPresentationShape = QuestionPresentationShape.DEFAULT


@dataclass(frozen=True, slots=True)
class QuestionPerspectiveApplication:
    """One reviewed perspective allowed for a declaration descriptor."""

    perspective: QuestionPerspective
    capability: QuestionCapabilityFamily
    anchor_kind: QuestionAnchorKind
    action_posture: str = "advise_only"
    rule_state: QuestionRuleState = QuestionRuleState.NOT_APPLICABLE
    investigation: QuestionInvestigationPosture = QuestionInvestigationPosture()


_OBJECT_PERSPECTIVES: dict[str, tuple[QuestionPerspective, ...]] = {
    "Resource": (QuestionPerspective.RESOURCE, QuestionPerspective.OPERATION),
    "ResourceType": (QuestionPerspective.RESOURCE, QuestionPerspective.POLICY),
    "BusinessCapability": (QuestionPerspective.BUSINESS,),
    "BusinessService": (QuestionPerspective.SERVICE, QuestionPerspective.BUSINESS),
    "Workload": (QuestionPerspective.SERVICE, QuestionPerspective.OPERATION),
    "Incident": (QuestionPerspective.OPERATION, QuestionPerspective.CAUSAL),
    "Change": (QuestionPerspective.OPERATION, QuestionPerspective.CAUSAL),
    "Rule": (QuestionPerspective.POLICY,),
    "PolicyArtifact": (QuestionPerspective.POLICY,),
    "ServiceObjective": (QuestionPerspective.BUSINESS, QuestionPerspective.OPERATION),
    "CausalHypothesis": (QuestionPerspective.CAUSAL,),
}


def perspective_applications(
    descriptor: dict[str, Any],
) -> tuple[QuestionPerspectiveApplication, ...]:
    """Map one descriptor to reviewed perspectives without Cartesian expansion."""

    kind = descriptor["kind"]
    name = descriptor["name"]
    if kind == "action":
        return (
            QuestionPerspectiveApplication(
                perspective=QuestionPerspective.ACTION,
                capability=QuestionCapabilityFamily.ACTION_DRAFT,
                anchor_kind=QuestionAnchorKind.SELECTED_OBJECT,
                action_posture="draft_only",
            ),
            QuestionPerspectiveApplication(
                perspective=QuestionPerspective.POLICY,
                capability=QuestionCapabilityFamily.POLICY_REFERENCE,
                anchor_kind=QuestionAnchorKind.NONE,
                action_posture="draft_only",
            ),
        )
    if kind == "object":
        if name == "Rule":
            return tuple(
                QuestionPerspectiveApplication(
                    perspective=QuestionPerspective.POLICY,
                    capability=QuestionCapabilityFamily.POLICY_REFERENCE,
                    anchor_kind=QuestionAnchorKind.SERVER_SCOPE,
                    rule_state=rule_state,
                )
                for rule_state in (QuestionRuleState.ACTIVE, QuestionRuleState.COLLECTED)
            )
        perspectives = _OBJECT_PERSPECTIVES.get(name, (QuestionPerspective.OPERATION,))
        return tuple(
            QuestionPerspectiveApplication(
                perspective=perspective,
                capability=_capability_for_perspective(perspective),
                anchor_kind=_anchor_for_object(name, perspective),
                investigation=_investigation_posture(perspective),
            )
            for perspective in perspectives
        )
    if kind == "link":
        link_perspectives: list[QuestionPerspective] = [QuestionPerspective.SERVICE]
        if descriptor.get("is_causal") is True:
            link_perspectives.append(QuestionPerspective.CAUSAL)
        return tuple(
            QuestionPerspectiveApplication(
                perspective=perspective,
                capability=_capability_for_perspective(perspective),
                anchor_kind=QuestionAnchorKind.SERVER_SCOPE,
                investigation=_investigation_posture(perspective),
            )
            for perspective in link_perspectives
        )
    if kind == "function":
        return (
            QuestionPerspectiveApplication(
                perspective=QuestionPerspective.OPERATION,
                capability=QuestionCapabilityFamily.DECLARATION,
                anchor_kind=QuestionAnchorKind.SERVER_SCOPE,
            ),
        )
    return (
        QuestionPerspectiveApplication(
            perspective=QuestionPerspective.POLICY,
            capability=QuestionCapabilityFamily.DECLARATION,
            anchor_kind=QuestionAnchorKind.NONE,
        ),
    )


def expected_question_posture(
    perspective: QuestionPerspective,
    *,
    access_filtered: bool,
    evidence_posture: QuestionEvidencePosture,
) -> QuestionExpectedPosture:
    """Resolve the safe terminal posture without inspecting question wording."""

    if evidence_posture is not QuestionEvidencePosture.FRESH or access_filtered:
        return QuestionExpectedPosture.HOLD
    if perspective is QuestionPerspective.ACTION:
        return QuestionExpectedPosture.ACTION_DRAFT
    return QuestionExpectedPosture.ANSWER


def _capability_for_perspective(
    perspective: QuestionPerspective,
) -> QuestionCapabilityFamily:
    if perspective is QuestionPerspective.CAUSAL:
        return QuestionCapabilityFamily.EVIDENCE_JOIN
    if perspective is QuestionPerspective.SERVICE:
        return QuestionCapabilityFamily.TOPOLOGY
    if perspective is QuestionPerspective.POLICY:
        return QuestionCapabilityFamily.POLICY_REFERENCE
    return QuestionCapabilityFamily.OBJECT_SET


def _anchor_for_object(
    name: str,
    perspective: QuestionPerspective,
) -> QuestionAnchorKind:
    if name in {"Incident", "Change"}:
        return QuestionAnchorKind.SELECTED_INCIDENT
    if perspective in {QuestionPerspective.RESOURCE, QuestionPerspective.SERVICE}:
        return QuestionAnchorKind.SELECTED_OBJECT
    return QuestionAnchorKind.SERVER_SCOPE


def _investigation_posture(
    perspective: QuestionPerspective,
) -> QuestionInvestigationPosture:
    if perspective is not QuestionPerspective.CAUSAL:
        return QuestionInvestigationPosture()
    return QuestionInvestigationPosture(
        entity_state=QuestionEntityState.EXACT,
        temporal_state=QuestionTemporalState.ALIGNED,
        causal_result=QuestionCausalResult.COMPETING,
        presentation_shape=QuestionPresentationShape.TABLE,
    )


__all__ = [
    "QuestionAnchorKind",
    "QuestionCapabilityFamily",
    "QuestionEvidencePosture",
    "QuestionEntityState",
    "QuestionTemporalState",
    "QuestionCausalResult",
    "QuestionPresentationShape",
    "QuestionInvestigationPosture",
    "QuestionExpectedPosture",
    "QuestionPerspective",
    "QuestionPerspectiveApplication",
    "QuestionRuleState",
    "expected_question_posture",
    "perspective_applications",
]
