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
from collections import Counter
from dataclasses import dataclass
from typing import Any

_ALLOWED_KINDS: frozenset[str] = frozenset(
    {"new", "revision", "retirement", "threshold_adjustment"}
)
# Evidence keys that must be strictly positive when present.
_POSITIVE_COUNT_KEYS: tuple[str, ...] = (
    "occurrence_count",
    "sample_size",
    "override_count",
)


@dataclass(frozen=True, slots=True)
class GuardVerdict:
    accepted: bool
    reason: str


class CandidateGuard:
    """Deterministic provenance + poisoning guard for RuleCandidates."""

    def __init__(self, *, max_repeats: int = 3) -> None:
        if max_repeats < 1:
            raise ValueError("max_repeats MUST be >= 1")
        self._max_repeats = max_repeats
        self._seen: Counter[str] = Counter()

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
        self._seen[fingerprint] += 1
        if self._seen[fingerprint] > self._max_repeats:
            return GuardVerdict(False, "flood_suspected")

        return GuardVerdict(True, "ok")

    def _fingerprint(self, candidate: dict[str, Any]) -> str:
        return "|".join(
            (
                str(candidate.get("proposed_by", "")),
                str(candidate.get("proposal_kind", "")),
                str(candidate.get("target_rule_id", "")),
                str(candidate.get("source_signal", "")),
            )
        )


__all__ = ["CandidateGuard", "GuardVerdict"]
