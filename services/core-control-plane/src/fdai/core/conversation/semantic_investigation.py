"""Verify span-anchored investigation intent before ontology planning."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Annotated, Any, Literal

from fdai_service_contracts.ontology_query import SemanticOperation, content_digest
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_INTENT_ID_PATTERN = r"^[a-z][a-z0-9_.-]{0,79}$"
_MAX_UTTERANCE_CHARS = 32_000


class _IntentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class InvestigationEntityRole(StrEnum):
    """Role an entity mention plays in one read-only investigation."""

    AFFECTED_TARGET = "affected_target"
    CAUSE_CANDIDATE = "cause_candidate"
    COMPARISON_TARGET = "comparison_target"
    SCOPE_ANCHOR = "scope_anchor"


class InvestigationTemporalRole(StrEnum):
    """Meaning of an exact temporal cue without resolving server time."""

    BASELINE = "baseline"
    CHANGE_POINT = "change_point"
    CURRENT_WINDOW = "current_window"
    LOOKBACK = "lookback"
    ONSET = "onset"


class InvestigationEvidenceStandard(StrEnum):
    """Minimum evidence posture requested by the operator intent."""

    BEST_AVAILABLE = "best_available"
    COMPLETE_WINDOWS = "complete_windows"
    SUPPORT_AND_REFUTATION = "support_and_refutation"


class InvestigationAnswerShape(StrEnum):
    """Bounded answer family selected before presentation planning."""

    COMPARISON = "comparison"
    DIAGNOSIS = "diagnosis"
    TIMELINE = "timeline"


class InvestigationMeasureDirection(StrEnum):
    """Expected symptom direction relative to its aligned baseline."""

    DECREASE = "decrease"
    INCREASE = "increase"


class IntentSourceSpan(_IntentRecord):
    """Exact Python code-point range in the current operator utterance."""

    start: int = Field(ge=0, le=_MAX_UTTERANCE_CHARS)
    end: int = Field(gt=0, le=_MAX_UTTERANCE_CHARS)
    text: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def _ordered_non_control_span(self) -> IntentSourceSpan:
        if self.end <= self.start:
            raise ValueError("investigation source span end MUST follow start")
        if not self.text.strip() or "\r" in self.text or "\n" in self.text:
            raise ValueError("investigation source span text MUST be one non-empty line")
        return self


class InvestigationEntityMention(_IntentRecord):
    """Candidate entity role anchored to operator-authored text."""

    mention_id: Annotated[str, Field(pattern=_INTENT_ID_PATTERN)]
    span: IntentSourceSpan
    role: InvestigationEntityRole
    object_type_candidates: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...] = Field(
        min_length=1, max_length=8
    )

    @field_validator("object_type_candidates")
    @classmethod
    def _unique_types(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("investigation entity type candidates MUST be unique")
        return values


class InvestigationSymptomMeasure(_IntentRecord):
    """Candidate symptom metric anchored to operator-authored text."""

    measure_id: Annotated[str, Field(pattern=_INTENT_ID_PATTERN)]
    span: IntentSourceSpan
    concept_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")]
    target_mention_id: Annotated[str, Field(pattern=_INTENT_ID_PATTERN)]
    direction: InvestigationMeasureDirection


class InvestigationTemporalCue(_IntentRecord):
    """Unresolved time-language cue that Core must bind to trusted time."""

    cue_id: Annotated[str, Field(pattern=_INTENT_ID_PATTERN)]
    span: IntentSourceSpan
    role: InvestigationTemporalRole


class InvestigationRelationshipIntent(_IntentRecord):
    """Candidate manifest LinkType sides for one graph-expansion request."""

    relationship_id: Annotated[str, Field(pattern=_INTENT_ID_PATTERN)]
    span: IntentSourceSpan
    source_mention_id: Annotated[str, Field(pattern=_INTENT_ID_PATTERN)]
    target_mention_id: Annotated[str, Field(pattern=_INTENT_ID_PATTERN)] | None = None
    query_side_candidates: tuple[
        Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,159}$")], ...
    ] = Field(min_length=1, max_length=16)

    @field_validator("query_side_candidates")
    @classmethod
    def _unique_query_sides(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("investigation relationship candidates MUST be unique")
        return values


class InvestigationHypothesis(_IntentRecord):
    """One candidate mechanism to test with supporting and refuting evidence."""

    hypothesis_id: Annotated[str, Field(pattern=_INTENT_ID_PATTERN)]
    span: IntentSourceSpan
    relationship_id: Annotated[str, Field(pattern=_INTENT_ID_PATTERN)]
    cause_measure_concept: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")]
    effect_measure_id: Annotated[str, Field(pattern=_INTENT_ID_PATTERN)]
    competing_explanations: tuple[Annotated[str, Field(pattern=_INTENT_ID_PATTERN)], ...] = Field(
        default=(), max_length=8
    )

    @field_validator("competing_explanations")
    @classmethod
    def _unique_competitors(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("investigation competing explanations MUST be unique")
        return values


class InvestigationIntentProposal(_IntentRecord):
    """Untrusted model proposal for a bounded read-only investigation."""

    operation: SemanticOperation
    entities: tuple[InvestigationEntityMention, ...] = Field(min_length=1, max_length=8)
    symptom_measures: tuple[InvestigationSymptomMeasure, ...] = Field(min_length=1, max_length=4)
    primary_symptom_measure_id: Annotated[str, Field(pattern=_INTENT_ID_PATTERN)]
    temporal_cues: tuple[InvestigationTemporalCue, ...] = Field(min_length=1, max_length=4)
    relationship_intents: tuple[InvestigationRelationshipIntent, ...] = Field(
        min_length=1, max_length=8
    )
    hypotheses: tuple[InvestigationHypothesis, ...] = Field(min_length=2, max_length=4)
    evidence_standard: InvestigationEvidenceStandard
    answer_shape: InvestigationAnswerShape
    confidence: float = Field(ge=0.0, le=1.0)


class VerifiedInvestigationIntent(_IntentRecord):
    """Content-addressed read-only intent after deterministic grounding checks."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    operation: Literal[SemanticOperation.EXPLAIN_CHANGE]
    entities: tuple[InvestigationEntityMention, ...]
    symptom_measures: tuple[InvestigationSymptomMeasure, ...]
    primary_symptom_measure_id: str
    temporal_cues: tuple[InvestigationTemporalCue, ...]
    relationship_intents: tuple[InvestigationRelationshipIntent, ...]
    hypotheses: tuple[InvestigationHypothesis, ...]
    evidence_standard: Literal[InvestigationEvidenceStandard.SUPPORT_AND_REFUTATION]
    answer_shape: Literal[InvestigationAnswerShape.DIAGNOSIS]
    confidence: float = Field(ge=0.0, le=1.0)
    input_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    intent_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    authority: Literal["candidate_only"] = "candidate_only"
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _digest_matches_content(self) -> VerifiedInvestigationIntent:
        body = self.model_dump(mode="json", exclude={"intent_digest"})
        if self.intent_digest != content_digest(body):
            raise ValueError("verified investigation intent digest does not match its content")
        return self


