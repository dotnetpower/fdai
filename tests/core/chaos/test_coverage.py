"""Tests for the scenario-coverage learner (Norns extension seam)."""

from __future__ import annotations

import pathlib

import pytest

from fdai.core.chaos.coverage import ScenarioCoverageAggregator
from fdai.core.chaos.scenario_catalog import CatalogEntry
from fdai.core.chaos.symptom_index import build_from_entries


def _entry(
    scenario_id: str,
    signal: str,
    target: str = "pod",
    intensity: str = "mild",
) -> CatalogEntry:
    spec = {
        "id": scenario_id,
        "version": 1,
        "provenance": {"source": "synthesized", "synthesis_method": "deterministic"},
        "category": "compute",
        "target_type": target,
        "fault_family": "stop",
        "intensity": intensity,
        "duration_seconds": 360,
        "expected_signal": signal,
        "injector": "chaos-mesh:PodChaos",
        "blast_radius_cap": 1,
        "rollback_note": "n/a",
        "gates": {"shadow_status": "pending", "enforce_status": None},
        "requires_hardware": False,
        "gpu_domain": None,
    }
    return CatalogEntry(
        id=scenario_id,
        source_path=pathlib.Path("/tmp/x.yaml"),  # noqa: S108 - synthetic marker, never opened
        spec=spec,
    )


def _empty_index():
    return build_from_entries([])


def test_covered_symptom_yields_no_proposal() -> None:
    idx = build_from_entries([_entry("chaos.a.p", "pod_restart", "pod", "mild")])
    agg = ScenarioCoverageAggregator(index=idx, gap_threshold=2)
    for i in range(5):
        agg.observe(
            incident_id=f"i-{i}",
            signal="pod_restart",
            target_type="pod",
            severity="low",
        )
    assert agg.drain_proposals() == []
    assert agg.uncovered_symptom_count() == 0


def test_dedup_survives_sample_cap_smaller_than_threshold() -> None:
    # sample_incidents_cap < gap_threshold: the display buffer evicts old ids,
    # but distinct-incident dedup must still hold, so re-observing the same two
    # incidents can never cross a threshold of 3 (regression for the shared
    # deque that once served both display and dedup).
    agg = ScenarioCoverageAggregator(
        index=_empty_index(), gap_threshold=3, sample_incidents_cap=1
    )
    for _ in range(10):
        agg.observe(incident_id="inc-a", signal="s", target_type="pod", severity="high")
        agg.observe(incident_id="inc-b", signal="s", target_type="pod", severity="high")
    assert agg.drain_proposals() == []  # only 2 distinct incidents, below 3
    agg.observe(incident_id="inc-c", signal="s", target_type="pod", severity="high")
    assert len(agg.drain_proposals()) == 1  # third DISTINCT incident crosses


def test_uncovered_symptom_emits_after_threshold() -> None:
    agg = ScenarioCoverageAggregator(index=_empty_index(), gap_threshold=3)
    for i in range(2):
        agg.observe(
            incident_id=f"i-{i}",
            signal="brand_new_signal",
            target_type="pod",
            severity="medium",
        )
    assert agg.drain_proposals() == [], "not yet at threshold"
    agg.observe(
        incident_id="i-2",
        signal="brand_new_signal",
        target_type="pod",
        severity="medium",
    )
    proposals = agg.drain_proposals()
    assert len(proposals) == 1
    p = proposals[0]
    assert p["candidate_type"] == "scenario-coverage-gap"
    assert p["target_symptom"] == {
        "signal": "brand_new_signal",
        "target_type": "pod",
        "severity": "medium",
    }
    assert p["proposed_scenario_id"] == "chaos.coverage-gap.brand-new-signal-on-pod"
    assert p["provenance"]["source"] == "internal-incident"
    assert p["provenance"]["synthesis_method"] == "distilled"
    assert p["provenance"]["sample_incidents"] == ["i-0", "i-1", "i-2"]
    assert p["provenance"]["observed_count"] == 3


