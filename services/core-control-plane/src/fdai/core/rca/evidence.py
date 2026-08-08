"""Telemetry evidence gathering for RCA grounding.

Design contract: ``docs/roadmap/fork-and-sequencing/scope-expansion.md`` section 3.2 (the log +
trace ingestion seams) and
[observability-and-detection.md](../../../../docs/roadmap/rules-and-detection/observability-and-detection.md)
section 4 (RCA as a grounded tier output).

The § 3.2 :class:`~fdai.shared.providers.log_query.LogQueryProvider` and
:class:`~fdai.shared.providers.trace_query.TraceQueryProvider` seams exist "so
RCA can ground on real event text" and "walk a request across services", but
nothing consumed them - :class:`~fdai.core.rca.coordinator.RcaCoordinator`
takes the ``candidate_citations`` from its caller and never gathers any.
:class:`TelemetryEvidenceGatherer` is that missing consumer: it queries the two
seams for **failure** signals (error-level logs, error-status spans) around an
incident and returns :class:`~fdai.core.rca.contract.Citation` s of kind
``TELEMETRY`` the coordinator can ground a hypothesis on.

Fail-safe by construction, matching the seam docstrings' "fail-closed" contract:
a missing binding or a provider outage contributes **no** citations rather than
raising. Empty evidence then makes the grounding gate abstain to HIL - the
control plane never reasons on the absence of telemetry.

Secret-safe: a citation ``ref`` is an opaque, deterministic token. A log ref is
a ``uuid5`` over the record's timestamp / severity / body, so raw log text
(which may carry secrets) never appears in a citation, audit entry, or model
prompt (per ``security-and-identity.md``). A span ref uses only the trace and
span ids.

CSP-neutral: imports only the provider Protocols, the RCA contract, and the
standard library, so it stays under the ``core/`` import rule.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from fdai.core.rca.contract import Citation, CitationKind
from fdai.shared.providers.log_query import (
    LogQuery,
    LogQueryProvider,
    LogQueryProviderError,
    LogRecord,
)
from fdai.shared.providers.trace_query import (
    Span,
    TraceQuery,
    TraceQueryProvider,
    TraceQueryProviderError,
)

_LOGGER = logging.getLogger(__name__)

_DEFAULT_ERROR_SEVERITIES = frozenset({"error", "critical", "fatal", "err"})
_RESOURCE_LABEL = "resource_id"


def _log_ref(record: LogRecord) -> str:
    """Opaque, deterministic citation ref for a log record (no raw body)."""
    token = uuid5(NAMESPACE_URL, f"{record.at.isoformat()}|{record.severity}|{record.body}")
    return f"log:{token.hex}"


def _span_ref(span: Span) -> str:
    """Citation ref for an error span - trace + span ids only."""
    return f"trace:{span.trace_id}:{span.span_id}"


class TelemetryEvidenceGatherer:
    """Gather TELEMETRY citations for RCA from the log + trace seams."""

    __slots__ = ("_error_severities", "_log_provider", "_trace_provider")

    def __init__(
        self,
        *,
        log_provider: LogQueryProvider | None = None,
        trace_provider: TraceQueryProvider | None = None,
        error_severities: Iterable[str] = _DEFAULT_ERROR_SEVERITIES,
    ) -> None:
        self._log_provider = log_provider
        self._trace_provider = trace_provider
        self._error_severities = frozenset(s.lower() for s in error_severities)

    async def gather(
        self,
        *,
        resource_ref: str,
        since: datetime,
        until: datetime,
        log_expression: str = "",
        trace_service: str | None = None,
        limit: int = 20,
    ) -> tuple[Citation, ...]:
        """Return TELEMETRY citations for failures in ``[since, until]``.

        Queries the log seam for error-level records and the trace seam for
        error-status spans scoped to ``resource_ref``. Deduplicates by ref and
        preserves discovery order (logs first, then traces). Never raises: a
        provider outage on either seam is logged and that source contributes
        nothing, so a partial telemetry backend still yields the evidence it
        can.
        """
        citations: list[Citation] = []
        seen: set[str] = set()

        for ref in await self._gather_log_refs(resource_ref, since, until, log_expression, limit):
            if ref not in seen:
                seen.add(ref)
                citations.append(Citation(kind=CitationKind.TELEMETRY, ref=ref))

        for ref in await self._gather_span_refs(resource_ref, since, until, trace_service, limit):
            if ref not in seen:
                seen.add(ref)
                citations.append(Citation(kind=CitationKind.TELEMETRY, ref=ref))

        return tuple(citations)

    async def _gather_log_refs(
        self,
        resource_ref: str,
        since: datetime,
        until: datetime,
        expression: str,
        limit: int,
    ) -> list[str]:
        if self._log_provider is None:
            return []
        query = LogQuery(
            expression=expression,
            labels={_RESOURCE_LABEL: resource_ref},
            since=since,
            until=until,
            limit=limit,
        )
        refs: list[str] = []
        try:
            async for record in self._log_provider.query(query):
                if record.severity.lower() in self._error_severities:
                    refs.append(_log_ref(record))
        except LogQueryProviderError:
            _LOGGER.warning("rca_log_evidence_unavailable", extra={"resource_ref": resource_ref})
            return []
        return refs

    async def _gather_span_refs(
        self,
        resource_ref: str,
        since: datetime,
        until: datetime,
        service: str | None,
        limit: int,
    ) -> list[str]:
        if self._trace_provider is None:
            return []
        query = TraceQuery(
            service=service,
            labels={_RESOURCE_LABEL: resource_ref},
            since=since,
            until=until,
            limit=limit,
        )
        refs: list[str] = []
        try:
            async for span in self._trace_provider.query(query):
                if span.status.lower() == "error":
                    refs.append(_span_ref(span))
        except TraceQueryProviderError:
            _LOGGER.warning("rca_trace_evidence_unavailable", extra={"resource_ref": resource_ref})
            return []
        return refs


__all__ = ["TelemetryEvidenceGatherer"]
