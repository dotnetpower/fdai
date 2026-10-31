"""Evidence-bounded deterministic RCA for distributed trace discontinuities."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from fdai.core.detection.trace_continuity import (
    TraceContinuityReason,
    TraceContinuityResult,
    TraceContinuityState,
)
from fdai.core.rca.contract import (
    CauseDomain,
    Citation,
    CitationKind,
    RcaOutcome,
    RcaResult,
    RcaTier,
    RootCauseHypothesis,
)
from fdai.core.rca.grounding import enforce_grounding

_MAX_AFFECTED_ITEMS = 32
_MAX_AFFECTED_TEXT_CHARS = 1024
_MAX_EVIDENCE_REFS = 100
_MAX_EVIDENCE_AGE = timedelta(hours=24)


class TraceRcaCause(StrEnum):
    """Reviewed trace-discontinuity cause classes."""

    INSTRUMENTATION = "instrumentation"
    COLLECTOR = "collector"
    HEADER_PROPAGATION = "header_propagation"


@dataclass(frozen=True, slots=True)
class TraceCauseEvidence:
    """Independent telemetry evidence supporting one bounded cause class."""

    cause: TraceRcaCause
    topology_ref: str
    scenario_id: str
    window_bucket: str
    observed_at: datetime
    confidence: float
    affected_items: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.cause, TraceRcaCause):
            raise ValueError("trace cause MUST be a TraceRcaCause")
        for name, value in (
            ("topology_ref", self.topology_ref),
            ("scenario_id", self.scenario_id),
            ("window_bucket", self.window_bucket),
        ):
            if not value or value != value.strip() or len(value) > 512:
                raise ValueError(f"trace cause {name} MUST be bounded non-empty text")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("trace cause observed_at MUST be timezone-aware")
        if (
            isinstance(self.confidence, bool)
            or not math.isfinite(self.confidence)
            or not 0.0 <= self.confidence <= 1.0
        ):
            raise ValueError("trace cause confidence MUST be finite and in [0, 1]")
        if not 1 <= len(self.affected_items) <= _MAX_AFFECTED_ITEMS:
            raise ValueError(
                f"trace cause affected_items MUST contain 1 to {_MAX_AFFECTED_ITEMS} items"
            )
        if not 1 <= len(self.evidence_refs) <= _MAX_EVIDENCE_REFS:
            raise ValueError(
                f"trace cause evidence_refs MUST contain 1 to {_MAX_EVIDENCE_REFS} items"
            )
        if any(not item or item != item.strip() or len(item) > 128 for item in self.affected_items):
            raise ValueError("trace cause affected_items MUST be bounded non-empty text")
        if sum(map(len, self.affected_items)) > _MAX_AFFECTED_TEXT_CHARS:
            raise ValueError(
                f"trace cause affected_items MUST contain at most "
                f"{_MAX_AFFECTED_TEXT_CHARS} characters"
            )
        if any(not ref or ref != ref.strip() or len(ref) > 512 for ref in self.evidence_refs):
            raise ValueError("trace cause evidence_refs MUST be bounded non-empty text")
        if len(set(self.affected_items)) != len(self.affected_items):
            raise ValueError("trace cause affected_items MUST be unique")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("trace cause evidence_refs MUST be unique")
        object.__setattr__(self, "affected_items", tuple(sorted(self.affected_items)))
        object.__setattr__(self, "evidence_refs", tuple(sorted(self.evidence_refs)))


def analyze_trace_continuity_cause(
    result: TraceContinuityResult,
    *,
    cause_evidence: tuple[TraceCauseEvidence, ...],
    min_confidence: float = 0.5,
    max_evidence_age: timedelta = timedelta(minutes=5),
) -> RcaResult:
    """Return one cited T1 cause or hold when evidence is absent or conflicting."""

    if (
        isinstance(min_confidence, bool)
        or not math.isfinite(min_confidence)
        or not 0.0 <= min_confidence <= 1.0
    ):
        raise ValueError("min_confidence MUST be in [0, 1]")
    if not timedelta(0) < max_evidence_age <= _MAX_EVIDENCE_AGE:
        raise ValueError("max_evidence_age MUST be positive and at most 24 hours")
    if result.state is not TraceContinuityState.DISCONTINUOUS:
        return _abstained("trace_not_discontinuous")
    if not result.evidence_refs:
        return _abstained("trace_continuity_evidence_missing")
    if not cause_evidence:
        return _abstained("trace_cause_evidence_missing")
    if len(cause_evidence) != 1:
        return _abstained("trace_cause_evidence_conflicting")

    selected = cause_evidence[0]
    if not _evidence_matches(
        result,
        selected,
        max_evidence_age=max_evidence_age,
    ):
        return _abstained("trace_cause_evidence_scope_mismatch")

    combined_refs = tuple(dict.fromkeys((*result.evidence_refs, *selected.evidence_refs)))
    if len(combined_refs) > _MAX_EVIDENCE_REFS:
        return _abstained("trace_citation_limit_exceeded")
    citations = tuple(Citation(kind=CitationKind.TELEMETRY, ref=ref) for ref in combined_refs)
    hypothesis = RootCauseHypothesis(
        tier=RcaTier.T1,
        cause=_cause_text(selected),
        confidence=min(0.85, selected.confidence),
        citations=citations,
        cause_domain=_cause_domain(selected.cause),
        evidence_refs=tuple(citation.ref for citation in citations),
        remediation_ref=None,
    )
    return enforce_grounding(hypothesis, min_confidence=min_confidence)


def _evidence_matches(
    result: TraceContinuityResult,
    evidence: TraceCauseEvidence,
    *,
    max_evidence_age: timedelta,
) -> bool:
    if (
        evidence.topology_ref != result.topology_ref
        or evidence.scenario_id != result.scenario_id
        or evidence.window_bucket != result.window_bucket
        or result.observed_at is None
        or evidence.observed_at > result.observed_at
        or result.observed_at - evidence.observed_at > max_evidence_age
    ):
        return False
    affected = set(evidence.affected_items)
    if evidence.cause is TraceRcaCause.HEADER_PROPAGATION:
        allowed = set(result.disconnected_boundaries)
        if result.reason is TraceContinuityReason.CONTEXT_DROPPED:
            allowed.update(_missing_hop_boundaries(result))
        return (
            result.reason
            in {
                TraceContinuityReason.CONTEXT_REGENERATED,
                TraceContinuityReason.CONTEXT_DROPPED,
            }
            and affected <= allowed
        )
    if evidence.cause is TraceRcaCause.INSTRUMENTATION:
        return result.reason is TraceContinuityReason.CONTEXT_DROPPED and affected <= set(
            result.missing_hops
        )
    return result.reason is TraceContinuityReason.CONTEXT_DROPPED and affected <= set(
        result.missing_hops
    )


def _missing_hop_boundaries(result: TraceContinuityResult) -> tuple[str, ...]:
    missing = set(result.missing_hops)
    return tuple(
        f"{upstream}->{downstream}"
        for upstream, downstream in zip(
            result.expected_hops,
            result.expected_hops[1:],
            strict=False,
        )
        if upstream in missing or downstream in missing
    )


def _cause_text(evidence: TraceCauseEvidence) -> str:
    targets = ", ".join(evidence.affected_items)
    if evidence.cause is TraceRcaCause.INSTRUMENTATION:
        return f"trace instrumentation missing or invalid at hops: {targets}"
    if evidence.cause is TraceRcaCause.COLLECTOR:
        return f"telemetry collector did not retain spans for hops: {targets}"
    return f"trace context propagation failed at boundaries: {targets}"


def _cause_domain(cause: TraceRcaCause) -> CauseDomain:
    if cause is TraceRcaCause.COLLECTOR:
        return CauseDomain.SHARED_DEPENDENCY
    if cause is TraceRcaCause.INSTRUMENTATION:
        return CauseDomain.APPLICATION
    return CauseDomain.UNKNOWN


def _abstained(reason: str) -> RcaResult:
    return RcaResult(
        outcome=RcaOutcome.ABSTAINED,
        hypothesis=None,
        reason=reason,
    )


__all__ = [
    "TraceCauseEvidence",
    "TraceRcaCause",
    "analyze_trace_continuity_cause",
]
