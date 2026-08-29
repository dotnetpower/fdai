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

from fdai.shared.ontology.threshold_bounds import load_promotion_gate_bounds

_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_MAX_TARGET_CHARS = 128
_MAX_SAMPLE_SIZE = 1_000_000
_MAX_WINDOW_DAYS = 3_650
_MAX_TARGETS = 5_000
_MAX_OBSERVATIONS_PER_TARGET = 10_000

#: The discovery loop tolerates no shadow policy-violation escape. Not a setting.
MAX_POLICY_ESCAPES = 0

# The floors and the accuracy ceiling are read from the shipped ActionType contract, so a
# widened ontology bound propagates instead of being shadowed by a copied literal.
_PROMOTION_GATE_BOUNDS = load_promotion_gate_bounds()
_MIN_SHADOW_DAYS_FLOOR = int(_PROMOTION_GATE_BOUNDS["promotion_gate.min_shadow_days"].minimum or 1)
_MIN_SAMPLES_FLOOR = int(_PROMOTION_GATE_BOUNDS["promotion_gate.min_samples"].minimum or 1)
_MIN_ACCURACY_CEILING = float(_PROMOTION_GATE_BOUNDS["promotion_gate.min_accuracy"].maximum or 1.0)

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
        if self.min_shadow_days < _MIN_SHADOW_DAYS_FLOOR or self.min_samples < _MIN_SAMPLES_FLOOR:
            raise ValueError("shadow dwell thresholds MUST require at least one day and sample")
        if (
            not isinstance(self.min_accuracy, (int, float))
            or isinstance(self.min_accuracy, bool)
            or not math.isfinite(self.min_accuracy)
            or not 0.0 < self.min_accuracy <= _MIN_ACCURACY_CEILING
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
        # Rounding the reported value can print the threshold itself, so a real gap
        # reads as "14.00<14" and looks like a bug in the gate. Truncate instead.
        observed = math.floor(shadow_days * 100) / 100
        gaps.append(f"shadow_days={observed:.2f}<min_shadow_days={thresholds.min_shadow_days}")
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


@dataclass(slots=True)
class _RetainedTarget:
    """Bounded observation detail plus counters that eviction cannot erase."""

    observations: deque[ShadowDwellObservation]
    observation_reviews: OrderedDict[str, bool]
    first_observed: datetime
    last_observed: datetime
    sample_size: int = 0
    reviewed_count: int = 0
    agreed_count: int = 0
    policy_escapes: int = 0


class ShadowDwellLedger:
    """Bounded per-target retention of shadow observations.

    Retained observation *detail* is bounded on both axes because the observation
    stream is driven by external traffic: an unbounded ledger inside a long-lived
    learner is a memory-exhaustion vector. The counted evidence is kept separately
    and is not bounded by that eviction, because dropping the oldest observations
    would silently turn the non-negotiable zero-escape bar into "zero escapes in
    the retained window" and re-admit a candidate that already escaped.

    Evicting a whole target is safe by contrast: an unknown target has no evidence
    at all, and absent evidence is already ineligible.
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
        self._targets: OrderedDict[str, _RetainedTarget] = OrderedDict()

    def record(
        self,
        observation: ShadowDwellObservation,
        *,
        observation_id: str | None = None,
    ) -> bool:
        """Retain one observation once and return whether it was accepted."""

        if not isinstance(observation, ShadowDwellObservation):
            raise TypeError("shadow dwell ledger accepts ShadowDwellObservation only")
        if observation_id is not None:
            _validate_observation_id(observation_id)
        entry = self._targets.get(observation.target)
        if entry is None:
            entry = _RetainedTarget(
                observations=deque(maxlen=self._max_observations_per_target),
                observation_reviews=OrderedDict(),
                first_observed=observation.observed_at,
                last_observed=observation.observed_at,
            )
            self._targets[observation.target] = entry
        if observation_id is not None and observation_id in entry.observation_reviews:
            return False
        entry.observations.append(observation)
        if observation_id is not None:
            entry.observation_reviews[observation_id] = observation.reviewed
            while len(entry.observation_reviews) > self._max_observations_per_target:
                entry.observation_reviews.popitem(last=False)
        entry.first_observed = min(entry.first_observed, observation.observed_at)
        entry.last_observed = max(entry.last_observed, observation.observed_at)
        if entry.sample_size < _MAX_SAMPLE_SIZE:
            entry.sample_size += 1
            entry.reviewed_count += int(observation.reviewed)
            entry.agreed_count += int(observation.reviewed and observation.agreed)
        entry.policy_escapes += int(observation.policy_escape)
        self._targets.move_to_end(observation.target)
        while len(self._targets) > self._max_targets:
            self._targets.popitem(last=False)
        return True

    def apply_review(self, *, target: str, observation_id: str, agreed: bool) -> bool:
        """Upgrade one retained unreviewed sample without counting it twice."""

        _validate_target(target)
        _validate_observation_id(observation_id)
        if not isinstance(agreed, bool):
            raise ShadowDwellEvidenceError("observation_agreed_invalid")
        entry = self._targets.get(target)
        if entry is None or observation_id not in entry.observation_reviews:
            return False
        if entry.observation_reviews[observation_id]:
            return False
        entry.observation_reviews[observation_id] = True
        entry.observation_reviews.move_to_end(observation_id)
        entry.reviewed_count += 1
        entry.agreed_count += int(agreed)
        self._targets.move_to_end(target)
        return True

    def evidence_for(self, target: str) -> ShadowDwellEvidence | None:
        """Return counted evidence for ``target``, or ``None`` when unobserved."""

        entry = self._targets.get(target)
        if entry is None or not entry.sample_size:
            return None
        return ShadowDwellEvidence(
            target=target,
            window_start=entry.first_observed,
            window_end=entry.last_observed,
            sample_size=entry.sample_size,
            reviewed_count=entry.reviewed_count,
            agreed_count=entry.agreed_count,
            # Saturating the sample count must not silently zero a real escape.
            policy_escapes=min(entry.policy_escapes, entry.sample_size),
        )

    def targets(self) -> tuple[str, ...]:
        return tuple(self._targets)

    def observation_count(self, target: str) -> int:
        """Return retained observation detail, which eviction does bound."""

        entry = self._targets.get(target)
        return len(entry.observations) if entry is not None else 0


def _validate_target(target: object) -> None:
    if (
        not isinstance(target, str)
        or len(target) > _MAX_TARGET_CHARS
        or _IDENTIFIER.fullmatch(target) is None
    ):
        raise ShadowDwellEvidenceError("target_invalid")


def _validate_observation_id(value: object) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or not value.isascii()
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in value)
    ):
        raise ShadowDwellEvidenceError("observation_id_invalid")


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
