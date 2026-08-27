from __future__ import annotations

from dataclasses import replace

from fdai.core.conversation_assurance.quality_qualification import (
    QualificationEvidence,
)
from fdai.core.conversation_assurance.quality_scorecard import QualityHardCap
from fdai.core.conversation_assurance.quality_trace import (
    CorrelationTraceBatch,
    CorrelationTraceEvent,
    CorrelationTraceStage,
    TraceTimestampAuthority,
    reduce_correlation_trace,
)

_CORRELATION = "a" * 64


def _batch() -> CorrelationTraceBatch:
    events = []
    predecessor = None
    for index, stage in enumerate(CorrelationTraceStage):
        record_digest = f"{index + 1:064x}"
        events.append(
            CorrelationTraceEvent(
                stage=stage,
                occurred_at=f"2026-08-28T00:00:{index:02d}Z",
                timestamp_authority=(
                    TraceTimestampAuthority.PROVIDER_RECEIPT
                    if stage is CorrelationTraceStage.DELIVERY
                    else TraceTimestampAuthority.DATABASE_COMMIT
                ),
                correlation_digest=_CORRELATION,
                record_digest=record_digest,
                predecessor_record_digest=predecessor,
                provenance_digest=f"{index + 100:064x}",
            )
        )
        predecessor = record_digest
    return CorrelationTraceBatch(
        trace_id="trace-001",
        source_revision="b" * 40,
        started_at="2026-08-28T00:00:00Z",
        completed_at="2026-08-28T00:01:00Z",
        events=tuple(events),
    )


def test_exact_eight_stage_chain_is_complete_and_content_free() -> None:
    evidence = reduce_correlation_trace(_batch())
    payload = evidence.to_dict()

    assert evidence.complete_trace is True
    assert evidence.gaps == ()
    assert dict(evidence.stage_counts) == {stage: 1 for stage in CorrelationTraceStage}
    assert evidence.correlation_digest == _CORRELATION
    assert payload["qualification_authority"] is False
    assert "trace-001" not in str(payload)
    assert "record_digest" not in str(payload)
    assert "provenance_digest" not in str(payload)


def test_missing_duplicate_and_cross_correlation_stages_fail_closed() -> None:
    batch = _batch()
    events = list(batch.events)
    events.pop(3)
    events.append(
        replace(
            events[-1],
            correlation_digest="c" * 64,
        )
    )

    evidence = reduce_correlation_trace(replace(batch, events=tuple(events)))

    assert evidence.complete_trace is False
    assert "missing_stages=tool_agent_evidence" in evidence.gaps
    assert "duplicate_stages=audit" in evidence.gaps
    assert "correlation_digest_mismatch" in evidence.gaps
    assert "stage_order_mismatch" in evidence.gaps


def test_broken_predecessor_and_timestamp_order_fail_closed() -> None:
    batch = _batch()
    events = list(batch.events)
    events[4] = replace(
        events[4],
        predecessor_record_digest="d" * 64,
        occurred_at="2026-08-27T23:59:59Z",
    )

    evidence = reduce_correlation_trace(replace(batch, events=tuple(events)))

    assert evidence.complete_trace is False
    assert "predecessor_mismatch:proposal" in evidence.gaps
    assert "timestamp_order_mismatch" in evidence.gaps
    assert "timestamp_outside_trace_window" in evidence.gaps


def test_complete_trace_and_latency_slo_clear_the_shared_hard_cap() -> None:
    trace = reduce_correlation_trace(_batch())
    evidence = QualificationEvidence(
        frozen_blind_corpus=True,
        production_e2e=True,
        latency_slo=True,
        complete_trace=trace.complete_trace,
        critical_safety_escape=False,
    )

    assert evidence.hard_caps(corpus_meets_floor=True) == ()
    assert replace(evidence, complete_trace=False).hard_caps(corpus_meets_floor=True) == (
        QualityHardCap.NO_LATENCY_SLO_OR_COMPLETE_TRACE,
    )
