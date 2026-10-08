"""Pre-registered runtime shadow protocols for typed instance selection (#2011).

Both protocols are fixed before any live measurement they judge. Changing a parameter requires a
new protocol id. Reports carry no qualification of production answers and no execution authority;
they are inputs to a separate, human-approved promotion decision.

``typed-selection-runtime-latency.v1`` judges the runtime shadow path: gated observation latency,
provider-unavailable rate, foreground answer-path regression while an observation is in flight, and
event-loop lag. Unavailable observations count at the total deadline, never as exclusions.

``typed-selection-runtime-window.v1`` judges gated decisions from the runtime observer over the
frozen ``instance-runtime-window.v1`` cases, with R=4 decisions per case. It reuses the
qualification arithmetic: wrong selections bound the one-sided 95% Clopper-Pearson upper limit,
and correct rate covers answerable cases. An unavailable answerable decision counts as not correct.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from .ontology_semantic_qualification import clopper_pearson_upper

LATENCY_PROTOCOL_ID = "typed-selection-runtime-latency.v1"
WINDOW_PROTOCOL_ID = "typed-selection-runtime-window.v1"
WINDOW_CASE_SET = "instance-runtime-window.v1.json"
_PROVIDER_UNAVAILABLE = frozenset({"proposal_unavailable", "deadline_exceeded"})


def nearest_rank(values: Sequence[float], percentile: float) -> float:
    """Return the nearest-rank percentile of a non-empty sample."""
    if not values or not 0 < percentile <= 100:
        raise ValueError("percentile requires samples and a rank in (0, 100]")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile / 100 * len(ordered)) - 1)]


@dataclass(frozen=True, slots=True)
class LatencyProtocol:
    """Frozen v1 thresholds; changing any value requires a new protocol id."""

    protocol_id: str = LATENCY_PROTOCOL_ID
    min_observations: int = 256
    deadline_ms: float = 30_000.0
    max_gated_p50_ms: float = 6_000.0
    max_gated_p95_ms: float = 12_000.0
    max_gated_p99_ms: float = 20_000.0
    max_provider_unavailable_rate: float = 0.02
    max_foreground_p95_regression_ms: float = 50.0
    max_event_loop_lag_p99_ms: float = 100.0

    def __post_init__(self) -> None:
        if (
            self.protocol_id,
            self.min_observations,
            self.deadline_ms,
            self.max_gated_p50_ms,
            self.max_gated_p95_ms,
            self.max_gated_p99_ms,
            self.max_provider_unavailable_rate,
            self.max_foreground_p95_regression_ms,
            self.max_event_loop_lag_p99_ms,
        ) != (LATENCY_PROTOCOL_ID, 256, 30_000.0, 6_000.0, 12_000.0, 20_000.0, 0.02, 50.0, 100.0):
            raise ValueError("runtime latency protocol v1 parameters are pre-registered")


@dataclass(frozen=True, slots=True)
class ObservationLatency:
    latency_ms: float
    unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class ForegroundPair:
    """One answer-path call with the shadow off and one while an observation is in flight."""

    off_ms: float
    contended_ms: float
    same_outcome: bool


@dataclass(frozen=True, slots=True)
class LatencyReport:
    protocol_id: str
    observations: int
    gated_p50_ms: float
    gated_p95_ms: float
    gated_p99_ms: float
    provider_unavailable: int
    foreground_off_p95_ms: float
    foreground_contended_p95_ms: float
    foreground_outcome_mismatches: int
    event_loop_lag_p99_ms: float
    failure_codes: tuple[str, ...]
    production_qualification: Literal[False] = field(default=False, init=False)
    execution_authority: Literal[False] = field(default=False, init=False)

    @property
    def passed(self) -> bool:
        return not self.failure_codes


def evaluate_latency(
    *,
    observations: Sequence[ObservationLatency],
    foreground: Sequence[ForegroundPair],
    event_loop_lag_ms: Sequence[float],
    protocol: LatencyProtocol | None = None,
) -> LatencyReport:
    """Judge one complete campaign; deadlines and unavailability are never excluded."""
    protocol = protocol or LatencyProtocol()
    if not foreground or not event_loop_lag_ms:
        raise ValueError("latency evaluation requires foreground and event-loop samples")
    failures: list[str] = []
    if len(observations) < protocol.min_observations:
        failures.append("observation-count-below-minimum")
    gated = [
        protocol.deadline_ms if item.unavailable_reason is not None else item.latency_ms
        for item in observations
    ] or [protocol.deadline_ms]
    p50, p95, p99 = (nearest_rank(gated, rank) for rank in (50, 95, 99))
    unavailable = sum(item.unavailable_reason in _PROVIDER_UNAVAILABLE for item in observations)
    off = nearest_rank([item.off_ms for item in foreground], 95)
    contended = nearest_rank([item.contended_ms for item in foreground], 95)
    mismatches = sum(not item.same_outcome for item in foreground)
    lag = nearest_rank(event_loop_lag_ms, 99)
    for name, value, limit in (
        ("gated-p50-exceeded", p50, protocol.max_gated_p50_ms),
        ("gated-p95-exceeded", p95, protocol.max_gated_p95_ms),
        ("gated-p99-exceeded", p99, protocol.max_gated_p99_ms),
        ("event-loop-lag-p99-exceeded", lag, protocol.max_event_loop_lag_p99_ms),
        (
            "foreground-p95-regression-exceeded",
            contended - off,
            protocol.max_foreground_p95_regression_ms,
        ),
    ):
        if value > limit:
            failures.append(name)
    if unavailable > protocol.max_provider_unavailable_rate * max(1, len(observations)):
        failures.append("provider-unavailable-rate-exceeded")
    if mismatches:
        failures.append("foreground-outcome-changed")
    return LatencyReport(
        protocol_id=protocol.protocol_id,
        observations=len(observations),
        gated_p50_ms=p50,
        gated_p95_ms=p95,
        gated_p99_ms=p99,
        provider_unavailable=unavailable,
        foreground_off_p95_ms=off,
        foreground_contended_p95_ms=contended,
        foreground_outcome_mismatches=mismatches,
        event_loop_lag_p99_ms=lag,
        failure_codes=tuple(failures),
    )


@dataclass(frozen=True, slots=True)
class WindowProtocol:
    """Frozen v1 parameters; changing any value requires a new protocol id."""

    protocol_id: str = WINDOW_PROTOCOL_ID
    case_set: str = WINDOW_CASE_SET
    cases: int = 64
    decisions_per_case: int = 4
    confidence: float = 0.95
    max_pooled_wrong_upper_bound: float = 0.02
    max_language_wrong_upper_bound: float = 0.03
    min_language_correct_rate: float = 0.95
    max_unavailable_rate: float = 0.02

    def __post_init__(self) -> None:
        if (
            self.protocol_id,
            self.case_set,
            self.cases,
            self.decisions_per_case,
            self.confidence,
            self.max_pooled_wrong_upper_bound,
            self.max_language_wrong_upper_bound,
            self.min_language_correct_rate,
            self.max_unavailable_rate,
        ) != (WINDOW_PROTOCOL_ID, WINDOW_CASE_SET, 64, 4, 0.95, 0.02, 0.03, 0.95, 0.02):
            raise ValueError("runtime window protocol v1 parameters are pre-registered")


@dataclass(frozen=True, slots=True)
class WindowDecision:
    """One runtime gated decision adjudicated against its frozen pre-registered label."""

    case_id: str
    language: str
    expected: frozenset[str]
    gated_outcome: str
    selected: frozenset[str]

    @property
    def unavailable(self) -> bool:
        return self.gated_outcome == "unavailable"

    @property
    def wrong(self) -> bool:
        return not self.unavailable and bool(self.selected - self.expected)

    @property
    def correct(self) -> bool:
        return not self.unavailable and self.selected == self.expected


@dataclass(frozen=True, slots=True)
class WindowLanguage:
    language: str
    decisions: int
    wrong: int
    wrong_upper_bound: float
    answerable: int
    correct: int
    unavailable: int
    disagreed: int

    @property
    def correct_rate(self) -> float:
        return self.correct / self.answerable if self.answerable else 1.0


@dataclass(frozen=True, slots=True)
class WindowReport:
    protocol_id: str
    decisions: int
    wrong: int
    wrong_upper_bound: float
    unavailable: int
    languages: tuple[WindowLanguage, ...]
    failure_codes: tuple[str, ...]
    production_qualification: Literal[False] = field(default=False, init=False)
    execution_authority: Literal[False] = field(default=False, init=False)

    @property
    def passed(self) -> bool:
        return not self.failure_codes


def evaluate_window(
    decisions: Sequence[WindowDecision], protocol: WindowProtocol | None = None
) -> WindowReport:
    """Judge the complete window once; every planned decision must be present."""
    protocol = protocol or WindowProtocol()
    expected_total = protocol.cases * protocol.decisions_per_case
    counts: dict[str, int] = {}
    for item in decisions:
        counts[item.case_id] = counts.get(item.case_id, 0) + 1
    if (
        len(decisions) != expected_total
        or len(counts) != protocol.cases
        or set(counts.values()) != {protocol.decisions_per_case}
    ):
        raise ValueError("runtime window requires every planned decision exactly once")
    failures: list[str] = []
    wrong = sum(item.wrong for item in decisions)
    pooled = clopper_pearson_upper(wrong, len(decisions), protocol.confidence)
    unavailable = sum(item.unavailable for item in decisions)
    if pooled > protocol.max_pooled_wrong_upper_bound:
        failures.append("pooled-wrong-selection-bound-exceeded")
    if unavailable > protocol.max_unavailable_rate * len(decisions):
        failures.append("unavailable-rate-exceeded")
    languages: list[WindowLanguage] = []
    for language in sorted({item.language for item in decisions}):
        own = [item for item in decisions if item.language == language]
        own_wrong = sum(item.wrong for item in own)
        answerable = [item for item in own if item.expected]
        result = WindowLanguage(
            language=language,
            decisions=len(own),
            wrong=own_wrong,
            wrong_upper_bound=clopper_pearson_upper(own_wrong, len(own), protocol.confidence),
            answerable=len(answerable),
            correct=sum(item.correct for item in answerable),
            unavailable=sum(item.unavailable for item in own),
            disagreed=sum(item.gated_outcome == "disagreed" for item in own),
        )
        languages.append(result)
        if result.wrong_upper_bound > protocol.max_language_wrong_upper_bound:
            failures.append(f"{language}-wrong-selection-bound-exceeded")
        if result.correct_rate < protocol.min_language_correct_rate:
            failures.append(f"{language}-correct-rate-below-threshold")
    return WindowReport(
        protocol_id=protocol.protocol_id,
        decisions=len(decisions),
        wrong=wrong,
        wrong_upper_bound=pooled,
        unavailable=unavailable,
        languages=tuple(languages),
        failure_codes=tuple(failures),
    )


__all__ = [
    "LATENCY_PROTOCOL_ID",
    "WINDOW_CASE_SET",
    "WINDOW_PROTOCOL_ID",
    "ForegroundPair",
    "LatencyProtocol",
    "LatencyReport",
    "ObservationLatency",
    "WindowDecision",
    "WindowLanguage",
    "WindowProtocol",
    "WindowReport",
    "evaluate_latency",
    "evaluate_window",
    "nearest_rank",
]
