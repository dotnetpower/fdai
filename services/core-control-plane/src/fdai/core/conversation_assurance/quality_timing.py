"""Bind latency SLO and complete-trace evidence for qualification."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from fdai.core.conversation_assurance.quality_latency import (
    CHATOPS_LATENCY_CONTRACT_V1,
    ChatOpsLatencyEvidence,
)
from fdai.core.conversation_assurance.quality_qualification import (
    QualificationEvidence,
)
from fdai.core.conversation_assurance.quality_trace import (
    CorrelationTraceEvidence,
    trace_set_digest,
)


@dataclass(frozen=True, slots=True)
class CorrelationTraceCohortEvidence:
    source_revision: str
    minimum_traces: int
    trace_count: int
    trace_set_digest: str
    complete_trace: bool
    gaps: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "1.0.0",
            "evidence_kind": "chatops_correlation_trace_cohort",
            "qualification_authority": False,
            "source_revision": self.source_revision,
            "minimum_traces": self.minimum_traces,
            "trace_count": self.trace_count,
            "trace_set_digest": self.trace_set_digest,
            "complete_trace": self.complete_trace,
            "gaps": list(self.gaps),
        }
        payload["content_digest"] = _digest(payload)
        return payload


def reduce_trace_cohort(
    traces: tuple[CorrelationTraceEvidence, ...],
    *,
    minimum_traces: int = 500,
) -> CorrelationTraceCohortEvidence:
    """Require a complete unique trace for every committed qualification trace."""

    if type(minimum_traces) is not int or minimum_traces < 1:
        raise ValueError("minimum_traces MUST be a positive integer")
    if not traces:
        raise ValueError("trace cohort MUST contain evidence")
    revisions = {trace.source_revision for trace in traces}
    if len(revisions) != 1:
        raise ValueError("trace cohort source revisions MUST match")
    correlations = tuple(
        trace.correlation_digest for trace in traces if trace.correlation_digest is not None
    )
    gaps: list[str] = []
    if len(traces) < minimum_traces:
        gaps.append(f"trace_count={len(traces)}<minimum_traces={minimum_traces}")
    if len(correlations) != len(traces):
        gaps.append("missing_correlation_digest")
    if len(correlations) != len(set(correlations)):
        gaps.append("duplicate_correlation_digest")
    incomplete = sum(not trace.complete_trace for trace in traces)
    if incomplete:
        gaps.append(f"incomplete_traces={incomplete}")
    unique_correlations = tuple(sorted(set(correlations)))
    return CorrelationTraceCohortEvidence(
        source_revision=next(iter(revisions)),
        minimum_traces=minimum_traces,
        trace_count=len(traces),
        trace_set_digest=(
            trace_set_digest(unique_correlations) if unique_correlations else _digest([])
        ),
        complete_trace=not gaps,
        gaps=tuple(gaps),
    )


def bind_qualification_timing_evidence(
    *,
    latency: ChatOpsLatencyEvidence,
    trace_cohort: CorrelationTraceCohortEvidence,
    frozen_blind_corpus: bool,
    production_e2e: bool,
    critical_safety_escape: bool,
) -> QualificationEvidence:
    """Derive timing booleans only from matching evidence artifacts."""

    if (
        latency.contract_version != CHATOPS_LATENCY_CONTRACT_V1.version
        or latency.contract_digest != CHATOPS_LATENCY_CONTRACT_V1.content_digest
    ):
        raise ValueError("latency evidence does not match the installed contract")
    if latency.source_revision != trace_cohort.source_revision:
        raise ValueError("latency and trace source revisions MUST match")
    if (
        latency.trace_count != trace_cohort.trace_count
        or latency.trace_set_digest != trace_cohort.trace_set_digest
    ):
        raise ValueError("latency and trace evidence MUST bind the same trace set")
    return QualificationEvidence(
        frozen_blind_corpus=frozen_blind_corpus,
        production_e2e=production_e2e,
        latency_slo=latency.latency_slo_met,
        complete_trace=trace_cohort.complete_trace,
        critical_safety_escape=critical_safety_escape,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


__all__ = [
    "CorrelationTraceCohortEvidence",
    "bind_qualification_timing_evidence",
    "reduce_trace_cohort",
]
