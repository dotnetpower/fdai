"""Aggregate evaluated Pantheon diagnostics without counting held observations."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.core.conversation_assurance.pantheon_scorecard import (
    PantheonDiagnosticVerdict,
    PantheonTurnDiagnostic,
)


@dataclass(frozen=True, slots=True)
class AgentDiagnosticSummary:
    agent: str
    turns: int
    average_score: float
    minimum_score: int
    pass_count: int
    review_count: int
    fail_count: int
    hard_zero_count: int


@dataclass(frozen=True, slots=True)
class PantheonDiagnosticSummary:
    turns: int
    pass_count: int
    review_count: int
    fail_count: int
    hard_zero_count: int
    explicit_target_accuracy: float | None
    owner_routing_f1: float | None
    missed_t2_rate: float | None
    unnecessary_t2_rate: float | None
    agents: tuple[AgentDiagnosticSummary, ...]


def aggregate_pantheon_diagnostics(
    diagnostics: tuple[PantheonTurnDiagnostic, ...],
    *,
    explicit_route_results: tuple[bool, ...] = (),
    owner_route_pairs: tuple[tuple[str, str], ...] = (),
    required_t2_results: tuple[bool, ...] = (),
    forbidden_t2_results: tuple[bool, ...] = (),
) -> PantheonDiagnosticSummary:
    """Reduce evaluated rows only; unavailable or held turns never enter the input."""

    grouped: dict[str, list[PantheonTurnDiagnostic]] = {}
    for item in diagnostics:
        grouped.setdefault(item.agent, []).append(item)
    agents = tuple(_agent_summary(agent, tuple(rows)) for agent, rows in sorted(grouped.items()))
    return PantheonDiagnosticSummary(
        turns=len(diagnostics),
        pass_count=_count(diagnostics, PantheonDiagnosticVerdict.PASS),
        review_count=_count(diagnostics, PantheonDiagnosticVerdict.REVIEW),
        fail_count=_count(diagnostics, PantheonDiagnosticVerdict.FAIL),
        hard_zero_count=_count(diagnostics, PantheonDiagnosticVerdict.HARD_ZERO_FAIL),
        explicit_target_accuracy=_rate(explicit_route_results),
        owner_routing_f1=_macro_f1(owner_route_pairs),
        missed_t2_rate=_failure_rate(required_t2_results),
        unnecessary_t2_rate=_failure_rate(forbidden_t2_results),
        agents=agents,
    )


def _agent_summary(
    agent: str,
    rows: tuple[PantheonTurnDiagnostic, ...],
) -> AgentDiagnosticSummary:
    return AgentDiagnosticSummary(
        agent=agent,
        turns=len(rows),
        average_score=round(sum(item.score for item in rows) / len(rows), 4),
        minimum_score=min(item.score for item in rows),
        pass_count=_count(rows, PantheonDiagnosticVerdict.PASS),
        review_count=_count(rows, PantheonDiagnosticVerdict.REVIEW),
        fail_count=_count(rows, PantheonDiagnosticVerdict.FAIL),
        hard_zero_count=_count(rows, PantheonDiagnosticVerdict.HARD_ZERO_FAIL),
    )


def _count(
    rows: tuple[PantheonTurnDiagnostic, ...],
    verdict: PantheonDiagnosticVerdict,
) -> int:
    return sum(item.verdict is verdict for item in rows)


def _rate(values: tuple[bool, ...]) -> float | None:
    return None if not values else sum(values) / len(values)


def _failure_rate(values: tuple[bool, ...]) -> float | None:
    rate = _rate(values)
    return None if rate is None else 1.0 - rate


def _macro_f1(pairs: tuple[tuple[str, str], ...]) -> float | None:
    if not pairs:
        return None
    labels = sorted({value for pair in pairs for value in pair})
    scores: list[float] = []
    for label in labels:
        true_positive = sum(expected == actual == label for expected, actual in pairs)
        false_positive = sum(expected != label and actual == label for expected, actual in pairs)
        false_negative = sum(expected == label and actual != label for expected, actual in pairs)
        denominator = 2 * true_positive + false_positive + false_negative
        scores.append(0.0 if denominator == 0 else 2 * true_positive / denominator)
    return round(sum(scores) / len(scores), 6)


__all__ = [
    "AgentDiagnosticSummary",
    "PantheonDiagnosticSummary",
    "aggregate_pantheon_diagnostics",
]
