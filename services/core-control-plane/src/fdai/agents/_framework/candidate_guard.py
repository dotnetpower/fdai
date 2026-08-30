"""Candidate guard - provenance + poisoning defense for the discovery loop.

The discovery loop (`Norns -> Mimir`) turns operational signals into
`RuleCandidate` proposals. That intake is an adversarial surface: a
poisoned or malformed signal stream could flood Mimir with junk
candidates or smuggle an ungrounded rule toward promotion. The
architecture is explicit - "Candidates without grounded provenance are
rejected" - so Mimir must not append blindly.

`CandidateGuard` is the deterministic gate Mimir runs before accepting a
candidate. It never promotes anything (that is the quality gate's job);
it only decides *accept* vs *quarantine* and records a reason, so a
rejected candidate is preserved for audit rather than silently dropped.

Checks (all deterministic, no I/O, no model call):

- **Provenance** - `proposed_by` and a known `proposal_kind` are
  required.
- **Grounding** - a non-empty `evidence` mapping is required; an
  ungrounded candidate is quarantined.
- **Range sanity** - numeric evidence must be in range (a `rollback_rate`
  outside ``[0, 1]`` or a non-positive count is a corrupt/forged signal).
- **Flood detection** - identical candidate fingerprints beyond a repeat
  cap are quarantined as a suspected poisoning flood (Norns already
  dedups legitimate proposals, so a repeat burst is anomalous).
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fdai.agents._framework.bounded import BoundedLruDict

_ALLOWED_KINDS: frozenset[str] = frozenset(
    {"new", "new-scenario", "revision", "retirement", "threshold_adjustment"}
)
# Evidence keys that must be strictly positive when present.
_POSITIVE_COUNT_KEYS: tuple[str, ...] = (
    "occurrence_count",
    "sample_size",
    "override_count",
)

#: Cap on distinct repeat-count fingerprints retained. The guard's own flood
#: counter must be bounded, or the poisoning defense becomes a poisoning
#: vector: an attacker sending candidates with ever-changing fingerprints
#: (varying proposed_by / target_rule_id / source_signal) would grow the map
#: without limit - a memory-exhaustion DoS. LRU eviction is safe for flood
#: detection because a genuine flood REPEATS one fingerprint, keeping it
#: most-recently-used (never evicted mid-burst); a stream of all-distinct
#: fingerprints is not a flood of any single candidate.
_MAX_FINGERPRINTS = 10_000
_INVESTIGATION_STRATEGY_SOURCE = "investigation_strategy_comparison_cohort"
_MAX_SOURCE_KEYS = 1_000


@dataclass(frozen=True, slots=True)
class GuardVerdict:
    accepted: bool
    reason: str


class CandidateGuard:
    """Deterministic provenance + poisoning guard for RuleCandidates."""

    def __init__(
        self,
        *,
        max_repeats: int = 3,
        max_source_candidates: int = 100,
        source_window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_repeats < 1:
            raise ValueError("max_repeats MUST be >= 1")
        if max_source_candidates < 1:
            raise ValueError("max_source_candidates MUST be >= 1")
        if source_window_seconds <= 0:
            raise ValueError("source_window_seconds MUST be positive")
        self._max_repeats = max_repeats
        self._seen: BoundedLruDict[str, int] = BoundedLruDict(_MAX_FINGERPRINTS)
        self._max_source_candidates = max_source_candidates
        self._source_window_seconds = source_window_seconds
        self._clock = clock
        self._source_events: BoundedLruDict[str, deque[float]] = BoundedLruDict(_MAX_SOURCE_KEYS)

    def inspect(self, candidate: dict[str, Any]) -> GuardVerdict:
        kind = str(candidate.get("proposal_kind", ""))
        if kind not in _ALLOWED_KINDS:
            return GuardVerdict(False, f"unknown_proposal_kind:{kind or 'missing'}")
        if not candidate.get("proposed_by"):
            return GuardVerdict(False, "missing_provenance:proposed_by")
        evidence = candidate.get("evidence")
        if not isinstance(evidence, dict) or not evidence:
            return GuardVerdict(False, "ungrounded:no_evidence")

        rollback_rate = evidence.get("rollback_rate")
        if rollback_rate is not None:
            try:
                rate = float(rollback_rate)
            except (TypeError, ValueError):
                return GuardVerdict(False, "evidence_out_of_range:rollback_rate")
            if not math.isfinite(rate) or not 0.0 <= rate <= 1.0:
                return GuardVerdict(False, "evidence_out_of_range:rollback_rate")

        for key in _POSITIVE_COUNT_KEYS:
            value = evidence.get(key)
            if value is None:
                continue
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value <= 0
            ):
                return GuardVerdict(False, f"evidence_out_of_range:{key}")

        fingerprint = self._fingerprint(candidate)
        count = (self._seen.get(fingerprint) or 0) + 1
        self._seen.set(fingerprint, count)
        if count > self._max_repeats:
            return GuardVerdict(False, "flood_suspected")
        if self._source_rate_exceeded(candidate):
            return GuardVerdict(False, "source_rate_exceeded")

        return GuardVerdict(True, "ok")

    def _fingerprint(self, candidate: dict[str, Any]) -> str:
        source_signal = str(candidate.get("source_signal", ""))
        candidate_digest = ""
        if source_signal == _INVESTIGATION_STRATEGY_SOURCE:
            evidence = candidate.get("evidence")
            if isinstance(evidence, dict):
                candidate_digest = str(evidence.get("candidate_digest", ""))
        return "|".join(
            (
                str(candidate.get("proposed_by", "")),
                str(candidate.get("proposal_kind", "")),
                str(candidate.get("target_rule_id", "")),
                source_signal,
                candidate_digest,
            )
        )

    def _source_rate_exceeded(self, candidate: dict[str, Any]) -> bool:
        if candidate.get("source_signal") != _INVESTIGATION_STRATEGY_SOURCE:
            return False
        source_key = "|".join(
            (
                str(candidate.get("proposed_by", "")),
                str(candidate.get("target_rule_id", "")),
                _INVESTIGATION_STRATEGY_SOURCE,
            )
        )
        now = self._clock()
        cutoff = now - self._source_window_seconds
        events = self._source_events.get(source_key) or deque()
        while events and events[0] <= cutoff:
            events.popleft()
        events.append(now)
        self._source_events.set(source_key, events)
        return len(events) > self._max_source_candidates


__all__ = ["CandidateGuard", "GuardVerdict"]
