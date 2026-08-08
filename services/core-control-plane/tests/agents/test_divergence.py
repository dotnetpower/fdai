"""Unit tests for the shadow-vs-authoritative divergence ledger."""

from __future__ import annotations

from fdai.agents._framework.divergence import ShadowDivergenceLedger


def test_matched_pair_counts_as_agreement() -> None:
    led = ShadowDivergenceLedger()
    led.record_pantheon("c1", "auto")
    led.record_authoritative("c1", "auto")
    report = led.report()
    assert report["matched"] == 1
    assert report["diverged"] == 0
    assert report["agreement_rate"] == 1.0
    assert report["pending"] == 0
    assert report["pantheon_total"] == 1
    assert report["authoritative_total"] == 1


def test_diverged_pair_records_directional_breakdown() -> None:
    led = ShadowDivergenceLedger()
    led.record_authoritative("c2", "hil")
    led.record_pantheon("c2", "auto")
    report = led.report()
    assert report["matched"] == 0
    assert report["diverged"] == 1
    assert report["agreement_rate"] == 0.0
    # authoritative -> pantheon: "P1 said hil, shadow would have auto".
    assert report["breakdown"] == {"hil->auto": 1}


def test_single_side_stays_pending() -> None:
    led = ShadowDivergenceLedger()
    led.record_pantheon("c1", "auto")
    report = led.report()
    assert report["pending"] == 1
    assert report["matched"] == 0
    assert report["agreement_rate"] is None


def test_pending_map_is_lru_bounded() -> None:
    led = ShadowDivergenceLedger(max_pending=2)
    led.record_pantheon("a", "auto")
    led.record_pantheon("b", "auto")
    led.record_pantheon("c", "auto")  # evicts oldest ("a")
    report = led.report()
    assert report["pending"] == 2
    assert report["evicted"] == 1


def test_empty_correlation_id_is_not_tracked() -> None:
    led = ShadowDivergenceLedger()
    led.record_pantheon("", "auto")
    report = led.report()
    assert report["pending"] == 0
    assert report["pantheon_total"] == 1  # counted as seen, not joined


def test_same_side_redelivery_updates_pending_decision() -> None:
    led = ShadowDivergenceLedger()
    led.record_pantheon("c", "auto")
    led.record_pantheon("c", "hil")  # re-delivery overwrites
    led.record_authoritative("c", "hil")
    report = led.report()
    assert report["matched"] == 1
    assert report["diverged"] == 0


def test_agreement_rate_none_when_nothing_resolved() -> None:
    assert ShadowDivergenceLedger().report()["agreement_rate"] is None
