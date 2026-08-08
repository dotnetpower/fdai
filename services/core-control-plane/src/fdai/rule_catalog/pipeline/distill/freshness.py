"""Deterministic freshness diff for manual distillation (delta + deletion).

Design contract:
``docs/roadmap/rules-and-detection/manual-distillation.md`` § "Freshness and
deletion propagation". A refresh must not be a full re-crawl: only changed
manuals re-enter the pipeline, and - the gap a naive sync misses - a manual that
was **deleted or archived** must have the rules distilled from it retired
(tombstoned), never left firing on withdrawn guidance.

A source's own ``changes(since)`` cursor cannot report deletions for every
backend (a drop directory has no memory of removed files). This module therefore
derives the delta the reliable way: compare a prior snapshot manifest
(``source_ref -> curation fingerprint``) against the current listing. New,
content-changed, or re-curated candidates are upserts; source_refs present before
but absent now are deletions that drive retirement.

Pure and deterministic: no LLM, no network, no wall-clock.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fdai.shared.providers.manual_source import ManualCandidate


@dataclass(frozen=True, slots=True)
class FreshnessDelta:
    """What changed between a prior snapshot and the current listing.

    ``upserted`` are candidates to (re-)distill; ``deleted`` are source_refs
    whose derived rules must be tombstoned; ``unchanged`` are source_refs whose
    curation fingerprint is identical to the snapshot (skipped, saving LLM cost).
    """

    upserted: tuple[ManualCandidate, ...] = ()
    deleted: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RetirementRequest:
    """A request to retire the rules distilled from a removed manual.

    Consumed by the promotion / living-rules retirement path (M5 orchestration);
    this module only plans them deterministically from a :class:`FreshnessDelta`.
    """

    source_ref: str
    reason: str


def _curation_fingerprint(candidate: ManualCandidate) -> str:
    """Fingerprint the content plus the curation signals that gate re-triage.

    Combines ``content_sha`` with the discrete curation signals a source can move
    *without editing the page* - labels, space, and the verified flag - so a
    relabel / re-space / verify re-enters the manual into triage even when its
    text is byte-identical. High-churn signals (view count, edit timestamp) are
    intentionally excluded so ordinary traffic does not force a needless
    re-distill.
    """
    parts = "\0".join(
        [
            candidate.content_sha,
            ",".join(sorted(candidate.labels)),
            candidate.space,
            "1" if candidate.verified else "0",
        ]
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def snapshot_of(candidates: Sequence[ManualCandidate]) -> dict[str, str]:
    """Record the current listing as a ``source_ref -> curation fingerprint`` manifest.

    Persisted between runs so the next :func:`diff_snapshot` can detect content
    or curation changes and deletions. On a duplicate source_ref the last entry
    wins (a well-formed source does not emit duplicates; the orchestrator rejects
    duplicates at its boundary anyway).
    """
    return {c.source_ref: _curation_fingerprint(c) for c in candidates}


def diff_snapshot(
    previous: Mapping[str, str],
    current: Sequence[ManualCandidate],
) -> FreshnessDelta:
    """Diff the current listing against a prior snapshot.

    A candidate is *upserted* when its source_ref is new, when its curation
    fingerprint (content plus labels / space / verified) differs from the
    snapshot, or when it carries an empty content_sha (which cannot be confirmed
    unchanged, so it re-distills to stay safe). A source_ref in the snapshot but
    absent from ``current`` is *deleted*. A snapshot written by an older build
    (bare content_sha values) simply mismatches the new fingerprint once, so
    every manual re-distills on the first run after upgrade and stabilises after.
    """
    upserted: list[ManualCandidate] = []
    unchanged: list[str] = []
    seen: set[str] = set()

    for candidate in current:
        seen.add(candidate.source_ref)
        old_fp = previous.get(candidate.source_ref)
        fingerprint = _curation_fingerprint(candidate)
        if old_fp is None or not candidate.content_sha or fingerprint != old_fp:
            upserted.append(candidate)
        else:
            unchanged.append(candidate.source_ref)

    deleted = [ref for ref in previous if ref not in seen]

    upserted.sort(key=lambda c: c.doc_id)
    return FreshnessDelta(
        upserted=tuple(upserted),
        deleted=tuple(sorted(deleted)),
        unchanged=tuple(sorted(unchanged)),
    )


def plan_retirements(delta: FreshnessDelta) -> tuple[RetirementRequest, ...]:
    """Plan one retirement per deleted manual (deterministic, ordered)."""
    return tuple(
        RetirementRequest(source_ref=ref, reason="source manual removed") for ref in delta.deleted
    )


__all__ = [
    "FreshnessDelta",
    "RetirementRequest",
    "diff_snapshot",
    "plan_retirements",
    "snapshot_of",
]