def test_duplicate_incident_ids_do_not_double_count() -> None:
    agg = ScenarioCoverageAggregator(index=_empty_index(), gap_threshold=3)
    for _ in range(5):
        agg.observe(
            incident_id="i-dup",
            signal="sig",
            target_type="pod",
            severity="low",
        )
    assert agg.drain_proposals() == []


def test_key_does_not_re_propose_after_threshold() -> None:
    agg = ScenarioCoverageAggregator(index=_empty_index(), gap_threshold=2)
    for i in range(2):
        agg.observe(
            incident_id=f"i-{i}",
            signal="sig",
            target_type="pod",
            severity="low",
        )
    first = agg.drain_proposals()
    assert len(first) == 1
    # Ten more incidents on the same key: no additional proposal.
    for i in range(2, 12):
        agg.observe(
            incident_id=f"i-{i}",
            signal="sig",
            target_type="pod",
            severity="low",
        )
    assert agg.drain_proposals() == []
    assert agg.proposed_count() == 1


def test_rebind_index_clears_proposed_memo() -> None:
    agg = ScenarioCoverageAggregator(index=_empty_index(), gap_threshold=2)
    for i in range(2):
        agg.observe(
            incident_id=f"i-{i}",
            signal="sig",
            target_type="pod",
            severity="low",
        )
    agg.drain_proposals()
    assert agg.proposed_count() == 1
    # A fresh index rebinds: proposed memo cleared. If a new merge did
    # NOT cover the symptom the aggregator sees new incidents as gap
    # candidates again.
    agg.rebind_index(_empty_index())
    assert agg.proposed_count() == 0


def test_sample_incidents_capped() -> None:
    agg = ScenarioCoverageAggregator(index=_empty_index(), gap_threshold=10, sample_incidents_cap=3)
    for i in range(10):
        agg.observe(
            incident_id=f"i-{i}",
            signal="sig",
            target_type="pod",
            severity="low",
        )
    p = agg.drain_proposals()[0]
    # deque(maxlen=3) keeps the last 3 unique ids that landed inside the
    # buffer at emission time.
    assert len(p["provenance"]["sample_incidents"]) == 3
    assert p["provenance"]["sample_incidents"] == ["i-7", "i-8", "i-9"]


def test_empty_target_type_becomes_unspecified_slug() -> None:
    agg = ScenarioCoverageAggregator(index=_empty_index(), gap_threshold=1)
    agg.observe(incident_id="i-0", signal="sig", target_type="", severity="low")
    p = agg.drain_proposals()[0]
    assert p["proposed_scenario_id"] == "chaos.coverage-gap.sig-on-unspecified"


def test_zero_thresholds_are_rejected() -> None:
    with pytest.raises(ValueError, match="gap_threshold MUST be >= 1"):
        ScenarioCoverageAggregator(index=_empty_index(), gap_threshold=0)
    with pytest.raises(ValueError, match="sample_incidents_cap MUST be >= 1"):
        ScenarioCoverageAggregator(index=_empty_index(), gap_threshold=1, sample_incidents_cap=0)


def test_empty_inputs_are_rejected() -> None:
    agg = ScenarioCoverageAggregator(index=_empty_index(), gap_threshold=1)
    with pytest.raises(ValueError, match="incident_id"):
        agg.observe(incident_id="", signal="sig", target_type="pod", severity="low")
    with pytest.raises(ValueError, match="signal"):
        agg.observe(incident_id="i", signal="", target_type="pod", severity="low")


def test_uncovered_symptom_count_reflects_pending() -> None:
    agg = ScenarioCoverageAggregator(index=_empty_index(), gap_threshold=5)
    agg.observe(incident_id="a", signal="s1", target_type="pod", severity="low")
    agg.observe(incident_id="b", signal="s2", target_type="pod", severity="low")
    assert agg.uncovered_symptom_count() == 2
