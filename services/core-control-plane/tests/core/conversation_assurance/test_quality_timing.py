from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.core.conversation_assurance.quality_latency import (
    CHATOPS_LATENCY_CONTRACT_V1,
    ChatOpsLatencyEvidence,
)
from fdai.core.conversation_assurance.quality_scorecard import QualityHardCap
from fdai.core.conversation_assurance.quality_timing import (
    bind_qualification_timing_evidence,
    reduce_trace_cohort,
)
from fdai.core.conversation_assurance.quality_trace import (
    CorrelationTraceEvidence,
    CorrelationTraceStage,
    TraceTimestampAuthority,
    trace_set_digest,
)

_SOURCE_REVISION = "a" * 40


def _trace(index: int, *, complete: bool = True) -> CorrelationTraceEvidence:
    correlation = f"{index:064x}"
    return CorrelationTraceEvidence(
        trace_digest=f"{index + 1_000:064x}",
        source_revision=_SOURCE_REVISION,
        started_at="2026-08-28T00:00:00Z",
        completed_at="2026-08-28T00:01:00Z",
        correlation_digest=correlation,
        event_manifest_digest=f"{index + 2_000:064x}",
        stage_counts=tuple((stage, 1) for stage in CorrelationTraceStage),
        timestamp_authorities=(TraceTimestampAuthority.DATABASE_COMMIT,),
        complete_trace=complete,
        gaps=() if complete else ("missing_stages=audit",),
    )


def _latency(trace_digests: tuple[str, ...]) -> ChatOpsLatencyEvidence:
    return ChatOpsLatencyEvidence(
        run_digest="b" * 64,
        source_revision=_SOURCE_REVISION,
        contract_version=CHATOPS_LATENCY_CONTRACT_V1.version,
        contract_digest=CHATOPS_LATENCY_CONTRACT_V1.content_digest,
        sample_manifest_digest="c" * 64,
        trace_count=len(trace_digests),
        trace_set_digest=trace_set_digest(trace_digests),
        started_at="2026-08-28T00:00:00Z",
        completed_at="2026-08-28T01:00:00Z",
        stages=(),
        latency_slo_met=True,
    )


def test_matching_complete_cohort_derives_clear_timing_evidence() -> None:
    traces = tuple(_trace(index) for index in range(500))
    cohort = reduce_trace_cohort(traces)
    latency = _latency(
        tuple(trace.correlation_digest for trace in traces if trace.correlation_digest)
    )

    evidence = bind_qualification_timing_evidence(
        latency=latency,
        trace_cohort=cohort,
        frozen_blind_corpus=True,
        production_e2e=True,
        critical_safety_escape=False,
    )

    assert cohort.complete_trace is True
    assert evidence.hard_caps(corpus_meets_floor=True) == ()
    assert len(cohort.to_dict()["content_digest"]) == 64


def test_incomplete_or_small_trace_cohort_keeps_hard_cap() -> None:
    traces = tuple(_trace(index, complete=index == 0) for index in range(10))
    cohort = reduce_trace_cohort(traces)
    latency = _latency(
        tuple(trace.correlation_digest for trace in traces if trace.correlation_digest)
    )

    evidence = bind_qualification_timing_evidence(
        latency=latency,
        trace_cohort=cohort,
        frozen_blind_corpus=True,
        production_e2e=True,
        critical_safety_escape=False,
    )

    assert cohort.complete_trace is False
    assert "trace_count=10<minimum_traces=500" in cohort.gaps
    assert "incomplete_traces=9" in cohort.gaps
    assert evidence.hard_caps(corpus_meets_floor=True) == (
        QualityHardCap.NO_LATENCY_SLO_OR_COMPLETE_TRACE,
    )


def test_binding_rejects_source_contract_and_trace_set_mismatch() -> None:
    traces = tuple(_trace(index) for index in range(500))
    cohort = reduce_trace_cohort(traces)
    trace_digests = tuple(trace.correlation_digest for trace in traces if trace.correlation_digest)
    latency = _latency(trace_digests)

    with pytest.raises(ValueError, match="source revisions"):
        bind_qualification_timing_evidence(
            latency=latency,
            trace_cohort=replace(cohort, source_revision="d" * 40),
            frozen_blind_corpus=True,
            production_e2e=True,
            critical_safety_escape=False,
        )
    with pytest.raises(ValueError, match="same trace set"):
        bind_qualification_timing_evidence(
            latency=replace(latency, trace_set_digest="e" * 64),
            trace_cohort=cohort,
            frozen_blind_corpus=True,
            production_e2e=True,
            critical_safety_escape=False,
        )
    with pytest.raises(ValueError, match="installed contract"):
        bind_qualification_timing_evidence(
            latency=replace(latency, contract_digest="f" * 64),
            trace_cohort=cohort,
            frozen_blind_corpus=True,
            production_e2e=True,
            critical_safety_escape=False,
        )


def test_trace_cohort_rejects_duplicate_correlations() -> None:
    first = _trace(1)
    duplicate = replace(_trace(2), correlation_digest=first.correlation_digest)

    cohort = reduce_trace_cohort((first, duplicate), minimum_traces=2)

    assert cohort.complete_trace is False
    assert "duplicate_correlation_digest" in cohort.gaps
