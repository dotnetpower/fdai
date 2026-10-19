"""Pre-registered live protocols for the governed typed-selection answer path (#2034)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from .ontology_semantic_qualification import clopper_pearson_upper
from .ontology_typed_selection_campaign import nearest_rank

LATENCY_PROTOCOL_ID = "governed-typed-selection-answer-latency.v1"
WINDOW_PROTOCOL_ID = "governed-typed-selection-answer-window.v1"
WINDOW_CASE_SET = "governed-read-window.v1.json"
LATENCY_PROTOCOL_ID_V2 = "governed-typed-selection-answer-latency.v2"
WINDOW_PROTOCOL_ID_V2 = "governed-typed-selection-answer-window.v2"
WINDOW_CASE_SET_V2 = "governed-read-window.v2.json"


@dataclass(frozen=True, slots=True)
class GovernedLatencyProtocol:
    """Frozen user-facing thresholds; changing any value requires a new protocol id."""

    protocol_id: str = LATENCY_PROTOCOL_ID
    min_observations: int = 256
    deadline_ms: float = 30_000.0
    max_p50_ms: float = 8_000.0
    max_p95_ms: float = 15_000.0
    max_p99_ms: float = 25_000.0
    max_provider_unavailable_rate: float = 0.02
    max_event_loop_lag_p99_ms: float = 100.0

    def __post_init__(self) -> None:
        if (
            self.protocol_id,
            self.min_observations,
            self.deadline_ms,
            self.max_p50_ms,
            self.max_p95_ms,
            self.max_p99_ms,
            self.max_provider_unavailable_rate,
            self.max_event_loop_lag_p99_ms,
        ) != (
            LATENCY_PROTOCOL_ID,
            256,
            30_000.0,
            8_000.0,
            15_000.0,
            25_000.0,
            0.02,
            100.0,
        ):
            raise ValueError("governed answer latency protocol v1 parameters are pre-registered")


@dataclass(frozen=True, slots=True)
class GovernedLatencyObservation:
    latency_ms: float
    unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class GovernedLatencyProtocolV2:
    """Fresh Sol-bound thresholds; changing any value requires a new protocol id."""

    protocol_id: str = LATENCY_PROTOCOL_ID_V2
    min_observations: int = 256
    deadline_ms: float = 30_000.0
    max_p50_ms: float = 8_000.0
    max_p95_ms: float = 15_000.0
    max_p99_ms: float = 25_000.0
    max_provider_unavailable_rate: float = 0.02
    max_event_loop_lag_p99_ms: float = 100.0

    def __post_init__(self) -> None:
        if (
            self.protocol_id,
            self.min_observations,
            self.deadline_ms,
            self.max_p50_ms,
            self.max_p95_ms,
            self.max_p99_ms,
            self.max_provider_unavailable_rate,
            self.max_event_loop_lag_p99_ms,
        ) != (
            LATENCY_PROTOCOL_ID_V2,
            256,
            30_000.0,
            8_000.0,
            15_000.0,
            25_000.0,
            0.02,
            100.0,
        ):
            raise ValueError("governed answer latency protocol v2 parameters are pre-registered")


@dataclass(frozen=True, slots=True)
class GovernedLatencyReport:
    protocol_id: str
    observations: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    provider_unavailable: int
    event_loop_lag_p99_ms: float
    failure_codes: tuple[str, ...]
    production_qualification: Literal[False] = field(default=False, init=False)
    execution_authority: Literal[False] = field(default=False, init=False)

    @property
    def passed(self) -> bool:
        return not self.failure_codes


def evaluate_governed_latency(
    observations: Sequence[GovernedLatencyObservation],
    event_loop_lag_ms: Sequence[float],
    protocol: GovernedLatencyProtocol | GovernedLatencyProtocolV2 | None = None,
) -> GovernedLatencyReport:
    """Judge complete end-to-end read latency without excluding unavailable observations."""

    protocol = protocol or GovernedLatencyProtocol()
    failures: list[str] = []
    if len(observations) < protocol.min_observations:
        failures.append("observation-count-below-minimum")
    measured = [
        protocol.deadline_ms if item.unavailable_reason is not None else item.latency_ms
        for item in observations
    ] or [protocol.deadline_ms]
    p50, p95, p99 = (nearest_rank(measured, rank) for rank in (50, 95, 99))
    lag = nearest_rank(event_loop_lag_ms or [0.0], 99)
    unavailable = sum(item.unavailable_reason == "provider_unavailable" for item in observations)
    for code, value, limit in (
        ("p50-exceeded", p50, protocol.max_p50_ms),
        ("p95-exceeded", p95, protocol.max_p95_ms),
        ("p99-exceeded", p99, protocol.max_p99_ms),
        ("event-loop-lag-p99-exceeded", lag, protocol.max_event_loop_lag_p99_ms),
    ):
        if value > limit:
            failures.append(code)
    if unavailable > protocol.max_provider_unavailable_rate * max(1, len(observations)):
        failures.append("provider-unavailable-rate-exceeded")
    return GovernedLatencyReport(
        protocol_id=protocol.protocol_id,
        observations=len(observations),
        p50_ms=p50,
        p95_ms=p95,
        p99_ms=p99,
        provider_unavailable=unavailable,
        event_loop_lag_p99_ms=lag,
        failure_codes=tuple(failures),
    )


@dataclass(frozen=True, slots=True)
class GovernedWindowProtocol:
    """Frozen fresh-window thresholds; changing any value requires a new protocol id."""

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
        ) != (
            WINDOW_PROTOCOL_ID,
            WINDOW_CASE_SET,
            64,
            4,
            0.95,
            0.02,
            0.03,
            0.95,
            0.02,
        ):
            raise ValueError("governed answer window protocol v1 parameters are pre-registered")


@dataclass(frozen=True, slots=True)
class GovernedWindowDecision:
    case_id: str
    language: str
    expected: frozenset[str]
    outcome: Literal["returned", "held", "unavailable"]
    selected: frozenset[str]

    @property
    def unavailable(self) -> bool:
        return self.outcome == "unavailable"

    @property
    def wrong(self) -> bool:
        return not self.unavailable and bool(self.selected - self.expected)

    @property
    def correct(self) -> bool:
        return not self.unavailable and self.selected == self.expected


@dataclass(frozen=True, slots=True)
class GovernedWindowLanguage:
    language: str
    decisions: int
    wrong: int
    wrong_upper_bound: float
    answerable: int
    correct: int
    held: int
    unavailable: int

    @property
    def correct_rate(self) -> float:
        return self.correct / self.answerable if self.answerable else 1.0


@dataclass(frozen=True, slots=True)
class GovernedWindowProtocolV2:
    """Fresh Sol-bound window; changing any value requires a new protocol id."""

    protocol_id: str = WINDOW_PROTOCOL_ID_V2
    case_set: str = WINDOW_CASE_SET_V2
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
        ) != (
            WINDOW_PROTOCOL_ID_V2,
            WINDOW_CASE_SET_V2,
            64,
            4,
            0.95,
            0.02,
            0.03,
            0.95,
            0.02,
        ):
            raise ValueError("governed answer window protocol v2 parameters are pre-registered")


@dataclass(frozen=True, slots=True)
class GovernedWindowReport:
    protocol_id: str
    decisions: int
    wrong: int
    wrong_upper_bound: float
    unavailable: int
    languages: tuple[GovernedWindowLanguage, ...]
    failure_codes: tuple[str, ...]
    production_qualification: Literal[False] = field(default=False, init=False)
    execution_authority: Literal[False] = field(default=False, init=False)

    @property
    def passed(self) -> bool:
        return not self.failure_codes


def evaluate_governed_window(
    decisions: Sequence[GovernedWindowDecision],
    protocol: GovernedWindowProtocol | GovernedWindowProtocolV2 | None = None,
) -> GovernedWindowReport:
    """Judge one complete fresh window, including held and unavailable outcomes."""

    protocol = protocol or GovernedWindowProtocol()
    expected_total = protocol.cases * protocol.decisions_per_case
    counts: dict[str, int] = {}
    for item in decisions:
        counts[item.case_id] = counts.get(item.case_id, 0) + 1
    if (
        len(decisions) != expected_total
        or len(counts) != protocol.cases
        or set(counts.values()) != {protocol.decisions_per_case}
    ):
        raise ValueError("governed answer window requires every planned decision exactly once")
    failures: list[str] = []
    wrong = sum(item.wrong for item in decisions)
    pooled = clopper_pearson_upper(wrong, len(decisions), protocol.confidence)
    unavailable = sum(item.unavailable for item in decisions)
    if pooled > protocol.max_pooled_wrong_upper_bound:
        failures.append("pooled-wrong-selection-bound-exceeded")
    if unavailable > protocol.max_unavailable_rate * len(decisions):
        failures.append("unavailable-rate-exceeded")
    languages: list[GovernedWindowLanguage] = []
    for language in sorted({item.language for item in decisions}):
        own = [item for item in decisions if item.language == language]
        own_wrong = sum(item.wrong for item in own)
        answerable = [item for item in own if item.expected]
        result = GovernedWindowLanguage(
            language=language,
            decisions=len(own),
            wrong=own_wrong,
            wrong_upper_bound=clopper_pearson_upper(own_wrong, len(own), protocol.confidence),
            answerable=len(answerable),
            correct=sum(item.correct for item in answerable),
            held=sum(item.outcome == "held" for item in own),
            unavailable=sum(item.unavailable for item in own),
        )
        languages.append(result)
        if result.wrong_upper_bound > protocol.max_language_wrong_upper_bound:
            failures.append(f"{language}-wrong-selection-bound-exceeded")
        if result.correct_rate < protocol.min_language_correct_rate:
            failures.append(f"{language}-correct-rate-below-threshold")
    return GovernedWindowReport(
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
    "LATENCY_PROTOCOL_ID_V2",
    "WINDOW_CASE_SET",
    "WINDOW_CASE_SET_V2",
    "WINDOW_PROTOCOL_ID",
    "WINDOW_PROTOCOL_ID_V2",
    "GovernedLatencyObservation",
    "GovernedLatencyProtocol",
    "GovernedLatencyProtocolV2",
    "GovernedLatencyReport",
    "GovernedWindowDecision",
    "GovernedWindowLanguage",
    "GovernedWindowProtocol",
    "GovernedWindowProtocolV2",
    "GovernedWindowReport",
    "evaluate_governed_latency",
    "evaluate_governed_window",
]
