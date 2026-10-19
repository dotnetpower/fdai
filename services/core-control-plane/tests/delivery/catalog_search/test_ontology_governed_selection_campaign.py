"""Frozen protocol arithmetic for governed typed-selection answer qualification."""

from fdai.delivery.catalog_search.ontology_governed_selection_campaign import (
    GovernedLatencyObservation,
    GovernedLatencyProtocol,
    GovernedLatencyProtocolV2,
    GovernedWindowDecision,
    GovernedWindowProtocol,
    GovernedWindowProtocolV2,
    evaluate_governed_latency,
    evaluate_governed_window,
)


def _decisions(*, wrong: int = 0, unavailable: int = 0):
    rows = []
    for _repeat in range(4):
        for language in ("en", "ko"):
            for index in range(1, 33):
                expected = (
                    frozenset({f"object:Resource:{language}-{index}"})
                    if index <= 16
                    else frozenset()
                )
                selected = expected
                outcome = "returned" if expected else "held"
                if len(rows) < wrong:
                    selected = frozenset({"object:Resource:wrong"})
                    outcome = "returned"
                elif len(rows) < wrong + unavailable:
                    selected = frozenset()
                    outcome = "unavailable"
                rows.append(
                    GovernedWindowDecision(
                        case_id=f"governed1-{language}-{index:02d}",
                        language=language,
                        expected=expected,
                        outcome=outcome,
                        selected=selected,
                    )
                )
    return rows


def test_governed_protocol_identity_and_clean_window_pass() -> None:
    assert GovernedLatencyProtocol().min_observations == 256
    assert GovernedWindowProtocol().decisions_per_case == 4
    assert GovernedLatencyProtocolV2().protocol_id.endswith(".v2")
    assert GovernedWindowProtocolV2().case_set == "governed-read-window.v2.json"
    latency = evaluate_governed_latency(
        [GovernedLatencyObservation(2_000.0, None) for _ in range(256)],
        [1.0],
    )
    window = evaluate_governed_window(_decisions())
    assert latency.passed
    assert window.passed
    assert all(item.correct_rate == 1.0 for item in window.languages)
    assert all(item.held == 64 for item in window.languages)


def test_governed_protocol_fails_wrong_and_unavailable_bounds() -> None:
    latency = evaluate_governed_latency(
        [GovernedLatencyObservation(2_000.0, "provider_unavailable") for _ in range(6)]
        + [GovernedLatencyObservation(2_000.0, None) for _ in range(250)],
        [1.0],
    )
    window = evaluate_governed_window(_decisions(wrong=3, unavailable=6))
    assert "provider-unavailable-rate-exceeded" in latency.failure_codes
    assert "pooled-wrong-selection-bound-exceeded" in window.failure_codes
    assert "unavailable-rate-exceeded" in window.failure_codes
