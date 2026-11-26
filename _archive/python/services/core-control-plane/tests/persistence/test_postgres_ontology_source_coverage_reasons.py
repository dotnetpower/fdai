"""Inventory graph coverage keeps a typed reason for every source-completeness gap."""

from __future__ import annotations

from typing import Any

import pytest
from fdai.delivery.persistence.postgres_ontology_source_coverage import (
    InventoryGraphSourceCoverage,
    inventory_graph_source_coverage_detail,
    resolve_inventory_graph_source_coverage,
)
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot

_COMPLETE: dict[str, Any] = {
    "active_generation": "generation-2",
    "status": {"status": "available", "generation": "generation-2", "complete": True},
    "manifest": {
        "generation": "generation-2",
        "complete": True,
        "relationship_complete": True,
        "dropped_reasons": [],
    },
}


def _state(**updates: Any) -> dict[str, Any]:
    state = {
        **_COMPLETE,
        "status": dict(_COMPLETE["status"]),
        "manifest": dict(_COMPLETE["manifest"]),
    }
    for key, value in updates.items():
        if key in {"status", "manifest"}:
            state[key].update(value)
        else:
            state[key] = value
    return state


def test_complete_projection_has_no_reason() -> None:
    assert inventory_graph_source_coverage_detail(**_state()) == InventoryGraphSourceCoverage(
        complete=True,
        generation="generation-2",
    )


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"pending_observation": True}, "inventory_observation_pending"),
        ({"pending_correction": True}, "inventory_correction_pending"),
        ({"storage_pressure_hard": True}, "inventory_storage_pressure"),
        ({"pending_reconciliation": True}, "inventory_relationship_reconciliation_pending"),
        ({"status": {"generation": "generation-1"}}, "inventory_generation_transition"),
        ({"status": {"status": "unavailable"}}, "inventory_projection_unavailable"),
        ({"active_generation": None}, "inventory_projection_unavailable"),
        ({"manifest": {"complete": False}}, "inventory_projection_incomplete"),
        (
            {"manifest": {"manifest_digest": "sha256:" + "a" * 64}},
            "inventory_projection_inconsistent",
        ),
        ({"manifest": {"relationship_complete": False}}, "inventory_relationship_incomplete"),
        (
            {"pending_observation": True, "status": {"generation": "generation-1"}},
            "inventory_generation_transition+inventory_observation_pending",
        ),
    ],
)
def test_each_gap_keeps_its_typed_reason(updates: dict[str, Any], reason: str) -> None:
    state = _state(**updates)

    coverage = inventory_graph_source_coverage_detail(**state)

    assert coverage.complete is False
    assert coverage.reason == reason
    assert resolve_inventory_graph_source_coverage(**state) == (False, coverage.generation)


@pytest.mark.parametrize(
    "updates",
    [{"pending_reconciliation": True}, {"manifest": {"relationship_complete": False}}],
)
def test_relationship_gaps_do_not_limit_object_only_reads(updates: dict[str, Any]) -> None:
    state = _state(**updates, expresses_relationships=False)

    assert inventory_graph_source_coverage_detail(**state).complete is True
    assert resolve_inventory_graph_source_coverage(**state) == (True, "generation-2")


def test_snapshot_reason_exists_only_on_an_incomplete_snapshot() -> None:
    snapshot = OntologyGraphSnapshot(
        source_complete=False,
        source_incomplete_reason="inventory_generation_transition+inventory_observation_pending",
    )

    assert snapshot.source_incomplete_reason is not None
    with pytest.raises(ValueError, match="source_incomplete_reason"):
        OntologyGraphSnapshot(source_incomplete_reason="inventory_observation_pending")
    with pytest.raises(ValueError, match="source_incomplete_reason"):
        OntologyGraphSnapshot(source_complete=False, source_incomplete_reason="Not A Token")


def test_every_simultaneous_gap_fits_the_snapshot_reason_bound() -> None:
    state = _state(
        status={"status": "unavailable", "generation": "generation-1", "complete": False},
        manifest={"complete": False, "manifest_digest": "sha256:" + "a" * 64},
        storage_pressure_hard=True,
        pending_correction=True,
        pending_observation=True,
        pending_reconciliation=True,
    )

    coverage = inventory_graph_source_coverage_detail(**state)

    assert coverage.reason is not None
    assert len(coverage.reason.split("+")) == 8
    snapshot = OntologyGraphSnapshot(
        source_complete=coverage.complete,
        source_generation=coverage.generation,
        source_incomplete_reason=coverage.reason,
    )
    assert snapshot.source_incomplete_reason == coverage.reason
