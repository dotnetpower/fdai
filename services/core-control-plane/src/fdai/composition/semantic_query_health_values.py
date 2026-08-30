"""Derive Resource Health value groups from inventory query semantics."""

from __future__ import annotations

from fdai.core.ontology_platform.resource_state_queries import (
    RESOURCE_STATE_MEASURE_CONCEPTS,
)
from fdai.rule_catalog.schema.inventory_query_language import (
    InventoryQueryLanguageRegistry,
    QueryEvidenceAuthority,
)


def resource_health_state_values(
    registry: InventoryQueryLanguageRegistry,
) -> dict[str, tuple[str, ...]]:
    """Return non-inventory state groups accepted by Resource Health queries."""

    state_measures = frozenset(RESOURCE_STATE_MEASURE_CONCEPTS)
    groups: dict[str, tuple[str, ...]] = {}
    for state_id, state in registry.states.items():
        normalized = {f"resource_state.{value}" for value in state.values}
        if (
            state.evidence_authority is not QueryEvidenceAuthority.CURRENT_INVENTORY
            or not normalized <= state_measures
        ):
            groups[f"resource_health.{state_id}"] = state.values
    if not groups:
        raise ValueError("inventory query language declares no Resource Health semantics")
    return groups


__all__ = ["resource_health_state_values"]
