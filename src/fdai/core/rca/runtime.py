"""Runtime orchestration for temporal causal hypotheses and independent closure."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from fdai.shared.contracts.models import Event
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

from .hypothesis import (
    CausalClosure,
    CausalEvidenceAssessment,
    CausalHypothesisRecord,
    build_causal_hypothesis,
    close_causal_hypothesis,
)
from .temporal_causality import (
    TemporalCausalClaim,
    TemporalCausalityAnalyzer,
    TemporalSeries,
)

_MAX_EVIDENCE_REFS = 64
_MAX_PROJECTION_REFS = 32
_MAX_ENDPOINT_OBJECTS = 128
_MAX_REF_LENGTH = 512


@dataclass(frozen=True, slots=True)
class TemporalCausalEvidence:
    """Bounded provider evidence for one temporal causal analysis."""

    cause: TemporalSeries
    effect: TemporalSeries
    feature_cutoff: datetime
    evidence_refs: tuple[str, ...]
    cause_ref: str
    effect_ref: str
    mechanism: str
    graph_revision: str
    finding_id: str
    topological_reachability: float
    mechanism_fit: float
    intervention_consistency: float
    evidence_completeness: float
    ambiguity: int = 1
    confounder: TemporalSeries | None = None
    change_ids: tuple[str, ...] = ()
    supporting_evidence_ids: tuple[str, ...] = ()
    refuting_evidence_ids: tuple[str, ...] = ()
    endpoint_objects: tuple[OntologyObjectRecord, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (
            ("topological_reachability", self.topological_reachability),
            ("mechanism_fit", self.mechanism_fit),
            ("intervention_consistency", self.intervention_consistency),
            ("evidence_completeness", self.evidence_completeness),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"temporal causal evidence {name} MUST be in [0, 1]")
        if self.ambiguity < 1:
            raise ValueError("temporal causal evidence ambiguity MUST be >= 1")
        if self.feature_cutoff.tzinfo is None:
            raise ValueError("temporal causal evidence cutoff MUST be timezone-aware")
        if not all(
            (
                self.evidence_refs,
                self.cause_ref,
                self.effect_ref,
                self.mechanism,
                self.graph_revision,
                self.finding_id,
            )
        ):
            raise ValueError("temporal causal evidence identity MUST be non-empty")
        reference_groups = (
            ("evidence_refs", self.evidence_refs, _MAX_EVIDENCE_REFS),
            ("change_ids", self.change_ids, _MAX_PROJECTION_REFS),
            ("supporting_evidence_ids", self.supporting_evidence_ids, _MAX_PROJECTION_REFS),
            ("refuting_evidence_ids", self.refuting_evidence_ids, _MAX_PROJECTION_REFS),
        )
        for name, references, maximum in reference_groups:
            if len(references) > maximum or len(set(references)) != len(references):
                raise ValueError(f"temporal causal evidence {name} MUST be bounded and unique")
            if any(not reference or len(reference) > _MAX_REF_LENGTH for reference in references):
                raise ValueError(f"temporal causal evidence {name} refs MUST be bounded")
        if len(self.endpoint_objects) > _MAX_ENDPOINT_OBJECTS:
            raise ValueError("temporal causal endpoint objects MUST be bounded")


class TemporalCausalEvidenceProvider(Protocol):
    """Collect bounded time-series and graph evidence for one incident."""

    async def collect(
        self,
        *,
        event: Event,
        incident_id: str,
    ) -> TemporalCausalEvidence | None: ...


class CausalHypothesisProjection(Protocol):
    async def project(
        self,
        hypothesis: CausalHypothesisRecord,
        *,
        finding_id: str,
        change_ids: tuple[str, ...] = (),
        experiment_ids: tuple[str, ...] = (),
        supporting_evidence_ids: tuple[str, ...] = (),
        refuting_evidence_ids: tuple[str, ...] = (),
        outcome_ids: tuple[str, ...] = (),
        previous_hypothesis_id: str | None = None,
        endpoint_objects: tuple[OntologyObjectRecord, ...] = (),
    ) -> None: ...


class CausalRuntimeOutcome(StrEnum):
    ANALYZED = "analyzed"
    NO_EVIDENCE = "no_evidence"
    NO_CLAIM = "no_claim"


@dataclass(frozen=True, slots=True)
class CausalRuntimeResult:
    outcome: CausalRuntimeOutcome
    claim: TemporalCausalClaim | None = None
    hypothesis: CausalHypothesisRecord | None = None


@dataclass(frozen=True, slots=True)
class CausalClosureObservation:
    """Independent observed result used to close one hypothesis revision."""

    hypothesis: CausalHypothesisRecord
    finding_id: str
    outcome_ref: str
    observed_at: datetime
    expected_direction_matched: bool | None
    telemetry_complete: bool
    within_window: bool
    affected_scope_safe: bool
    intervention_approved: bool
    independent_observer: bool
    endpoint_objects: tuple[OntologyObjectRecord, ...] = ()

    def __post_init__(self) -> None:
        if not self.finding_id or not self.outcome_ref:
            raise ValueError("causal closure finding and outcome refs MUST be non-empty")
        if self.observed_at.tzinfo is None:
            raise ValueError("causal closure observed_at MUST be timezone-aware")
        checks = (
            self.telemetry_complete,
            self.within_window,
            self.affected_scope_safe,
            self.intervention_approved,
            self.independent_observer,
        )
        if any(not isinstance(check, bool) for check in checks):
            raise ValueError("causal closure checks MUST be boolean")
        if self.expected_direction_matched is not None and not isinstance(
            self.expected_direction_matched, bool
        ):
            raise ValueError("causal closure direction result MUST be boolean or unknown")


class CausalRuntimeCoordinator:
    """Analyze and project causal revisions without granting action authority."""

    def __init__(
        self,
        *,
        evidence_provider: TemporalCausalEvidenceProvider,
        analyzer: TemporalCausalityAnalyzer,
        projector: CausalHypothesisProjection,
        method_version: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not method_version:
            raise ValueError("causal runtime method_version MUST be non-empty")
        self._evidence_provider = evidence_provider
        self._analyzer = analyzer
        self._projector = projector
        self._method_version = method_version
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def analyze(self, *, event: Event, incident_id: str) -> CausalRuntimeResult:
        evidence = await self._evidence_provider.collect(event=event, incident_id=incident_id)
        if evidence is None:
            return CausalRuntimeResult(CausalRuntimeOutcome.NO_EVIDENCE)
        if evidence.feature_cutoff > event.ingested_at:
            raise ValueError("causal evidence cutoff MUST NOT follow event ingestion")
        claim = self._analyzer.analyze(
            cause=evidence.cause,
            effect=evidence.effect,
            feature_cutoff=evidence.feature_cutoff,
            evidence_refs=evidence.evidence_refs,
            confounder=evidence.confounder,
        )
        if claim is None:
            return CausalRuntimeResult(CausalRuntimeOutcome.NO_CLAIM)
        hypothesis = build_causal_hypothesis(
            incident_id=incident_id,
            cause_ref=evidence.cause_ref,
            effect_ref=evidence.effect_ref,
            mechanism=evidence.mechanism,
            graph_revision=evidence.graph_revision,
            evidence_cutoff=evidence.feature_cutoff,
            method_version=self._method_version,
            evidence_grade=claim.evidence_grade,
            assessment=CausalEvidenceAssessment(
                temporal_precedence=abs(claim.correlation),
                topological_reachability=evidence.topological_reachability,
                mechanism_fit=evidence.mechanism_fit,
                intervention_consistency=evidence.intervention_consistency,
                evidence_completeness=evidence.evidence_completeness,
                ambiguity=evidence.ambiguity,
                supporting_refs=evidence.supporting_evidence_ids,
                refuting_refs=evidence.refuting_evidence_ids,
            ),
            created_at=self._clock(),
        )
        await self._projector.project(
            hypothesis,
            finding_id=evidence.finding_id,
            change_ids=evidence.change_ids,
            supporting_evidence_ids=evidence.supporting_evidence_ids,
            refuting_evidence_ids=evidence.refuting_evidence_ids,
            endpoint_objects=evidence.endpoint_objects,
        )
        return CausalRuntimeResult(
            CausalRuntimeOutcome.ANALYZED,
            claim=claim,
            hypothesis=hypothesis,
        )

    async def close(self, observation: CausalClosureObservation) -> CausalHypothesisRecord:
        closure = _classify_closure(observation)
        closed = close_causal_hypothesis(
            observation.hypothesis,
            closure=closure,
            outcome_ref=observation.outcome_ref,
            created_at=observation.observed_at,
        )
        await self._projector.project(
            closed,
            finding_id=observation.finding_id,
            outcome_ids=(observation.outcome_ref,),
            previous_hypothesis_id=observation.hypothesis.hypothesis_id,
            endpoint_objects=observation.endpoint_objects,
        )
        return closed


def _classify_closure(observation: CausalClosureObservation) -> CausalClosure:
    if not observation.affected_scope_safe:
        return CausalClosure.UNSAFE
    if (
        not observation.telemetry_complete
        or not observation.within_window
        or not observation.independent_observer
        or observation.expected_direction_matched is None
    ):
        return CausalClosure.INCONCLUSIVE
    if not observation.expected_direction_matched:
        return CausalClosure.REFUTED
    if not observation.intervention_approved:
        return CausalClosure.INCONCLUSIVE
    return CausalClosure.CONFIRMED


__all__ = [
    "CausalClosureObservation",
    "CausalHypothesisProjection",
    "CausalRuntimeCoordinator",
    "CausalRuntimeOutcome",
    "CausalRuntimeResult",
    "TemporalCausalEvidence",
    "TemporalCausalEvidenceProvider",
]
