"""Pure pattern evidence: temporal holdout envelopes and measured reuse statistics.

Both are derived only from independently verified, enforce-mode outcomes grouped by the pattern
signature. They never create or execute a pattern: holdout evidence lets shadow growth admit a
pattern, and measured statistics replace its placeholder success rate with the observed one. A
failure or rollback lowers the recomputed rate on the next run, so demotion needs no separate
path. Rollbacks are excluded from the technical-failure denominator, as in
:class:`~fdai.core.tiers.t1_lightweight.retained_pattern_bindings.RetainedReuseStatistics`.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from fdai.core.tiers.t1_lightweight.contextual_reuse import OperationalCaseContext

HOLDOUT_STATE_PREFIX: Final = "measurement:pattern_holdout:"
_MAX_SAMPLES: Final = 1_000


def pattern_signature(
    *,
    action_type_id: str,
    params: Mapping[str, Any],
    rule_id: str,
    operational_case: OperationalCaseContext | None,
) -> str | None:
    """Return the stable pattern signature, or ``None`` when the material is not encodable."""
    material = {
        "action_type_id": action_type_id,
        "operational_case": operational_case.to_mapping() if operational_case else None,
        "params": dict(params),
        "rule_id": rule_id,
    }
    try:
        encoded = json.dumps(
            material, separators=(",", ":"), sort_keys=True, allow_nan=False
        ).encode()
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ScoredOutcome:
    """One enforce-mode outcome reduced to what evidence needs."""

    signature: str
    observed_at: datetime
    scorable: bool
    verified: bool
    rolled_back: bool


@dataclass(frozen=True, slots=True)
class HoldoutPolicy:
    min_samples: int = 20
    min_window: timedelta = timedelta(days=1)

    def __post_init__(self) -> None:
        if self.min_samples < 1 or self.min_window < timedelta(0):
            raise ValueError("holdout policy MUST be positive")


@dataclass(frozen=True, slots=True)
class StatisticsPolicy:
    min_outcomes: int = 20

    def __post_init__(self) -> None:
        if self.min_outcomes < 1:
            raise ValueError("min_outcomes MUST be >= 1")


@dataclass(frozen=True, slots=True)
class MeasuredStatistics:
    success_rate: float
    reuse_count: int


def holdout_envelopes(
    outcomes: Iterable[ScoredOutcome], *, policy: HoldoutPolicy | None = None
) -> dict[str, dict[str, Any]]:
    """Build one durable holdout envelope per signature.

    Every scorable outcome is a sample; the validator later keeps only samples strictly after the
    pattern's learned time. An envelope is complete only when enough later samples span the
    minimum window, so a pattern is never admitted on a burst of near-simultaneous outcomes.
    """
    resolved = policy or HoldoutPolicy()
    grouped: dict[str, list[ScoredOutcome]] = defaultdict(list)
    for outcome in outcomes:
        if outcome.scorable:
            grouped[outcome.signature].append(outcome)
    envelopes: dict[str, dict[str, Any]] = {}
    for signature, items in grouped.items():
        by_time: dict[datetime, ScoredOutcome] = {}
        for item in sorted(items, key=lambda value: value.observed_at):
            by_time.setdefault(item.observed_at, item)
        ordered = list(by_time.values())[-_MAX_SAMPLES:]
        first, last = ordered[0].observed_at, ordered[-1].observed_at
        later = len(ordered) - 1
        envelopes[signature] = {
            "pattern_id": signature,
            "complete": later >= resolved.min_samples and last - first >= resolved.min_window,
            "samples": [
                {
                    "pattern_id": signature,
                    "observed_at": item.observed_at.isoformat(),
                    "was_correct": item.verified and not item.rolled_back,
                }
                for item in ordered
            ],
        }
    return envelopes


def measured_statistics(
    outcomes: Iterable[ScoredOutcome], *, policy: StatisticsPolicy | None = None
) -> dict[str, MeasuredStatistics]:
    """Return observed success rate and denominator per signature with enough outcomes.

    A signature below the minimum is absent, so the caller leaves or resets it to unproven.
    """
    resolved = policy or StatisticsPolicy()
    successes: dict[str, int] = defaultdict(int)
    failures: dict[str, int] = defaultdict(int)
    for outcome in outcomes:
        if not outcome.scorable or outcome.rolled_back:
            continue
        if outcome.verified:
            successes[outcome.signature] += 1
        else:
            failures[outcome.signature] += 1
    result: dict[str, MeasuredStatistics] = {}
    for signature in successes.keys() | failures.keys():
        total = successes[signature] + failures[signature]
        if total >= resolved.min_outcomes:
            result[signature] = MeasuredStatistics(
                success_rate=successes[signature] / total, reuse_count=total
            )
    return result


__all__ = [
    "HOLDOUT_STATE_PREFIX",
    "HoldoutPolicy",
    "MeasuredStatistics",
    "ScoredOutcome",
    "StatisticsPolicy",
    "holdout_envelopes",
    "measured_statistics",
    "pattern_signature",
]
