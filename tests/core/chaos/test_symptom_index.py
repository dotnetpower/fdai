"""Tests for the symptom -> scenarios inverted index."""

from __future__ import annotations

import pathlib

from fdai.core.chaos.scenario_catalog import CatalogEntry
from fdai.core.chaos.symptom_index import (
    ScenarioRef,
    SymptomIndex,
    build_from_all,
    build_from_entries,
    load_snapshot,
    write_snapshot,
)


def _entry(
    scenario_id: str,
    signal: str,
    target: str,
    intensity: str,
    category: str = "compute",
    injector: str = "chaos-mesh:PodChaos",
    requires_hw: bool = False,
    gpu_domain: str | None = None,
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


def test_exact_lookup_returns_matching_ref() -> None:
    e = _entry("chaos.a.pod-a", "pod_restart", "pod", "mild")
    idx = build_from_entries([e])
    hits = idx.lookup(("pod_restart", "pod", "low"))
    assert len(hits) == 1
    assert hits[0].id == "chaos.a.pod-a"


def test_severity_bucket_derived_from_intensity() -> None:
    entries = [
        _entry("chaos.a.pod-mild", "pod_restart", "pod", "mild"),
        _entry("chaos.a.pod-high", "pod_restart", "pod", "high"),
        _entry("chaos.a.pod-extreme", "pod_restart", "pod", "extreme"),
    ]
    idx = build_from_entries(entries)
    assert {r.id for r in idx.lookup(("pod_restart", "pod", "low"))} == {"chaos.a.pod-mild"}
    assert {r.id for r in idx.lookup(("pod_restart", "pod", "medium"))} == {"chaos.a.pod-high"}
    assert {r.id for r in idx.lookup(("pod_restart", "pod", "high"))} == {"chaos.a.pod-extreme"}


def test_widening_drops_severity_then_target() -> None:
    entries = [
        _entry("chaos.a.pod-mild", "pod_restart", "pod", "mild"),
        _entry("chaos.a.pod-high", "pod_restart", "pod", "high"),
        _entry("chaos.b.node-mild", "pod_restart", "node", "mild"),
    ]
    idx = build_from_entries(entries)
    # Exact bucket empty (no extreme pod), widen to (signal, target, None)
    hits = idx.lookup_widening("pod_restart", "pod", "high")
    assert {r.id for r in hits} == {"chaos.a.pod-mild", "chaos.a.pod-high"}
    # Signal only bucket includes everything with this signal
    hits_all = idx.lookup_widening("pod_restart", "unknown_target", "medium")
    assert {r.id for r in hits_all} == {
        "chaos.a.pod-mild",
        "chaos.a.pod-high",
        "chaos.b.node-mild",
    }


def test_widening_returns_empty_for_unknown_signal() -> None:
    idx = build_from_entries([_entry("chaos.a.p", "pod_restart", "pod", "mild")])
    assert idx.lookup_widening("no_such_signal", "pod", "low") == ()


def test_lookup_returns_empty_for_missing_key() -> None:
    idx = build_from_entries([_entry("chaos.a.p", "pod_restart", "pod", "mild")])
    assert idx.lookup(("db_cpu", "db", "high")) == ()


def test_index_carries_gpu_metadata() -> None:
    e = _entry(
        "chaos.gpu.xid-1",
        "gpu_xid_event",
        "gpu",
        "high",
        category="gpu_driver",
        injector="needs-injector",
        requires_hw=True,
        gpu_domain="driver_xid",
    )
    idx = build_from_entries([e])
    ref = idx.lookup(("gpu_xid_event", "gpu", "medium"))[0]
    assert ref.gpu_domain == "driver_xid"
    assert ref.requires_hardware is True
    assert ref.injector == "needs-injector"


def test_snapshot_roundtrip(tmp_path: pathlib.Path) -> None:
    entries = [
        _entry("chaos.a.pod-mild", "pod_restart", "pod", "mild"),
        _entry(
            "chaos.gpu.xid-1",
            "gpu_xid_event",
            "gpu",
            "high",
            category="gpu_driver",
            injector="needs-injector",
            requires_hw=True,
            gpu_domain="driver_xid",
        ),
    ]
    orig = build_from_entries(entries)
    snap_path = tmp_path / "idx.json"
    write_snapshot(orig, snap_path)
    loaded = load_snapshot(snap_path)
    assert loaded.all_signals() == orig.all_signals()
    assert loaded.size() == orig.size()
    assert {r.id for r in loaded.lookup(("pod_restart", "pod", "low"))} == {"chaos.a.pod-mild"}
    gpu_ref = loaded.lookup(("gpu_xid_event", "gpu", "medium"))[0]
    assert gpu_ref.gpu_domain == "driver_xid"
    assert gpu_ref.requires_hardware is True


def test_build_from_all_covers_seed_catalog() -> None:
    """The 70 seed scenarios in rule-catalog/chaos-scenarios/collected/**
    all land in the index. Sanity check that the catalog + index are
    wired end-to-end."""
    idx = build_from_all()
    # Every registered signal used by the seed catalog should be reachable.
    assert "pod_restart" in idx.all_signals()
    assert "gpu_xid_event" in idx.all_signals()
    # Widening returns something for a known signal even with an
    # unfamiliar target_type.
    hits = idx.lookup_widening("pod_restart", "some_fork_target", "low")
    assert hits, "widening on a known signal must return >=1 scenario"


def test_scenario_ref_is_frozen_and_hashable() -> None:
    r = ScenarioRef(
        id="chaos.a.p",
        expected_signal="pod_restart",
        target_type="pod",
        intensity="mild",
        severity_bucket="low",
        category="compute",
        injector="chaos-mesh:PodChaos",
        requires_hardware=False,
        gpu_domain=None,
        source_path="/x",
    )
    # frozen dataclass -> hashable
    hash(r)


def test_index_size_counts_across_widening_buckets() -> None:
    """size() counts every (key, ref) landing including widened buckets,
    because the widened buckets are the API a router actually uses."""
    entries = [
        _entry("chaos.a.pod-mild", "pod_restart", "pod", "mild"),
        _entry("chaos.a.pod-high", "pod_restart", "pod", "high"),
    ]
    idx = build_from_entries(entries)
    # 2 entries * 3 bucket levels (exact, target, signal) = 6 landings.
    assert idx.size() == 6


def test_by_key_is_a_read_only_mapping() -> None:
    idx = build_from_entries([_entry("chaos.a.p", "pod_restart", "pod", "mild")])
    assert isinstance(idx, SymptomIndex)
    # Not asserting the concrete Mapping type; just that reassignment on
    # the frozen dataclass fails.
    try:
        idx.by_key = {}  # type: ignore[misc]
    except (AttributeError, TypeError):
        return
    raise AssertionError("SymptomIndex.by_key must be immutable on a frozen dataclass")
