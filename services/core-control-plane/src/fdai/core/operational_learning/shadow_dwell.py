"""Per-candidate shadow dwell evidence for the rule discovery loop.

The discovery loop in
``docs/roadmap/rules-and-detection/rule-catalog-autonomous-discovery.md`` requires a
shadow-mode dwell check before any candidate may be considered for promotion: the
candidate's target must have run judge-and-log-only on real traffic for a configured
minimum period and sample size, with reviewed accuracy above threshold and **zero**
policy-violation escapes.

This module is the deterministic, pure half of that gate. It retains observations,
turns them into self-verifying evidence, and answers "does this evidence clear the
thresholds?" - nothing here promotes, mutates a catalog, or changes an assignment.

Two fail-closed properties matter more than any threshold value:

- **Absent evidence is not consent.** ``evaluate_shadow_dwell(None, ...)`` is
  ineligible, so a candidate that was never observed in shadow can never pass by
  omission.
- **Evidence verifies itself.** Counts that contradict each other, a window that ends
  before it starts, or a non-finite value are rejected outright rather than trusted,
  because the evidence travels on the wire from another agent.

The escape allowance is deliberately not configurable. The design says zero, and a
tunable escape budget is exactly the knob an operator under delivery pressure would
turn.
"""

from __future__ import annotations

import math
import re
from collections import OrderedDict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_MAX_TARGET_CHARS = 128
_MAX_SAMPLE_SIZE = 1_000_000
_MAX_WINDOW_DAYS = 3_650
_MAX_TARGETS = 5_000
_MAX_OBSERVATIONS_PER_TARGET = 10_000

#: The discovery loop tolerates no shadow policy-violation escape. Not a setting.
MAX_POLICY_ESCAPES = 0

_EVIDENCE_FIELDS = frozenset(
    {
        "target",
        "window_start",
        "window_end",
        "sample_size",
        "reviewed_count",
        "agreed_count",
        "policy_escapes",
    }
)


