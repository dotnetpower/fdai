"""Tests for the optional Norns scenario-coverage learner seam."""

from __future__ import annotations

import pathlib

import pytest

from fdai.agents.norns import Norns
from fdai.core.chaos.coverage import ScenarioCoverageAggregator
from fdai.core.chaos.scenario_catalog import CatalogEntry
from fdai.core.chaos.symptom_index import build_from_entries


def _entry(scenario_id: str, signal: str, target: str = "pod") -> CatalogEntry:
    spec = {
        "id": scenario_id,
        "version": 1,
        "provenance": {"source": "synthesized", "synthesis_method": "deterministic"},
        "category": "compute",
        "target_type": target,
        "fault_family": "stop",
        "intensity": "mild",
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


def test_observe_incident_symptom_is_no_op_without_aggregator() -> None:
    """Default construction (no aggregator wired) => the method exists but
    does not fill pending_candidates. Non-breaking for existing forks."""
    norns = Norns()
    for i in range(10):
        norns.observe_incident_symptom(
            incident_id=f"i-{i}",
            signal="some_signal",
            target_type="pod",
            severity="low",
        )
    assert norns.pending_candidates == []


def test_observe_incident_symptom_emits_scenario_coverage_gap_candidate() -> None:
    """With an aggregator wired, uncovered symptoms cross the threshold
    and produce a scenario-coverage-gap candidate onto pending_candidates."""
    empty_index = build_from_entries([])
    agg = ScenarioCoverageAggregator(index=empty_index, gap_threshold=3)
    norns = Norns(coverage_aggregator=agg)
    for i in range(3):
        norns.observe_incident_symptom(
            incident_id=f"inc-{i}",
            signal="brand_new_signal",
            target_type="pod",
            severity="medium",
        )
    assert len(norns.pending_candidates) == 1
    c = norns.pending_candidates[0]
    assert c["source_signal"] == "scenario_coverage_gap"
    assert c["proposed_by"] == "Norns"
    assert c["proposal_kind"] == "new-scenario"
    assert c["candidate_type"] == "scenario-coverage-gap"
    assert c["evidence"] == {
        "signal": "brand_new_signal",
        "target_type": "pod",
        "severity": "medium",
    }
    assert c["provenance"]["source"] == "internal-incident"
    assert c["provenance"]["synthesis_method"] == "distilled"
    assert c["provenance"]["sample_incidents"] == ["inc-0", "inc-1", "inc-2"]
    assert c["proposed_scenario_id"] == "chaos.coverage-gap.brand-new-signal-on-pod"


def test_covered_symptom_never_produces_a_candidate() -> None:
    """A symptom that the catalog already covers must NOT produce a
    coverage-gap candidate no matter how many times it fires."""
    idx = build_from_entries([_entry("chaos.a.p", "pod_restart", "pod")])
    agg = ScenarioCoverageAggregator(index=idx, gap_threshold=2)
    norns = Norns(coverage_aggregator=agg)
    for i in range(10):
        norns.observe_incident_symptom(
            incident_id=f"inc-{i}",
            signal="pod_restart",
            target_type="pod",
            severity="low",
        )
    assert norns.pending_candidates == []


def test_coverage_learner_does_not_interfere_with_fingerprint_learner() -> None:
    """The two learners share pending_candidates; both must produce their
    own candidate without cross-contamination."""
    agg = ScenarioCoverageAggregator(index=build_from_entries([]), gap_threshold=2)
    norns = Norns(promotion_threshold=2, coverage_aggregator=agg)
    # Fingerprint stream drives the fingerprint learner.
    for _ in range(2):
        norns._observe_fingerprint({"fingerprint": "fp-1"})
    # Coverage stream drives the coverage learner.
    for i in range(2):
        norns.observe_incident_symptom(
            incident_id=f"cov-{i}",
            signal="new_signal",
            target_type="pod",
            severity="low",
        )
    kinds = {c.get("source_signal") for c in norns.pending_candidates}
    assert kinds == {"handoff_fingerprint", "scenario_coverage_gap"}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"incident_id": "", "signal": "sig", "target_type": "pod", "severity": "low"},
        {"incident_id": "i-0", "signal": "", "target_type": "pod", "severity": "low"},
    ],
)
def test_coverage_learner_input_validation_bubbles_up(kwargs: dict) -> None:
    """The aggregator's input validation surfaces through Norns."""
    agg = ScenarioCoverageAggregator(index=build_from_entries([]), gap_threshold=1)
    norns = Norns(coverage_aggregator=agg)
    with pytest.raises(ValueError):
        norns.observe_incident_symptom(**kwargs)
