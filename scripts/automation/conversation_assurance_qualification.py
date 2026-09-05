"""Reduce one complete Pantheon census into replayable operational evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from fdai.core.conversation_assurance import (
    ConversationTurnTraceReceipt,
    PantheonCensus,
    PantheonCensusCase,
    PantheonRubric,
    PantheonTurnDiagnostic,
    T2Expectation,
    t2_expected_outcome,
)

_MIN_OWNER_ROUTING_F1 = 0.98
_MAX_T2_ERROR_RATE = 0.01
_MIN_SCENARIO_SCORE = 27


@dataclass(frozen=True, slots=True)
class PantheonCaseMeasurement:
    """Bind one diagnostic to its authoritative content-free turn trace."""

    diagnostic: PantheonTurnDiagnostic
    trace: ConversationTurnTraceReceipt

    def __post_init__(self) -> None:
        if self.diagnostic.case_id != self.trace.case_id:
            raise ValueError("measurement diagnostic and trace case identities MUST match")
        if self.diagnostic.trace_receipt_digest != self.trace.receipt_digest:
            raise ValueError("measurement diagnostic MUST bind the supplied trace receipt")


@dataclass(frozen=True, slots=True)
class PantheonQualificationEvidence:
    """Content-free evidence for one exact, single-revision census."""

    source_revision: str
    source_content_digest: str
    census_version: str
    census_digest: str
    measurement_set_digest: str
    turns: int
    explicit_target_accuracy: float
    owner_routing_f1: float
    missed_t2_rate: float
    unnecessary_t2_rate: float
    minimum_score: int
    hard_zero_count: int
    suite_locale_floors: tuple[tuple[str, str, int], ...]
    agent_locale_floors: tuple[tuple[str, str, int], ...]
    source_tree_clean: bool
    qualified: bool
    failure_reasons: tuple[str, ...]

    @property
    def evidence_digest(self) -> str:
        canonical = json.dumps(
            self.to_dict(include_digest=False),
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "1.0.0",
            "evidence_kind": "pantheon_conversation_assurance_qualification",
            "source_revision": self.source_revision,
            "source_content_digest": self.source_content_digest,
            "census_version": self.census_version,
            "census_digest": self.census_digest,
            "measurement_set_digest": self.measurement_set_digest,
            "turns": self.turns,
            "metrics": {
                "explicit_target_accuracy": self.explicit_target_accuracy,
                "owner_routing_f1": self.owner_routing_f1,
                "missed_t2_rate": self.missed_t2_rate,
                "unnecessary_t2_rate": self.unnecessary_t2_rate,
                "minimum_score": self.minimum_score,
                "hard_zero_count": self.hard_zero_count,
            },
            "thresholds": {
                "explicit_target_accuracy": 1.0,
                "minimum_owner_routing_f1": _MIN_OWNER_ROUTING_F1,
                "maximum_missed_t2_rate": _MAX_T2_ERROR_RATE,
                "maximum_unnecessary_t2_rate": _MAX_T2_ERROR_RATE,
                "minimum_scenario_score": _MIN_SCENARIO_SCORE,
                "maximum_hard_zero_count": 0,
            },
            "denominators": {
                "explicit_target": 195,
                "owner_routing": 15,
                "required_t2": 12,
                "forbidden_t2": 218,
            },
            "suite_locale_floors": [
                {"suite": suite, "locale": locale, "minimum_score": score}
                for suite, locale, score in self.suite_locale_floors
            ],
            "agent_locale_floors": [
                {"agent": agent, "locale": locale, "minimum_score": score}
                for agent, locale, score in self.agent_locale_floors
            ],
            "source_tree_clean": self.source_tree_clean,
            "qualified": self.qualified,
            "failure_reasons": list(self.failure_reasons),
            "operational_evidence_only": True,
            "qualification_authority": False,
            "execution_authority": False,
        }
        if include_digest:
            payload["evidence_digest"] = self.evidence_digest
        return payload


def qualify_pantheon_series(
    census: PantheonCensus,
    measurements: tuple[PantheonCaseMeasurement, ...],
) -> PantheonQualificationEvidence:
    """Qualify only exact, digest-bound coverage of the installed census."""

    expected = {case.case_id: case for case in census.cases}
    observed = {item.diagnostic.case_id: item for item in measurements}
    if len(observed) != len(measurements) or set(observed) != set(expected):
        raise ValueError("qualification requires exact unique census coverage")
    revisions = {item.trace.source_revision for item in measurements}
    content_digests = {item.trace.source_content_digest for item in measurements}
    receipt_digests = {item.trace.receipt_digest for item in measurements}
    if len(revisions) != 1 or len(content_digests) != 1:
        raise ValueError("qualification requires one source identity")
    if len(receipt_digests) != len(measurements):
        raise ValueError("qualification requires unique trace receipts")

    ordered = tuple(observed[case.case_id] for case in census.cases)
    for case, item in zip(census.cases, ordered, strict=True):
        trace = item.trace
        diagnostic = item.diagnostic
        if (
            trace.expected_primary_agent != case.expected_primary_agent
            or trace.locale != case.locale
            or trace.terminal_status != "completed"
            or trace.hard_zero_violations != diagnostic.hard_zero_violations
            or diagnostic.agent != (trace.actual_primary_agent or trace.expected_primary_agent)
            or diagnostic.locale != case.locale
            or diagnostic.t2_expectation is not case.t2_expectation
            or not _trace_results_match(case, item)
        ):
            raise ValueError("qualification measurement does not match the installed census")

    explicit = tuple(
        item.trace.actual_primary_agent == case.expected_primary_agent
        for case, item in zip(census.cases, ordered, strict=True)
        if case.expected_routing_method == "explicit"
    )
    owner_pairs = tuple(
        (case.expected_primary_agent, item.trace.actual_primary_agent)
        for case, item in zip(census.cases, ordered, strict=True)
        if case.expected_routing_method == "semantic_judgment"
    )
    required_t2 = tuple(
        _item_passed(item, 27)
        for case, item in zip(census.cases, ordered, strict=True)
        if case.t2_expectation is T2Expectation.REQUIRED
    )
    forbidden_t2 = tuple(
        _item_passed(item, 26)
        for case, item in zip(census.cases, ordered, strict=True)
        if case.t2_expectation is T2Expectation.FORBIDDEN
    )
    if (len(explicit), len(owner_pairs), len(required_t2), len(forbidden_t2)) != (
        195,
        15,
        12,
        218,
    ):
        raise ValueError("qualification census denominators are inconsistent")

    explicit_accuracy = _rate(explicit)
    owner_f1 = _macro_f1(owner_pairs)
    missed_t2_rate = 1.0 - _rate(required_t2)
    unnecessary_t2_rate = 1.0 - _rate(forbidden_t2)
    minimum_score = min(item.diagnostic.score for item in ordered)
    hard_zero_count = sum(bool(item.diagnostic.hard_zero_violations) for item in ordered)
    revision = next(iter(revisions))
    source_content_digest = next(iter(content_digests))
    clean_content_digest = hashlib.sha256(f"{revision}\n".encode()).hexdigest()
    source_tree_clean = source_content_digest == clean_content_digest
    reasons: list[str] = []
    if not source_tree_clean:
        reasons.append("source_tree_not_clean")
    if explicit_accuracy < 1.0:
        reasons.append("explicit_target_accuracy_below_threshold")
    if owner_f1 < _MIN_OWNER_ROUTING_F1:
        reasons.append("owner_routing_f1_below_threshold")
    if missed_t2_rate > _MAX_T2_ERROR_RATE:
        reasons.append("missed_t2_rate_above_threshold")
    if unnecessary_t2_rate > _MAX_T2_ERROR_RATE:
        reasons.append("unnecessary_t2_rate_above_threshold")
    if minimum_score < _MIN_SCENARIO_SCORE:
        reasons.append("scenario_score_below_threshold")
    if hard_zero_count:
        reasons.append("hard_zero_violation")

    return PantheonQualificationEvidence(
        source_revision=revision,
        source_content_digest=source_content_digest,
        census_version=census.version,
        census_digest=census.content_digest,
        measurement_set_digest=_measurement_set_digest(ordered),
        turns=len(ordered),
        explicit_target_accuracy=explicit_accuracy,
        owner_routing_f1=owner_f1,
        missed_t2_rate=missed_t2_rate,
        unnecessary_t2_rate=unnecessary_t2_rate,
        minimum_score=minimum_score,
        hard_zero_count=hard_zero_count,
        suite_locale_floors=_floors(census, ordered, "suite"),
        agent_locale_floors=_floors(census, ordered, "agent"),
        source_tree_clean=source_tree_clean,
        qualified=not reasons,
        failure_reasons=tuple(reasons),
    )


def _item_passed(measurement: PantheonCaseMeasurement, item_id: int) -> bool:
    return measurement.diagnostic.results[item_id - 1].passed


def _trace_results_match(
    case: PantheonCensusCase,
    measurement: PantheonCaseMeasurement,
) -> bool:
    trace = measurement.trace
    required = case.t2_expectation is T2Expectation.REQUIRED
    forbidden = case.t2_expectation is T2Expectation.FORBIDDEN
    expected = (
        trace.actual_primary_agent == case.expected_primary_agent,
        trace.routing_method == case.expected_routing_method,
        (
            trace.semantic_score is None
            if case.expected_routing_method == "explicit"
            else trace.semantic_score is not None
            and trace.semantic_margin is not None
            and trace.semantic_score >= 0.0
            and trace.semantic_margin >= 0.0
        ),
        len(trace.contributors) <= 2
        and set(trace.contributors).issubset(case.allowed_contributors),
        (
            trace.handoff_owner == case.expected_handoff_owner
            if case.expected_handoff
            else trace.handoff_owner is None
        ),
        not forbidden or not trace.t2_attempted,
        not required or trace.t2_required,
        (
            not trace.t2_attempted
            or (
                trace.budget_reserved
                and trace.metering_receipt_digest is not None
                and trace.t2_model_family is not None
            )
        ),
        trace.t2_status == "completed" or trace.t1_conclusion_preserved,
        trace.latency_ms <= trace.latency_budget_ms and trace.terminal_status == "completed",
    )
    item_ids = (1, 2, 3, 4, 5, 26, 27, 28, 29, 30)
    rubrics = tuple(PantheonRubric)
    expected_t2_outcome = t2_expected_outcome(case.case_id)
    return (
        expected_t2_outcome is None or expected_t2_outcome == (trace.t1_reason, trace.t2_status)
    ) and all(
        measurement.diagnostic.results[item_id - 1].rubric is rubrics[item_id - 1]
        and measurement.diagnostic.results[item_id - 1].passed is passed
        for item_id, passed in zip(item_ids, expected, strict=True)
    )


def _measurement_set_digest(
    measurements: tuple[PantheonCaseMeasurement, ...],
) -> str:
    payload = [
        {
            "case_id": item.diagnostic.case_id,
            "trace_receipt_digest": item.trace.receipt_digest,
            "diagnostic_digest": item.diagnostic.content_digest,
        }
        for item in measurements
    ]
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _rate(values: tuple[bool, ...]) -> float:
    return sum(values) / len(values)


def _macro_f1(pairs: tuple[tuple[str, str | None], ...]) -> float:
    labels = sorted({expected for expected, _ in pairs})
    scores: list[float] = []
    for label in labels:
        true_positive = sum(expected == actual == label for expected, actual in pairs)
        false_positive = sum(expected != label and actual == label for expected, actual in pairs)
        false_negative = sum(expected == label and actual != label for expected, actual in pairs)
        denominator = 2 * true_positive + false_positive + false_negative
        scores.append(0.0 if denominator == 0 else 2 * true_positive / denominator)
    return round(sum(scores) / len(scores), 6)


def _floors(
    census: PantheonCensus,
    measurements: tuple[PantheonCaseMeasurement, ...],
    dimension: str,
) -> tuple[tuple[str, str, int], ...]:
    grouped: dict[tuple[str, str], list[int]] = {}
    for case, item in zip(census.cases, measurements, strict=True):
        key = case.suite if dimension == "suite" else case.expected_primary_agent
        grouped.setdefault((key, case.locale), []).append(item.diagnostic.score)
    return tuple((key, locale, min(scores)) for (key, locale), scores in sorted(grouped.items()))


__all__ = [
    "PantheonCaseMeasurement",
    "PantheonQualificationEvidence",
    "qualify_pantheon_series",
]
