"""Tests for the RCA scenario-context helper."""

from __future__ import annotations

import pathlib

import pytest

from fdai.core.chaos.scenario_catalog import CatalogEntry
from fdai.core.chaos.symptom_index import build_from_entries
from fdai.core.rca.contract import Citation, CitationKind
from fdai.core.rca.scenario_context import candidate_scenarios, scenario_summary


def _entry(
    scenario_id: str,
    signal: str,
    target: str = "pod",
    intensity: str = "mild",
    injector: str = "chaos-mesh:PodChaos",
    category: str = "compute",
    gpu_domain: str | None = None,
    requires_hw: bool = False,
) -> CatalogEntry:
    spec = {
        "id": scenario_id,
        "version": 1,
        "provenance": {"source": "synthesized", "synthesis_method": "deterministic"},
        "category": category,
        "target_type": target,
        "fault_family": "stop",
        "intensity": intensity,
        "duration_seconds": 360,
        "expected_signal": signal,
        "injector": injector,
        "blast_radius_cap": 1,
        "rollback_note": "n/a",
        "gates": {"shadow_status": "pending", "enforce_status": None},
        "requires_hardware": requires_hw,
        "gpu_domain": gpu_domain,
    }
    return CatalogEntry(
        id=scenario_id,
        source_path=pathlib.Path("/tmp/x.yaml"),  # noqa: S108 - synthetic marker, never opened
        spec=spec,
    )


def test_candidate_scenarios_returns_scenario_citations() -> None:
    idx = build_from_entries(
        [
            _entry("chaos.a.pod-kill-mild", "pod_restart", "pod", "mild"),
            _entry("chaos.a.pod-kill-high", "pod_restart", "pod", "high"),
        ]
    )
    got = candidate_scenarios(idx, signal="pod_restart", target_type="pod", severity="low")
    assert all(c.kind == CitationKind.SCENARIO for c in got)
    assert {c.ref for c in got} == {"chaos.a.pod-kill-mild"}


def test_candidate_scenarios_widens_when_exact_bucket_is_empty() -> None:
    idx = build_from_entries(
        [
            _entry("chaos.a.pod-kill-mild", "pod_restart", "pod", "mild"),
            _entry("chaos.a.pod-kill-high", "pod_restart", "pod", "high"),
        ]
    )
    # No extreme-severity match - widen path should return both.
    got = candidate_scenarios(idx, signal="pod_restart", target_type="pod", severity="high")
    assert {c.ref for c in got} == {"chaos.a.pod-kill-mild", "chaos.a.pod-kill-high"}


def test_candidate_scenarios_respects_max_candidates() -> None:
    entries = [
        _entry(f"chaos.a.p-{i}", "pod_restart", "pod", "mild") for i in range(20)
    ]
    idx = build_from_entries(entries)
    got = candidate_scenarios(
        idx, signal="pod_restart", target_type="pod", severity="low", max_candidates=5
    )
    assert len(got) == 5
    # Deterministic slice: sorted-by-id then truncated.
    assert [c.ref for c in got] == [f"chaos.a.p-{i}" for i in [0, 1, 10, 11, 12]]


def test_needs_injector_filter() -> None:
    idx = build_from_entries(
        [
            _entry("chaos.a.wired", "pod_restart", "pod", "mild", injector="chaos-mesh:PodChaos"),
            _entry("chaos.a.pending", "pod_restart", "pod", "mild", injector="needs-injector"),
        ]
    )
    with_all = candidate_scenarios(idx, signal="pod_restart", target_type="pod", severity="low")
    assert {c.ref for c in with_all} == {"chaos.a.wired", "chaos.a.pending"}
    only_wired = candidate_scenarios(
        idx,
        signal="pod_restart",
        target_type="pod",
        severity="low",
        include_needs_injector=False,
    )
    assert {c.ref for c in only_wired} == {"chaos.a.wired"}


def test_unknown_signal_returns_empty() -> None:
    idx = build_from_entries([_entry("chaos.a.p", "pod_restart", "pod", "mild")])
    got = candidate_scenarios(idx, signal="no_such_signal", target_type="pod", severity="low")
    assert got == ()


def test_empty_signal_is_rejected() -> None:
    idx = build_from_entries([_entry("chaos.a.p", "pod_restart", "pod", "mild")])
    with pytest.raises(ValueError, match="signal MUST be non-empty"):
        candidate_scenarios(idx, signal="", target_type="pod", severity="low")


def test_zero_max_candidates_is_rejected() -> None:
    idx = build_from_entries([_entry("chaos.a.p", "pod_restart", "pod", "mild")])
    with pytest.raises(ValueError, match="max_candidates MUST be positive"):
        candidate_scenarios(
            idx, signal="pod_restart", target_type="pod", severity="low", max_candidates=0
        )


def test_scenario_summary_names_matched_scenarios_only() -> None:
    idx = build_from_entries(
        [
            _entry(
                "chaos.a.pod-mild",
                "pod_restart",
                "pod",
                "mild",
                injector="chaos-mesh:PodChaos",
            ),
            _entry(
                "chaos.gpu.xid-1",
                "gpu_xid_event",
                "gpu",
                "high",
                injector="needs-injector",
                category="gpu_driver",
                gpu_domain="driver_xid",
                requires_hw=True,
            ),
        ]
    )
    text = scenario_summary(idx, signal="gpu_xid_event", target_type="gpu", severity="medium")
    assert "candidate scenarios" in text
    assert "chaos.gpu.xid-1" in text
    assert "chaos-mesh" not in text  # different signal, must not leak
    assert "gpu=driver_xid" in text
    assert "requires_hardware" in text


def test_scenario_summary_reports_no_match() -> None:
    idx = build_from_entries([_entry("chaos.a.p", "pod_restart", "pod", "mild")])
    text = scenario_summary(idx, signal="no_such_signal", target_type="pod", severity="low")
    assert "no catalog scenario" in text


def test_all_citations_are_scenario_kind() -> None:
    """A caller feeds these to `analyze_t2`; the reasoner's citation
    check filters by (kind, ref) equality, so the kind must be stable."""
    idx = build_from_entries([_entry("chaos.a.p", "pod_restart", "pod", "mild")])
    got = candidate_scenarios(idx, signal="pod_restart", target_type="pod", severity="low")
    for c in got:
        assert isinstance(c, Citation)
        assert c.kind is CitationKind.SCENARIO