def verify_investigation_intent(
    proposal: InvestigationIntentProposal,
    *,
    utterance: str,
    descriptors: Sequence[Mapping[str, Any]],
    metric_concepts: Sequence[str],
) -> VerifiedInvestigationIntent:
    """Ground one causal investigation proposal or reject it before any read."""

    if not utterance.strip() or len(utterance) > _MAX_UTTERANCE_CHARS:
        raise ValueError("investigation utterance MUST be non-empty and bounded")
    if proposal.operation is not SemanticOperation.EXPLAIN_CHANGE:
        raise ValueError("investigation intent MUST use explain_change")
    if proposal.evidence_standard is not InvestigationEvidenceStandard.SUPPORT_AND_REFUTATION:
        raise ValueError("causal investigation requires support and refutation evidence")
    if proposal.answer_shape is not InvestigationAnswerShape.DIAGNOSIS:
        raise ValueError("causal investigation requires a diagnosis answer shape")

    _verify_source_spans(proposal, utterance=utterance)
    entity_by_id = _verify_entities(proposal.entities, descriptors=descriptors)
    _verify_measures(
        proposal,
        entity_by_id=entity_by_id,
        metric_concepts=metric_concepts,
    )
    _verify_relationships(
        proposal.relationship_intents,
        entity_by_id=entity_by_id,
        descriptors=descriptors,
    )
    _verify_hypotheses(
        proposal.hypotheses,
        relationship_ids={item.relationship_id for item in proposal.relationship_intents},
        measure_ids={item.measure_id for item in proposal.symptom_measures},
        metric_concepts=metric_concepts,
    )
    if not any(
        entity.role is InvestigationEntityRole.AFFECTED_TARGET for entity in proposal.entities
    ):
        raise ValueError("investigation intent requires one affected target")
    if not any(
        cue.role in {InvestigationTemporalRole.CHANGE_POINT, InvestigationTemporalRole.ONSET}
        for cue in proposal.temporal_cues
    ):
        raise ValueError("causal investigation requires an onset or change-point cue")

    canonical = proposal.model_dump(mode="json")
    canonical["entities"] = sorted(canonical["entities"], key=lambda item: item["mention_id"])
    canonical["symptom_measures"] = sorted(
        canonical["symptom_measures"], key=lambda item: item["measure_id"]
    )
    canonical["temporal_cues"] = sorted(canonical["temporal_cues"], key=lambda item: item["cue_id"])
    canonical["relationship_intents"] = sorted(
        canonical["relationship_intents"], key=lambda item: item["relationship_id"]
    )
    canonical["hypotheses"] = sorted(
        canonical["hypotheses"], key=lambda item: item["hypothesis_id"]
    )
    canonical["input_digest"] = content_digest({"utterance": utterance})
    canonical["authority"] = "candidate_only"
    canonical["execution_authority"] = False
    body = {"schema_version": "1.0.0", **canonical}
    return VerifiedInvestigationIntent.model_validate(
        {**body, "intent_digest": content_digest(body)}
    )


