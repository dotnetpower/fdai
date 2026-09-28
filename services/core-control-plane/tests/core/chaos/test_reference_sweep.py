"""Regressions for the reference sweep's catalog selection."""

from __future__ import annotations

from fdai.core.chaos.reference_sweep import (
    REFERENCE_SWEEP_CATALOG_IDS,
    reference_catalog_id,
    reference_scenario_ids,
    reference_sweep_catalog_ids,
    resolve_scenario_id,
    unmapped_reference_scenarios,
)
from fdai.core.chaos.scenario_catalog import load_all
from fdai.core.chaos.scenarios import default_scenarios


def test_every_reference_scenario_maps_to_one_catalog_entry() -> None:
    assert unmapped_reference_scenarios() == ()
    assert reference_scenario_ids() == tuple(
        scenario.scenario_id for scenario in default_scenarios()
    )
    assert len(set(reference_sweep_catalog_ids())) == len(reference_sweep_catalog_ids())


def test_each_mapped_entry_exists_and_keeps_the_reference_signal() -> None:
    catalog = {entry.id: entry for entry in load_all()}
    signals = {scenario.scenario_id: scenario.expected_signal for scenario in default_scenarios()}

    for reference_id, catalog_id in REFERENCE_SWEEP_CATALOG_IDS.items():
        entry = catalog.get(catalog_id)
        assert entry is not None, f"{reference_id} maps to a missing catalog entry"
        assert entry.spec["expected_signal"] == signals[reference_id]


def test_resolution_passes_a_catalog_id_through_unchanged() -> None:
    assert reference_catalog_id("aks-pod-kill") == "chaos.general.pod-stop-pod-restart-mild"
    assert reference_catalog_id("chaos.chaos-mesh.pod-failure") is None
    assert resolve_scenario_id("chaos.chaos-mesh.pod-failure") == "chaos.chaos-mesh.pod-failure"
    assert resolve_scenario_id("aks-bad-deploy") == "chaos.general.pod-corrupt-rollout-stall-mild"
