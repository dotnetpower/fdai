"""TelemetryEvidenceGatherer + RcaCoordinator.analyze_t2_from_telemetry.

Covers the consumer that wires the section 3.2 log / trace seams into RCA
grounding: error-only filtering, secret-safe opaque log refs, dedupe, fail-safe
provider outages, and the coordinator convenience path (gathered evidence ->
grounded T2, or abstain when unsupported). Uses the in-memory Static providers;
async tests run under asyncio_mode="auto".
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.rca import (
    Citation,
    CitationKind,
    RcaCoordinator,
    RcaTier,
    RootCauseHypothesis,
    TelemetryEvidenceGatherer,
)
from fdai.shared.providers.log_query import (
    LogQuery,
    LogQueryProviderError,
    LogRecord,
    StaticLogQueryProvider,
)
from fdai.shared.providers.trace_query import (
    Span,
    StaticTraceQueryProvider,
    TraceQuery,
    TraceQueryProviderError,
)

_NOW = datetime(2026, 7, 9, 12, 0, 0, tzinfo=UTC)
_SINCE = _NOW - timedelta(minutes=30)
_RES = "res-1"


def _log(body: str, severity: str) -> LogRecord:
    return LogRecord(
        at=_NOW - timedelta(minutes=1),
        body=body,
        severity=severity,
        labels={"resource_id": _RES},
    )


def _span(span_id: str, status: str) -> Span:
    return Span(
        trace_id="trace-abc",
        span_id=span_id,
        parent_span_id=None,
        service="checkout",
        operation="POST /pay",
        start=_NOW - timedelta(minutes=1),
        duration=timedelta(milliseconds=200),
        status=status,
        labels={"resource_id": _RES},
    )


async def _gather(gatherer: TelemetryEvidenceGatherer) -> tuple[Citation, ...]:
    return await gatherer.gather(resource_ref=_RES, since=_SINCE, until=_NOW)


# ---------------------------------------------------------------------------
# Gatherer
# ---------------------------------------------------------------------------


async def test_no_providers_yields_no_evidence() -> None:
    assert await _gather(TelemetryEvidenceGatherer()) == ()


async def test_only_error_logs_become_citations_and_ref_hides_body() -> None:
    provider = StaticLogQueryProvider(
        [
            _log("secret-token=abc123 timed out after connection refused", "error"),
            _log("started ok", "info"),
        ]
    )
    citations = await _gather(TelemetryEvidenceGatherer(log_provider=provider))
    assert len(citations) == 1
    assert citations[0].kind is CitationKind.TELEMETRY
    assert citations[0].ref.startswith("log:")
    # The raw body (which may carry secrets) never leaks into the ref.
    assert "secret-token" not in citations[0].ref
    assert citations[0].facts == (
        "marker:connection",
        "marker:timeout",
        "severity:error",
        "signal:log_error",
    )
    assert all("secret" not in fact for fact in citations[0].facts)


async def test_only_error_spans_become_citations() -> None:
    provider = StaticTraceQueryProvider([_span("s1", "error"), _span("s2", "ok")])
    citations = await _gather(TelemetryEvidenceGatherer(trace_provider=provider))
    assert [c.ref for c in citations] == ["trace:trace-abc:s1"]
    assert citations[0].facts == (
        "duration:100ms_to_1s",
        "protocol:http_post",
        "signal:trace_error",
        "status:error",
    )


@pytest.mark.parametrize(
    "facts",
    (
        ("raw log body",),
        ("secret:token=value",),
        tuple(f"marker:value-{index}" for index in range(17)),
        ("marker:timeout", "marker:timeout"),
    ),
)
def test_citation_facts_reject_raw_unbounded_or_duplicate_context(
    facts: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError):
        Citation(kind=CitationKind.TELEMETRY, ref="log:opaque", facts=facts)


async def test_logs_then_traces_with_dedupe() -> None:
    logs = StaticLogQueryProvider([_log("boom", "error"), _log("boom", "error")])
    traces = StaticTraceQueryProvider([_span("s1", "error")])
    citations = await _gather(TelemetryEvidenceGatherer(log_provider=logs, trace_provider=traces))
    # Two identical error logs dedupe to one; the span adds a second.
    assert len(citations) == 2
    assert citations[0].ref.startswith("log:")
    assert citations[1].ref == "trace:trace-abc:s1"


class _RaisingLogProvider:
    async def query(self, query: LogQuery):
        raise LogQueryProviderError("log backend down")
        yield  # pragma: no cover - unreachable, makes this an async generator


class _RaisingTraceProvider:
    async def query(self, query: TraceQuery):
        raise TraceQueryProviderError("trace backend down")
        yield  # pragma: no cover


class _BlockedLogProvider:
    async def query(self, query: LogQuery):
        await asyncio.Event().wait()
        yield  # pragma: no cover


class _BlockedTraceProvider:
    async def query(self, query: TraceQuery):
        await asyncio.Event().wait()
        yield  # pragma: no cover


async def test_log_outage_is_fail_safe_trace_still_contributes() -> None:
    gatherer = TelemetryEvidenceGatherer(
        log_provider=_RaisingLogProvider(),
        trace_provider=StaticTraceQueryProvider([_span("s1", "error")]),
    )
    citations = await _gather(gatherer)
    assert [c.ref for c in citations] == ["trace:trace-abc:s1"]


async def test_trace_outage_is_fail_safe() -> None:
    gatherer = TelemetryEvidenceGatherer(
        log_provider=StaticLogQueryProvider([_log("boom", "error")]),
        trace_provider=_RaisingTraceProvider(),
    )
    citations = await _gather(gatherer)
    assert len(citations) == 1
    assert citations[0].ref.startswith("log:")


async def test_slow_log_source_does_not_block_trace_evidence() -> None:
    gatherer = TelemetryEvidenceGatherer(
        log_provider=_BlockedLogProvider(),
        trace_provider=StaticTraceQueryProvider([_span("s1", "error")]),
        source_timeout_seconds=0.01,
    )

    citations = await asyncio.wait_for(_gather(gatherer), timeout=0.1)

    assert [citation.ref for citation in citations] == ["trace:trace-abc:s1"]


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("inf"), float("nan")])
def test_source_timeout_must_be_finite_and_positive(timeout: float) -> None:
    with pytest.raises(ValueError, match="source_timeout_seconds"):
        TelemetryEvidenceGatherer(source_timeout_seconds=timeout)


async def test_slow_trace_source_does_not_block_log_evidence() -> None:
    gatherer = TelemetryEvidenceGatherer(
        log_provider=StaticLogQueryProvider([_log("boom", "error")]),
        trace_provider=_BlockedTraceProvider(),
        source_timeout_seconds=0.01,
    )

    citations = await asyncio.wait_for(_gather(gatherer), timeout=0.1)

    assert len(citations) == 1
    assert citations[0].ref.startswith("log:")


# ---------------------------------------------------------------------------
# Coordinator integration
# ---------------------------------------------------------------------------


class _EchoReasoner:
    """Cites the first candidate (grounded) or a fabricated ref."""

    def __init__(self, *, fabricate: bool = False) -> None:
        self._fabricate = fabricate

    async def reason(
        self, *, incident_summary: str, candidate_citations: Sequence[Citation]
    ) -> RootCauseHypothesis | None:
        if self._fabricate:
            cite = Citation(kind=CitationKind.TELEMETRY, ref="trace:fabricated:x")
        elif not candidate_citations:
            return None
        else:
            cite = candidate_citations[0]
        return RootCauseHypothesis(
            tier=RcaTier.T2, cause="db pool exhausted", confidence=0.9, citations=(cite,)
        )


async def test_analyze_t2_from_telemetry_grounds_on_gathered_evidence() -> None:
    gatherer = TelemetryEvidenceGatherer(
        trace_provider=StaticTraceQueryProvider([_span("s1", "error")])
    )
    coordinator = RcaCoordinator(reasoner=_EchoReasoner(), evidence_gatherer=gatherer)
    result = await coordinator.analyze_t2_from_telemetry(
        incident_summary="checkout latency spike",
        resource_ref=_RES,
        since=_SINCE,
        until=_NOW,
    )
    assert result.is_grounded is True
    assert result.hypothesis is not None
    assert result.hypothesis.citations[0].ref == "trace:trace-abc:s1"


async def test_analyze_t2_from_telemetry_abstains_without_evidence() -> None:
    coordinator = RcaCoordinator(
        reasoner=_EchoReasoner(), evidence_gatherer=TelemetryEvidenceGatherer()
    )
    result = await coordinator.analyze_t2_from_telemetry(
        incident_summary="novel incident",
        resource_ref=_RES,
        since=_SINCE,
        until=_NOW,
    )
    assert result.is_grounded is False


async def test_analyze_t2_from_telemetry_refuses_fabricated_citation() -> None:
    gatherer = TelemetryEvidenceGatherer(
        trace_provider=StaticTraceQueryProvider([_span("s1", "error")])
    )
    coordinator = RcaCoordinator(reasoner=_EchoReasoner(fabricate=True), evidence_gatherer=gatherer)
    result = await coordinator.analyze_t2_from_telemetry(
        incident_summary="checkout latency spike",
        resource_ref=_RES,
        since=_SINCE,
        until=_NOW,
    )
    # A citation the gatherer never produced is treated as fabricated.
    assert result.is_grounded is False
    assert "ungrounded_citation" in result.reason
