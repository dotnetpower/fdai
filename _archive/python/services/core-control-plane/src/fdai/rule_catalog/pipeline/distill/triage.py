"""Deterministic triage for manual distillation (discovery at scale).

Design contract:
``docs/roadmap/rules-and-detection/manual-distillation.md`` § "Discovery and
triage at scale". At Confluence / Notion scale most pages are not manuals, and
distilling all of them explodes cost and false positives. This module is the
free, deterministic front of the triage funnel: cheap metadata filters, exact
duplicate removal, an authority score, and a priority ordering. The expensive
"is this really a procedure?" call is an LLM judgement and lives behind the
:class:`~fdai.shared.providers.manual_classifier.ManualClassifier` seam (fork).

Pure and deterministic: no LLM, no network. Wall-clock is injected (``now``) so
staleness evaluation is reproducible in tests. Every signal is best-effort - a
candidate missing a signal is never dropped *for* that missing signal (a source
that cannot report ``last_edited`` is not penalised as stale).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.shared.providers.manual_source import ManualCandidate

# Authority-score weights. Deterministic composite of the cheap authority
# signals a source can report. Inbound links dominate (canonical hub documents
# are linked the most); verification and views break ties.
_W_INBOUND = 3.0
_W_VERIFIED = 5.0
_W_VIEWS = 0.01


@dataclass(frozen=True, slots=True)
class TriagePolicy:
    """Deterministic keep/drop thresholds for the metadata filter.

    An empty constraint is inactive: empty ``required_labels`` imposes no label
    requirement, ``max_stale_days=None`` never drops on age, and so on. This
    keeps the default policy a permissive pass-through that a fork tightens.
    """

    required_labels: frozenset[str] = frozenset()
    excluded_labels: frozenset[str] = frozenset()
    required_spaces: frozenset[str] = frozenset()
    require_verified: bool = False
    min_view_count: int = 0
    max_stale_days: int | None = None


@dataclass(frozen=True, slots=True)
class TriageDrop:
    """One candidate the filter rejected, with a human-readable reason."""

    candidate: ManualCandidate
    reason: str


@dataclass(frozen=True, slots=True)
class TriageResult:
    """Outcome of the deterministic filter: what survives and what was dropped."""

    kept: tuple[ManualCandidate, ...] = ()
    dropped: tuple[TriageDrop, ...] = ()


def authority_score(candidate: ManualCandidate) -> float:
    """Deterministic authority score from a candidate's cheap signals.

    Higher means "more likely a canonical, load-bearing document". Used to order
    the priority queue and to pick the survivor when exact duplicates collide.
    """
    return (
        candidate.inbound_links * _W_INBOUND
        + (_W_VERIFIED if candidate.verified else 0.0)
        + candidate.view_count * _W_VIEWS
    )


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _drop_reason(candidate: ManualCandidate, policy: TriagePolicy, now: datetime) -> str | None:
    labels = set(candidate.labels)
    if policy.required_labels and labels.isdisjoint(policy.required_labels):
        return "missing required label"
    if policy.excluded_labels and not labels.isdisjoint(policy.excluded_labels):
        return "carries excluded label"
    if policy.required_spaces and candidate.space not in policy.required_spaces:
        return "outside required space"
    if policy.require_verified and not candidate.verified:
        return "not verified"
    if candidate.view_count < policy.min_view_count:
        return "below min view count"
    if policy.max_stale_days is not None:
        edited = _parse_iso(candidate.last_edited)
        # Missing timestamp is a best-effort miss, not grounds to drop.
        # Use full-precision seconds, not .days (which truncates, so a doc edited
        # 30.5 days ago would wrongly survive a 30-day cap).
        if edited is not None and (now - edited).total_seconds() > policy.max_stale_days * 86400:
            return "stale"
    return None


def triage_filter(
    candidates: Sequence[ManualCandidate],
    policy: TriagePolicy,
    *,
    now: datetime | None = None,
) -> TriageResult:
    """Apply the deterministic metadata filter, returning kept + dropped sets."""
    moment = now or datetime.now(tz=UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    kept: list[ManualCandidate] = []
    dropped: list[TriageDrop] = []
    for candidate in candidates:
        reason = _drop_reason(candidate, policy, moment)
        if reason is None:
            kept.append(candidate)
        else:
            dropped.append(TriageDrop(candidate=candidate, reason=reason))
    return TriageResult(kept=tuple(kept), dropped=tuple(dropped))


def dedupe_exact(
    candidates: Sequence[ManualCandidate],
) -> tuple[tuple[ManualCandidate, ...], tuple[TriageDrop, ...]]:
    """Collapse byte-identical duplicates (same ``content_sha``).

    Keeps the highest-authority survivor per hash; drops the rest as exact
    duplicates. Candidates with an empty ``content_sha`` are never deduplicated
    (no hash to compare). Semantic near-duplicate clustering needs embeddings
    and is a fork concern; this handles only the deterministic exact case.
    """
    by_hash: dict[str, list[ManualCandidate]] = {}
    unique: list[ManualCandidate] = []
    dropped: list[TriageDrop] = []
    for candidate in candidates:
        if not candidate.content_sha:
            unique.append(candidate)
            continue
        by_hash.setdefault(candidate.content_sha, []).append(candidate)

    for group in by_hash.values():
        if len(group) == 1:
            unique.append(group[0])
            continue
        ranked = sorted(group, key=lambda c: (authority_score(c), c.doc_id), reverse=True)
        unique.append(ranked[0])
        dropped.extend(TriageDrop(candidate=c, reason="exact duplicate") for c in ranked[1:])

    unique.sort(key=lambda c: c.doc_id)
    return tuple(unique), tuple(dropped)


def prioritize(
    candidates: Sequence[ManualCandidate],
    *,
    incident_refs: frozenset[str] = frozenset(),
) -> tuple[ManualCandidate, ...]:
    """Order candidates for distillation: most load-bearing first.

    Priority signals, in order: a candidate a recent incident referenced (the
    living-rules feedback loop), then authority score, then view count, then
    recency. Ties break on ``doc_id`` for a stable, reproducible order.
    """

    def key(candidate: ManualCandidate) -> tuple[int, float, int, str, str]:
        incident = 1 if candidate.source_ref in incident_refs else 0
        edited = _parse_iso(candidate.last_edited)
        edited_key = edited.isoformat() if edited is not None else ""
        return (
            incident,
            authority_score(candidate),
            candidate.view_count,
            edited_key,
            candidate.doc_id,
        )

    return tuple(sorted(candidates, key=key, reverse=True))


__all__ = [
    "TriageDrop",
    "TriagePolicy",
    "TriageResult",
    "authority_score",
    "dedupe_exact",
    "prioritize",
    "triage_filter",
]
