"""Change-correlation evidence for RCA grounding.

Design contract: ``docs/roadmap/rules-and-detection/observability-and-detection.md``
section 4 (RCA as a grounded tier output) and
``docs/roadmap/fork-and-sequencing/scope-expansion.md`` (DORA change ingestion).

FDAI writes remediation PRs but, before this gatherer, had no read-side
signal that a recent deploy / commit preceded an incident. The
:class:`~fdai.shared.providers.change_feed.ChangeFeed` seam supplies the
raw changes and :func:`~fdai.shared.providers.change_feed.correlate_changes`
ranks them; :class:`ChangeEvidenceGatherer` is the RCA consumer that turns a
correlated change into a :class:`~fdai.core.rca.contract.Citation` of kind
``CHANGE`` the coordinator can ground a hypothesis on.

Fail-safe by construction, matching the sibling
:class:`~fdai.core.rca.evidence.TelemetryEvidenceGatherer`: a missing
binding or a feed outage contributes **no** citations rather than raising,
so RCA abstains to HIL on the absence of change evidence instead of
reasoning on it. The gatherer never auto-acts on a correlation - it only
supplies grounded citations; the risk gate governs any action.

CSP/VCS-neutral: imports only the ChangeFeed Protocol, the RCA contract,
and the standard library, so it stays under the ``core/`` import rule.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from fdai.core.rca.contract import Citation, CitationKind
from fdai.shared.providers.change_feed import (
    ChangeCorrelation,
    ChangeFeed,
    ChangeFeedError,
    correlate_changes,
)

_LOGGER = logging.getLogger(__name__)

_DEFAULT_WINDOW = timedelta(hours=1)
_DEFAULT_MIN_SCORE = 0.0
_DEFAULT_MAX_CITATIONS = 5


def _as_utc(dt: datetime) -> datetime:
    """Return ``dt`` as UTC-aware; a naive value is assumed to be UTC.

    Guards the "never raises" contract: a naive ``incident_at`` would raise
    ``TypeError`` inside :func:`correlate_changes` when compared against the
    UTC-aware change timestamps.
    """
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _change_ref(correlation: ChangeCorrelation) -> str:
    """Opaque citation ref for a correlated change.

    ``change_id`` is a commit sha / release name / PR number - an
    identifier, never a secret or raw payload - so it is safe to surface
    in a citation, audit entry, or model prompt.
    """
    return f"change:{correlation.change.change_id}"


class ChangeEvidenceGatherer:
    """Gather CHANGE citations for RCA from the ChangeFeed seam."""

    __slots__ = ("_feed", "_max_citations", "_min_score", "_window")

    def __init__(
        self,
        *,
        feed: ChangeFeed | None = None,
        window: timedelta = _DEFAULT_WINDOW,
        min_score: float = _DEFAULT_MIN_SCORE,
        max_citations: int = _DEFAULT_MAX_CITATIONS,
    ) -> None:
        if window <= timedelta(0):
            raise ValueError("window MUST be positive")
        if not 0.0 <= min_score <= 1.0:
            raise ValueError("min_score MUST be in [0, 1]")
        if max_citations < 1:
            raise ValueError("max_citations MUST be >= 1")
        self._feed = feed
        self._window = window
        self._min_score = min_score
        self._max_citations = max_citations

    async def gather(
        self,
        *,
        incident_at: datetime,
        incident_resources: Sequence[str] = (),
        resource_hint: str | None = None,
    ) -> tuple[Citation, ...]:
        """Return CHANGE citations for changes that preceded the incident.

        Queries the feed for changes in ``[incident_at - window,
        incident_at]``, ranks them with :func:`correlate_changes`, and
        emits one citation per correlation whose score clears
        ``min_score`` (highest score first, capped at ``max_citations``).
        Never raises: no binding or a feed outage yields an empty tuple.
        """
        correlations = await self._ranked_correlations(
            incident_at=incident_at,
            incident_resources=incident_resources,
            resource_hint=resource_hint,
        )
        citations: list[Citation] = []
        seen: set[str] = set()
        for correlation in correlations:
            if correlation.score < self._min_score:
                continue
            ref = _change_ref(correlation)
            if ref in seen:
                continue
            seen.add(ref)
            citations.append(Citation(kind=CitationKind.CHANGE, ref=ref))
            if len(citations) >= self._max_citations:
                break
        return tuple(citations)

    async def gather_correlations(
        self,
        *,
        incident_at: datetime,
        incident_resources: Sequence[str] = (),
        resource_hint: str | None = None,
    ) -> tuple[ChangeCorrelation, ...]:
        """Same query as :meth:`gather` but returns the full ranked
        correlations (score + lead_seconds + overlap) so a caller can log
        the reasoning. Never raises."""
        return await self._ranked_correlations(
            incident_at=incident_at,
            incident_resources=incident_resources,
            resource_hint=resource_hint,
        )

    async def _ranked_correlations(
        self,
        *,
        incident_at: datetime,
        incident_resources: Sequence[str],
        resource_hint: str | None,
    ) -> tuple[ChangeCorrelation, ...]:
        """Query the feed and rank changes (shared by both public methods).

        Normalizes ``incident_at`` to UTC-aware so a naive caller value
        cannot raise inside :func:`correlate_changes`, and treats any
        :class:`ChangeFeedError` as "no change evidence" (fail-safe).
        """
        if self._feed is None:
            return ()
        incident_at = _as_utc(incident_at)
        since = incident_at - self._window
        try:
            changes = await self._feed.recent(
                since=since, until=incident_at, resource_hint=resource_hint
            )
        except ChangeFeedError:
            _LOGGER.warning(
                "rca_change_evidence_unavailable",
                extra={"resource_hint": resource_hint or ""},
            )
            return ()
        return tuple(
            correlate_changes(
                changes,
                incident_at=incident_at,
                incident_resources=incident_resources,
                window=self._window,
            )
        )


__all__ = ["ChangeEvidenceGatherer"]