def _verify_source_spans(
    proposal: InvestigationIntentProposal,
    *,
    utterance: str,
) -> None:
    records: tuple[
        InvestigationEntityMention
        | InvestigationSymptomMeasure
        | InvestigationTemporalCue
        | InvestigationRelationshipIntent
        | InvestigationHypothesis,
        ...,
    ] = (
        *proposal.entities,
        *proposal.symptom_measures,
        *proposal.temporal_cues,
        *proposal.relationship_intents,
        *proposal.hypotheses,
    )
    for record in records:
        span = record.span
        if span.end > len(utterance) or utterance[span.start : span.end] != span.text:
            raise ValueError("investigation source span does not match the utterance")


def _verify_entities(
    entities: tuple[InvestigationEntityMention, ...],
    *,
    descriptors: Sequence[Mapping[str, Any]],
) -> dict[str, InvestigationEntityMention]:
    available_types = {
        name
        for descriptor in descriptors
        if descriptor.get("kind") in {"object", "interface"}
        if isinstance((name := descriptor.get("name")), str)
    }
    by_id: dict[str, InvestigationEntityMention] = {}
    for entity in entities:
        if entity.mention_id in by_id:
            raise ValueError("investigation entity ids MUST be unique")
        if not set(entity.object_type_candidates) <= available_types:
            raise ValueError("investigation entity type is absent from the principal manifest")
        by_id[entity.mention_id] = entity
    return by_id


def _verify_measures(
    proposal: InvestigationIntentProposal,
    *,
    entity_by_id: Mapping[str, InvestigationEntityMention],
    metric_concepts: Sequence[str],
) -> None:
    available_metrics = frozenset(metric_concepts)
    measure_ids: set[str] = set()
    for measure in proposal.symptom_measures:
        if measure.measure_id in measure_ids:
            raise ValueError("investigation measure ids MUST be unique")
        if measure.target_mention_id not in entity_by_id:
            raise ValueError("investigation measure target is unknown")
        if measure.concept_id not in available_metrics:
            raise ValueError("investigation metric concept is unavailable")
        measure_ids.add(measure.measure_id)
    if proposal.primary_symptom_measure_id not in measure_ids:
        raise ValueError("investigation primary symptom measure is unknown")