class ShadowDwellEvidenceError(ValueError):
    """Bounded fail-closed reason for one rejected shadow dwell record."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ShadowDwellThresholds:
    """Configured dwell bars for a discovery-loop candidate."""

    min_shadow_days: int = 14
    min_samples: int = 100
    min_accuracy: float = 0.98

    def __post_init__(self) -> None:
        if isinstance(self.min_shadow_days, bool) or not isinstance(self.min_shadow_days, int):
            raise ValueError("min_shadow_days MUST be an integer")
        if isinstance(self.min_samples, bool) or not isinstance(self.min_samples, int):
            raise ValueError("min_samples MUST be an integer")
        if self.min_shadow_days < 1 or self.min_samples < 1:
            raise ValueError("shadow dwell thresholds MUST require at least one day and sample")
        if (
            not isinstance(self.min_accuracy, (int, float))
            or isinstance(self.min_accuracy, bool)
            or not math.isfinite(self.min_accuracy)
            or not 0.0 < self.min_accuracy <= 1.0
        ):
            raise ValueError("min_accuracy MUST be in (0, 1]")


@dataclass(frozen=True, slots=True)
class ShadowDwellObservation:
    """One judge-and-log-only observation of a candidate's target.

    ``agreed`` is meaningful only for a reviewed observation; an unreviewed
    observation that claims agreement is a fabricated accuracy sample.
    """

    target: str
    observed_at: datetime
    reviewed: bool
    agreed: bool
    policy_escape: bool

    def __post_init__(self) -> None:
        _validate_target(self.target)
        _validate_instant(self.observed_at, "observed_at")
        for name, value in (
            ("reviewed", self.reviewed),
            ("agreed", self.agreed),
            ("policy_escape", self.policy_escape),
        ):
            if not isinstance(value, bool):
                raise ShadowDwellEvidenceError(f"observation_{name}_invalid")
        if self.agreed and not self.reviewed:
            raise ShadowDwellEvidenceError("observation_agreement_unreviewed")


@dataclass(frozen=True, slots=True)
class ShadowDwellEvidence:
    """Self-verifying dwell record for one candidate target."""

    target: str
    window_start: datetime
    window_end: datetime
    sample_size: int
    reviewed_count: int
    agreed_count: int
    policy_escapes: int

    def __post_init__(self) -> None:
        _validate_target(self.target)
        _validate_instant(self.window_start, "window_start")
        _validate_instant(self.window_end, "window_end")
        if self.window_end < self.window_start:
            raise ShadowDwellEvidenceError("window_inverted")
        for name, value in (
            ("sample_size", self.sample_size),
            ("reviewed_count", self.reviewed_count),
            ("agreed_count", self.agreed_count),
            ("policy_escapes", self.policy_escapes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ShadowDwellEvidenceError(f"count_invalid:{name}")
        if self.sample_size > _MAX_SAMPLE_SIZE:
            raise ShadowDwellEvidenceError("sample_size_out_of_range")
        if self.reviewed_count > self.sample_size:
            raise ShadowDwellEvidenceError("count_conflict:reviewed_count")
        if self.agreed_count > self.reviewed_count:
            raise ShadowDwellEvidenceError("count_conflict:agreed_count")
        if self.policy_escapes > self.sample_size:
            raise ShadowDwellEvidenceError("count_conflict:policy_escapes")
        if self.shadow_days > _MAX_WINDOW_DAYS:
            raise ShadowDwellEvidenceError("window_out_of_range")

    @property
    def shadow_days(self) -> float:
        """Days actually observed, measured between first and last observation.

        Measuring to "now" would let the wall clock satisfy the gate: a target
        watched once and then abandoned would keep accruing dwell while nothing is
        being observed at all.
        """

        return (self.window_end - self.window_start).total_seconds() / 86400.0

    @property
    def accuracy(self) -> float:
        """Reviewed agreement rate; zero when nothing was reviewed."""

        if self.reviewed_count == 0:
            return 0.0
        return self.agreed_count / self.reviewed_count

    def to_mapping(self) -> dict[str, object]:
        return {
            "target": self.target,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "sample_size": self.sample_size,
            "reviewed_count": self.reviewed_count,
            "agreed_count": self.agreed_count,
            "policy_escapes": self.policy_escapes,
        }

    @classmethod
    def from_mapping(cls, value: object) -> ShadowDwellEvidence:
        if not isinstance(value, Mapping) or set(value) != _EVIDENCE_FIELDS:
            raise ShadowDwellEvidenceError("evidence_schema_invalid")
        target = value["target"]
        if not isinstance(target, str):
            raise ShadowDwellEvidenceError("target_invalid")
        return cls(
            target=target,
            window_start=_parse_instant(value["window_start"], "window_start"),
            window_end=_parse_instant(value["window_end"], "window_end"),
            sample_size=_parse_count(value["sample_size"], "sample_size"),
            reviewed_count=_parse_count(value["reviewed_count"], "reviewed_count"),
            agreed_count=_parse_count(value["agreed_count"], "agreed_count"),
            policy_escapes=_parse_count(value["policy_escapes"], "policy_escapes"),
        )


@dataclass(frozen=True, slots=True)
class ShadowDwellDecision:
    """Deterministic dwell verdict plus every unmet bar."""

    eligible: bool
    gaps: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.eligible != (not self.gaps):
            raise ValueError("a shadow dwell decision is eligible exactly when no gap remains")


def evaluate_shadow_dwell(
    evidence: ShadowDwellEvidence | None,
    thresholds: ShadowDwellThresholds,
) -> ShadowDwellDecision:
    """Return the dwell verdict for ``evidence`` against ``thresholds``."""

    if evidence is None:
        return ShadowDwellDecision(eligible=False, gaps=("no_shadow_dwell_evidence",))
    gaps: list[str] = []
    shadow_days = evidence.shadow_days
    if shadow_days < thresholds.min_shadow_days:
        gaps.append(f"shadow_days={shadow_days:.2f}<min_shadow_days={thresholds.min_shadow_days}")
    if evidence.sample_size < thresholds.min_samples:
        gaps.append(f"sample_size={evidence.sample_size}<min_samples={thresholds.min_samples}")
    if evidence.reviewed_count == 0:
        gaps.append("no_reviewed_samples")
    elif evidence.accuracy < thresholds.min_accuracy:
        gaps.append(f"accuracy={evidence.accuracy:.3f}<min_accuracy={thresholds.min_accuracy}")
    if evidence.policy_escapes > MAX_POLICY_ESCAPES:
        gaps.append(
            f"policy_escapes={evidence.policy_escapes}>max_policy_escapes={MAX_POLICY_ESCAPES}"
        )
    return ShadowDwellDecision(eligible=not gaps, gaps=tuple(gaps))


class ShadowDwellLedger:
    """Bounded per-target retention of shadow observations.

    Retention is bounded on both axes because the observation stream is driven by
    external traffic: an unbounded ledger inside a long-lived learner is a
    memory-exhaustion vector. Evidence therefore describes the retained window,
    which is the window the process can still prove.
    """

    def __init__(
        self,
        *,
        max_targets: int = _MAX_TARGETS,
        max_observations_per_target: int = _MAX_OBSERVATIONS_PER_TARGET,
    ) -> None:
        if min(max_targets, max_observations_per_target) < 1:
            raise ValueError("shadow dwell ledger capacities MUST be positive")
        self._max_targets = max_targets
        self._max_observations_per_target = max_observations_per_target
        self._observations: OrderedDict[str, deque[ShadowDwellObservation]] = OrderedDict()

    def record(self, observation: ShadowDwellObservation) -> None:
        """Retain one observation, evicting the least recently used target if needed."""

        if not isinstance(observation, ShadowDwellObservation):
            raise TypeError("shadow dwell ledger accepts ShadowDwellObservation only")
        retained = self._observations.get(observation.target)
        if retained is None:
            retained = deque(maxlen=self._max_observations_per_target)
            self._observations[observation.target] = retained
        retained.append(observation)
        self._observations.move_to_end(observation.target)
        while len(self._observations) > self._max_targets:
            self._observations.popitem(last=False)

    def evidence_for(self, target: str) -> ShadowDwellEvidence | None:
        """Return retained evidence for ``target``, or ``None`` when unobserved."""

        retained = self._observations.get(target)
        if not retained:
            return None
        instants = [item.observed_at for item in retained]
        return ShadowDwellEvidence(
            target=target,
            window_start=min(instants),
            window_end=max(instants),
            sample_size=len(retained),
            reviewed_count=sum(1 for item in retained if item.reviewed),
            agreed_count=sum(1 for item in retained if item.reviewed and item.agreed),
            policy_escapes=sum(1 for item in retained if item.policy_escape),
        )

    def targets(self) -> tuple[str, ...]:
        return tuple(self._observations)

    def observation_count(self, target: str) -> int:
        retained = self._observations.get(target)
        return len(retained) if retained else 0


def _validate_target(target: object) -> None:
    if (
        not isinstance(target, str)
        or len(target) > _MAX_TARGET_CHARS
        or _IDENTIFIER.fullmatch(target) is None
    ):
        raise ShadowDwellEvidenceError("target_invalid")


def _validate_instant(value: object, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ShadowDwellEvidenceError(f"instant_invalid:{name}")


def _parse_instant(value: object, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and len(value) <= 64:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ShadowDwellEvidenceError(f"instant_invalid:{name}") from exc
    else:
        raise ShadowDwellEvidenceError(f"instant_invalid:{name}")
    if parsed.tzinfo is None:
        raise ShadowDwellEvidenceError(f"instant_invalid:{name}")
    return parsed.astimezone(UTC)


def _parse_count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ShadowDwellEvidenceError(f"count_invalid:{name}")
    return value


__all__ = [
    "MAX_POLICY_ESCAPES",
    "ShadowDwellDecision",
    "ShadowDwellEvidence",
    "ShadowDwellEvidenceError",
    "ShadowDwellLedger",
    "ShadowDwellObservation",
    "ShadowDwellThresholds",
    "evaluate_shadow_dwell",
]
