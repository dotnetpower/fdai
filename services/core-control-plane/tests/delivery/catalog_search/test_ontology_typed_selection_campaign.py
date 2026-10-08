"""Pre-registered runtime protocols: frozen thresholds, no exclusions, complete accounting."""

import pytest
from fdai.delivery.catalog_search.ontology_typed_selection_campaign import (
    ForegroundPair,
    LatencyProtocol,
    ObservationLatency,
    WindowDecision,
    WindowProtocol,
    evaluate_latency,
    evaluate_window,
    nearest_rank,
)


def _fast(count: int = 256) -> list[ObservationLatency]:
    return [ObservationLatency(3_000.0, None) for _ in range(count)]


def _foreground(contended: float = 2.0) -> list[ForegroundPair]:
    return [ForegroundPair(1.0, contended, True) for _ in range(256)]


def test_nearest_rank_uses_the_ceiling_rank() -> None:
    assert nearest_rank([1, 2, 3, 4], 50) == 2
    assert nearest_rank([1, 2, 3, 4], 95) == 4
    with pytest.raises(ValueError):
        nearest_rank([], 50)


def test_latency_passes_only_within_every_frozen_bound() -> None:
    report = evaluate_latency(
        observations=_fast(), foreground=_foreground(), event_loop_lag_ms=[5.0] * 10
    )
    assert report.passed
    assert report.execution_authority is False
    assert report.production_qualification is False


def test_unavailable_observations_count_at_the_deadline_and_against_the_rate() -> None:
    observations = _fast(250) + [ObservationLatency(1.0, "deadline_exceeded")] * 6
    report = evaluate_latency(
        observations=observations, foreground=_foreground(), event_loop_lag_ms=[5.0]
    )
    assert report.provider_unavailable == 6
    assert report.gated_p99_ms == 30_000.0
    assert set(report.failure_codes) == {"gated-p99-exceeded", "provider-unavailable-rate-exceeded"}


def test_foreground_regression_and_changed_outcome_fail() -> None:
    foreground = _foreground(contended=80.0)
    foreground[0] = ForegroundPair(1.0, 1.0, False)
    report = evaluate_latency(
        observations=_fast(), foreground=foreground, event_loop_lag_ms=[150.0]
    )
    assert set(report.failure_codes) == {
        "foreground-p95-regression-exceeded",
        "foreground-outcome-changed",
        "event-loop-lag-p99-exceeded",
    }


def test_short_campaign_cannot_pass() -> None:
    report = evaluate_latency(
        observations=_fast(10), foreground=_foreground(), event_loop_lag_ms=[1.0]
    )
    assert "observation-count-below-minimum" in report.failure_codes


def _decisions(
    *, wrong: int = 0, unavailable: int = 0, clarify_answerable: int = 0
) -> list[WindowDecision]:
    decisions: list[WindowDecision] = []
    for index in range(64):
        language = "en" if index < 32 else "ko"
        expected = frozenset({f"object:Resource:r{index}"}) if index % 2 == 0 else frozenset()
        for _repeat in range(4):
            decisions.append(
                WindowDecision(
                    f"case-{index}",
                    language,
                    expected,
                    "selected" if expected else "empty",
                    expected,
                )
            )
    for position in range(wrong):
        item = decisions[position * 8]
        decisions[position * 8] = WindowDecision(
            item.case_id, item.language, item.expected, "selected", frozenset({"object:X:y"})
        )
    for position in range(unavailable):
        item = decisions[position * 8 + 1]
        decisions[position * 8 + 1] = WindowDecision(
            item.case_id, item.language, item.expected, "unavailable", frozenset()
        )
    for position in range(clarify_answerable):
        item = decisions[position * 8 + 2]
        decisions[position * 8 + 2] = WindowDecision(
            item.case_id, item.language, item.expected, "disagreed", frozenset()
        )
    return decisions


def test_window_with_zero_wrong_meets_the_per_language_bound() -> None:
    report = evaluate_window(_decisions())
    assert report.passed
    assert [(item.language, item.decisions, item.correct_rate) for item in report.languages] == [
        ("en", 128, 1.0),
        ("ko", 128, 1.0),
    ]


def test_one_wrong_selection_in_a_language_fails_its_bound() -> None:
    report = evaluate_window(_decisions(wrong=1))
    assert "en-wrong-selection-bound-exceeded" in report.failure_codes


def test_unavailable_answerable_decisions_lower_correct_rate() -> None:
    report = evaluate_window(_decisions(unavailable=6))
    assert "unavailable-rate-exceeded" in report.failure_codes
    assert report.unavailable == 6
    assert report.wrong == 0


def test_disagreement_is_safe_but_lowers_correct_rate() -> None:
    report = evaluate_window(_decisions(clarify_answerable=4))
    assert report.wrong == 0
    assert report.languages[0].disagreed == 4
    assert report.languages[0].correct_rate == 60 / 64
    assert "en-correct-rate-below-threshold" in report.failure_codes


def test_window_requires_complete_planned_accounting() -> None:
    with pytest.raises(ValueError, match="every planned decision"):
        evaluate_window(_decisions()[:-1])


def test_protocol_parameters_are_frozen() -> None:
    with pytest.raises(ValueError, match="pre-registered"):
        WindowProtocol(decisions_per_case=3)
    with pytest.raises(ValueError, match="pre-registered"):
        LatencyProtocol(max_gated_p95_ms=20_000.0)
