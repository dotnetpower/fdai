"""Change feed - VCS/deploy change ingestion for RCA correlation.

Design contract: ``docs/roadmap/rules-and-detection/observability-and-detection.md`` (root-cause
correlation) and ``docs/roadmap/fork-and-sequencing/scope-expansion.md`` (DORA change ingestion,
deferred git-history reader). FDAI writes remediation PRs but has no
read-side signal that correlates a recent deploy / commit with an incident.
This seam supplies that signal: a CSP/VCS-neutral feed of change records
(deployments, merges, config edits) that RCA can correlate to an incident
by temporal proximity and resource overlap.

The upstream default binding is :class:`EmptyChangeFeed` (returns no
changes), so correlation degrades to "no change evidence" rather than a
fabricated cause. A fork binds a live adapter (GitHub / Azure DevOps under
``delivery/``) at the composition root.

``correlate_changes`` is a pure, I/O-free ranking function - the RCA
primitive - so it is deterministically testable and never depends on a
live feed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

_DEFAULT_WINDOW = timedelta(hours=1)


class ChangeFeedError(RuntimeError):
    """Raised on an unrecoverable change-feed failure.

    Defined on the Protocol so ``core/`` can catch it without importing a
    concrete adapter: the RCA change-evidence gatherer treats a feed
    outage as "no change evidence" (fail-safe, abstain to HIL) rather than
    letting the exception abort analysis. Live adapters (GitHub, Azure
    DevOps) raise a subclass. Safe to log - carries only the source, HTTP
    status, and a short reason, never a token or raw response body.
    """


@dataclass(frozen=True, slots=True)
class ChangeRecord:
    """One normalized change (deploy / merge / config edit).

    CSP- and VCS-neutral: a GitHub deployment, an Azure DevOps release, and
    a Terraform apply all map onto this shape. ``resource_hints`` are
    CSP-neutral resource ids or names the change is believed to touch,
    used to score resource overlap with an incident.
    """

    change_id: str
    at: datetime
    source: str
    """Origin system: ``github`` / ``azure-devops`` / ``terraform`` / ..."""

    ref: str
    """Human-facing reference: a commit sha, a release name, a PR number."""

    summary: str
    author: str = ""
    resource_hints: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChangeCorrelation:
    """A change ranked against one incident, with an explainable score."""

    change: ChangeRecord
    score: float
    """0..1 - higher is a stronger candidate cause."""

    lead_seconds: float
    """Seconds the change preceded the incident (negative = after it)."""

    resource_overlap: tuple[str, ...] = ()


@runtime_checkable
class ChangeFeed(Protocol):
    """Return normalized change records in a time window."""

    async def recent(
        self,
        *,
        since: datetime,
        until: datetime,
        resource_hint: str | None = None,
    ) -> Sequence[ChangeRecord]:
        """Return changes in ``[since, until]``.

        ``resource_hint`` is an optional adapter-side pre-filter; adapters
        that cannot filter server-side return the full window and rely on
        :func:`correlate_changes` to score overlap. An empty result is a
        valid answer, NOT an error.
        """
        ...


class EmptyChangeFeed:
    """Upstream default - reports no changes."""

    async def recent(
        self,
        *,
        since: datetime,
        until: datetime,
        resource_hint: str | None = None,
    ) -> Sequence[ChangeRecord]:  # noqa: ARG002
        return ()


def correlate_changes(
    changes: Sequence[ChangeRecord],
    *,
    incident_at: datetime,
    incident_resources: Sequence[str] = (),
    window: timedelta = _DEFAULT_WINDOW,
) -> list[ChangeCorrelation]:
    """Rank ``changes`` as candidate causes of an incident (pure function).

    A change scores on two deterministic signals:

    - **Temporal proximity**: a change that preceded the incident inside
      ``window`` scores higher the closer it is; a change *after* the
      incident, or outside the window, is dropped (it cannot be a cause).
    - **Resource overlap**: sharing a resource hint with the incident
      boosts the score. With no incident resources supplied, ranking is
      purely temporal.

    Returns correlations sorted by descending score. Deterministic and
    I/O-free - the RCA layer calls this over a feed's output; it never
    auto-acts on the result (the risk gate governs any action).
    """
    if window <= timedelta(0):
        raise ValueError("window MUST be positive")

    incident_set = {r for r in incident_resources if r}
    window_seconds = window.total_seconds()
    out: list[ChangeCorrelation] = []

    for change in changes:
        lead = (incident_at - change.at).total_seconds()
        # Must precede the incident and fall inside the window.
        if lead < 0 or lead > window_seconds:
            continue
        # Closer in time -> higher temporal score (1.0 at t=0, 0.0 at edge).
        temporal = 1.0 - (lead / window_seconds)
        overlap = tuple(sorted(incident_set.intersection(change.resource_hints)))
        overlap_score = 1.0 if overlap else 0.0
        # Temporal dominates; overlap is a bounded boost.
        score = 0.7 * temporal + 0.3 * overlap_score
        out.append(
            ChangeCorrelation(
                change=change,
                score=round(score, 6),
                lead_seconds=lead,
                resource_overlap=overlap,
            )
        )

    out.sort(key=lambda c: (c.score, -c.lead_seconds), reverse=True)
    return out


__all__ = [
    "ChangeCorrelation",
    "ChangeFeed",
    "ChangeFeedError",
    "ChangeRecord",
    "EmptyChangeFeed",
    "correlate_changes",
]