def _verify_relationships(
    relationships: tuple[InvestigationRelationshipIntent, ...],
    *,
    entity_by_id: Mapping[str, InvestigationEntityMention],
    descriptors: Sequence[Mapping[str, Any]],
) -> None:
    available_sides = _relationship_sides(descriptors)
    relationship_ids: set[str] = set()
    for relationship in relationships:
        if relationship.relationship_id in relationship_ids:
            raise ValueError("investigation relationship ids MUST be unique")
        relationship_ids.add(relationship.relationship_id)
        source = entity_by_id.get(relationship.source_mention_id)
        target = (
            entity_by_id.get(relationship.target_mention_id)
            if relationship.target_mention_id is not None
            else None
        )
        if source is None or (relationship.target_mention_id is not None and target is None):
            raise ValueError("investigation relationship endpoint is unknown")
        current_types = set(source.object_type_candidates)
        for query_side in relationship.query_side_candidates:
            endpoints = available_sides.get(query_side)
            if endpoints is None:
                raise ValueError("investigation relationship side is absent from the manifest")
            source_type, target_type = endpoints
            if source_type not in current_types:
                raise ValueError("investigation relationship source type does not match")
            current_types = {target_type}
        if target is not None and current_types.isdisjoint(target.object_type_candidates):
            raise ValueError("investigation relationship target type does not match")


def _relationship_sides(
    descriptors: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for descriptor in descriptors:
        if descriptor.get("kind") != "link":
            continue
        from_type = descriptor.get("from_type")
        to_type = descriptor.get("to_type")
        query_sides = descriptor.get("query_sides")
        if not isinstance(from_type, str) or not isinstance(to_type, str):
            continue
        if not isinstance(query_sides, Mapping):
            continue
        for side in query_sides.values():
            if not isinstance(side, Mapping):
                continue
            query_id = side.get("query_id")
            direction = side.get("direction")
            if not isinstance(query_id, str):
                continue
            endpoints = (from_type, to_type) if direction == "outgoing" else (to_type, from_type)
            if query_id in result and result[query_id] != endpoints:
                raise ValueError("investigation query side identity is ambiguous")
            result[query_id] = endpoints
    return result


def _verify_hypotheses(
    hypotheses: tuple[InvestigationHypothesis, ...],
    *,
    relationship_ids: set[str],
    measure_ids: set[str],
    metric_concepts: Sequence[str],
) -> None:
    available_metrics = frozenset(metric_concepts)
    hypothesis_ids: set[str] = set()
    for hypothesis in hypotheses:
        if hypothesis.hypothesis_id in hypothesis_ids:
            raise ValueError("investigation hypothesis ids MUST be unique")
        if hypothesis.relationship_id not in relationship_ids:
            raise ValueError("investigation hypothesis relationship is unknown")
        if hypothesis.effect_measure_id not in measure_ids:
            raise ValueError("investigation hypothesis effect measure is unknown")
        if hypothesis.cause_measure_concept not in available_metrics:
            raise ValueError("investigation hypothesis metric concept is unavailable")
        hypothesis_ids.add(hypothesis.hypothesis_id)
    for hypothesis in hypotheses:
        unknown = set(hypothesis.competing_explanations) - hypothesis_ids
        if unknown or hypothesis.hypothesis_id in hypothesis.competing_explanations:
            raise ValueError("investigation hypothesis competitors are invalid")


__all__ = [
    "IntentSourceSpan",
    "InvestigationAnswerShape",
    "InvestigationEntityMention",
    "InvestigationEntityRole",
    "InvestigationEvidenceStandard",
    "InvestigationHypothesis",
    "InvestigationIntentProposal",
    "InvestigationMeasureDirection",
    "InvestigationRelationshipIntent",
    "InvestigationSymptomMeasure",
    "InvestigationTemporalCue",
    "InvestigationTemporalRole",
    "VerifiedInvestigationIntent",
    "verify_investigation_intent",
]
