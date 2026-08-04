"""Ontology-constrained semantic completion for inventory state queries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from fdai.delivery.operator_api.routes.chat_inventory_language import (
    default_inventory_query_language_resolver,
)
from fdai.delivery.operator_api.routes.chat_inventory_query import (
    InventoryField,
    InventoryOperator,
    InventoryPredicate,
    InventoryQuery,
    normalize_inventory_value,
)
from fdai.rule_catalog.schema.inventory_query_language import QueryEvidenceAuthority


class SemanticInventoryStatusError(ValueError):
    """Raised when a planner proposes a non-canonical inventory state."""


def merge_semantic_inventory_status(
    evidence: Mapping[str, Any],
    planned_arguments: Mapping[str, object],
) -> dict[str, object] | None:
    """Merge only a canonical planned state into the deterministic query."""

    result = evidence.get("result")
    raw_query = result.get("query") if isinstance(result, Mapping) else None
    if not isinstance(raw_query, Mapping):
        return None
    try:
        query = InventoryQuery.from_mapping(raw_query)
    except ValueError:
        return None
    return merge_semantic_inventory_status_query(query, planned_arguments)


def merge_semantic_inventory_status_query(
    query: InventoryQuery,
    planned_arguments: Mapping[str, object],
) -> dict[str, object] | None:
    """Merge a canonical planned state into one trusted deterministic query."""

    if any(predicate.field is InventoryField.STATUS for predicate in query.predicates):
        return None

    raw_predicates = planned_arguments.get("predicates")
    if not isinstance(raw_predicates, Sequence) or isinstance(raw_predicates, str | bytes):
        return None
    planned_statuses = [
        item
        for item in raw_predicates
        if isinstance(item, Mapping) and item.get("field") == InventoryField.STATUS.value
    ]
    if not planned_statuses:
        return None
    if len(planned_statuses) != 1:
        raise SemanticInventoryStatusError("semantic inventory status predicate is ambiguous")
    predicate = _canonical_status_predicate(planned_statuses[0])
    if predicate is None:
        raise SemanticInventoryStatusError("semantic inventory status predicate is invalid")
    return replace(query, predicates=(*query.predicates, predicate)).to_dict()


def ground_inventory_status_query(
    query: InventoryQuery,
    resources: Sequence[Mapping[str, Any]],
) -> InventoryQuery:
    """Expand canonical state values to matching provider-observed status values."""

    status_predicates = [
        predicate for predicate in query.predicates if predicate.field is InventoryField.STATUS
    ]
    if len(status_predicates) != 1:
        return query
    predicate = status_predicates[0]
    requested = predicate.value if isinstance(predicate.value, tuple) else (predicate.value,)
    canonical = _canonical_current_status_values()
    if any(not isinstance(value, str) or value not in canonical for value in requested):
        return query
    requested_set = set(requested)
    observed = tuple(
        dict.fromkeys(
            normalize_inventory_value(resource["status"])
            for resource in resources
            if resource.get("status") not in (None, "")
            and normalize_inventory_value(resource["status"]).rsplit(" ", 1)[-1] in requested_set
        )
    )
    if not observed:
        return query
    grounded = InventoryPredicate(
        InventoryField.STATUS,
        InventoryOperator.EQ if len(observed) == 1 else InventoryOperator.IN,
        observed[0] if len(observed) == 1 else observed,
    )
    return replace(
        query,
        predicates=tuple(grounded if item is predicate else item for item in query.predicates),
    )


def _canonical_status_predicate(raw: Mapping[str, object]) -> InventoryPredicate | None:
    operator = raw.get("operator")
    value = raw.get("value")
    state_ids: tuple[str, ...]
    if operator == InventoryOperator.EQ.value and isinstance(value, str):
        state_ids = (normalize_inventory_value(value),)
    elif operator == InventoryOperator.IN.value and isinstance(value, list) and value:
        if any(not isinstance(item, str) for item in value):
            return None
        state_ids = tuple(normalize_inventory_value(item) for item in value)
    else:
        return None

    registry = default_inventory_query_language_resolver().registry
    values: list[str] = []
    for state_id in state_ids:
        state = registry.states.get(state_id)
        if (
            state is None
            or state.evidence_authority is not QueryEvidenceAuthority.CURRENT_INVENTORY
        ):
            return None
        values.extend(normalize_inventory_value(item) for item in state.values)
    unique = tuple(dict.fromkeys(values))
    return InventoryPredicate(
        InventoryField.STATUS,
        InventoryOperator.EQ if len(unique) == 1 else InventoryOperator.IN,
        unique[0] if len(unique) == 1 else unique,
    )


def _canonical_current_status_values() -> frozenset[str]:
    registry = default_inventory_query_language_resolver().registry
    return frozenset(
        normalize_inventory_value(value)
        for state in registry.states.values()
        if state.evidence_authority is QueryEvidenceAuthority.CURRENT_INVENTORY
        for value in (
            *state.values,
            *(item for values in state.category_values.values() for item in values),
        )
    )


__all__ = [
    "SemanticInventoryStatusError",
    "ground_inventory_status_query",
    "merge_semantic_inventory_status",
    "merge_semantic_inventory_status_query",
]
