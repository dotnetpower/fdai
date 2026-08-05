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
    inventory_query_matches,
    normalize_inventory_value,
)
from fdai.delivery.operator_api.routes.chat_inventory_resource_types import (
    default_inventory_resource_type_resolver,
)
from fdai.rule_catalog.schema.inventory_query_language import QueryEvidenceAuthority

_PROVIDER_STATUS_PREFIXES = frozenset({"powerstate", "vm"})


class SemanticInventoryStatusError(ValueError):
    """Raised when a planner proposes a non-canonical inventory state."""


class SemanticInventoryInterpretationRequiredError(ValueError):
    """Raised when a required semantic predicate remains unresolved."""


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
    predicate = _canonical_status_predicate(
        planned_statuses[0],
        resource_category=_query_resource_category(query),
    )
    if predicate is None:
        raise SemanticInventoryStatusError("semantic inventory status predicate is invalid")
    return replace(query, predicates=(*query.predicates, predicate)).to_dict()


def validate_semantic_inventory_status_arguments(
    query: InventoryQuery,
    planned_arguments: Mapping[str, object],
) -> None:
    """Reject non-canonical planner status values without changing a complete query."""

    raw_predicates = planned_arguments.get("predicates")
    if not isinstance(raw_predicates, Sequence) or isinstance(raw_predicates, str | bytes):
        return
    planned_statuses = [
        item
        for item in raw_predicates
        if isinstance(item, Mapping) and item.get("field") == InventoryField.STATUS.value
    ]
    if not planned_statuses:
        return
    if (
        len(planned_statuses) != 1
        or _canonical_status_predicate(
            planned_statuses[0],
            resource_category=_query_resource_category(query),
        )
        is None
    ):
        raise SemanticInventoryStatusError("semantic inventory status predicate is invalid")


def canonicalize_semantic_inventory_status_arguments(
    query: InventoryQuery,
    planned_arguments: Mapping[str, object],
) -> InventoryQuery:
    """Replace planned ontology state IDs with their canonical provider values."""

    raw_predicates = planned_arguments.get("predicates")
    if not isinstance(raw_predicates, Sequence) or isinstance(raw_predicates, str | bytes):
        return query
    if not any(
        isinstance(item, Mapping) and item.get("field") == InventoryField.STATUS.value
        for item in raw_predicates
    ):
        return query
    selector = replace(
        query,
        predicates=tuple(
            predicate
            for predicate in query.predicates
            if predicate.field is not InventoryField.STATUS
        ),
    )
    merged = merge_semantic_inventory_status_query(selector, planned_arguments)
    if merged is None:  # pragma: no cover - status presence guarantees a merge or error
        raise SemanticInventoryStatusError("semantic inventory status predicate is invalid")
    return InventoryQuery.from_mapping(merged)


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
    raw_requested = predicate.value if isinstance(predicate.value, tuple) else (predicate.value,)
    requested = tuple(value for value in raw_requested if isinstance(value, str))
    if len(requested) != len(raw_requested):
        return query
    canonical = _canonical_current_status_values()
    if any(value not in canonical for value in requested):
        return query
    requested_set = set(requested)
    selector = replace(
        query,
        predicates=tuple(
            item for item in query.predicates if item.field is not InventoryField.STATUS
        ),
    )
    observed = tuple(
        dict.fromkeys(
            normalize_inventory_value(resource["status"])
            for resource in resources
            if inventory_query_matches(selector, resource)
            and resource.get("status") not in (None, "")
            and _observed_status_matches(resource["status"], requested_set)
        )
    )
    if not observed:
        return query
    grounded_operator = (
        InventoryOperator.NOT_IN
        if predicate.operator is InventoryOperator.NOT_IN
        else InventoryOperator.EQ
        if len(observed) == 1
        else InventoryOperator.IN
    )
    grounded = InventoryPredicate(
        InventoryField.STATUS,
        grounded_operator,
        observed
        if grounded_operator is InventoryOperator.NOT_IN
        else observed[0]
        if len(observed) == 1
        else observed,
    )
    return replace(
        query,
        predicates=tuple(grounded if item is predicate else item for item in query.predicates),
    )


def _observed_status_matches(value: object, requested: set[str]) -> bool:
    normalized = normalize_inventory_value(value)
    if normalized in requested:
        return True
    prefix, separator, state = normalized.partition(" ")
    return bool(separator and prefix in _PROVIDER_STATUS_PREFIXES and state in requested)


def _canonical_status_predicate(
    raw: Mapping[str, object],
    *,
    resource_category: str | None,
) -> InventoryPredicate | None:
    operator = raw.get("operator")
    value = raw.get("value")
    state_ids: tuple[str, ...]
    if operator == InventoryOperator.EQ.value and isinstance(value, str):
        state_ids = (normalize_inventory_value(value),)
    elif (
        operator
        in {
            InventoryOperator.IN.value,
            InventoryOperator.NOT_IN.value,
        }
        and isinstance(value, list)
        and value
    ):
        string_values = tuple(item for item in value if isinstance(item, str))
        if len(string_values) != len(value):
            return None
        state_ids = tuple(normalize_inventory_value(item) for item in string_values)
    else:
        return None

    registry = default_inventory_query_language_resolver().registry
    suppressed = {
        suppressed_id
        for state_id in state_ids
        if (state := registry.states.get(state_id)) is not None
        for suppressed_id in state.suppresses
    }
    state_ids = tuple(state_id for state_id in state_ids if state_id not in suppressed)
    if not state_ids:
        return None
    values: list[str] = []
    for state_id in state_ids:
        state = registry.states.get(state_id)
        if (
            state is None
            or state.evidence_authority is not QueryEvidenceAuthority.CURRENT_INVENTORY
        ):
            return None
        state_values = (
            state.category_values.get(resource_category, state.values)
            if resource_category is not None
            else state.values
        )
        values.extend(normalize_inventory_value(item) for item in state_values)
    unique = tuple(dict.fromkeys(values))
    if not 1 <= len(unique) <= 16 or any(not value for value in unique):
        return None
    resolved_operator = (
        InventoryOperator.NOT_IN
        if operator == InventoryOperator.NOT_IN.value
        else InventoryOperator.EQ
        if len(unique) == 1
        else InventoryOperator.IN
    )
    return InventoryPredicate(
        InventoryField.STATUS,
        resolved_operator,
        unique
        if resolved_operator is InventoryOperator.NOT_IN
        else unique[0]
        if len(unique) == 1
        else unique,
    )


def _query_resource_category(query: InventoryQuery) -> str | None:
    type_values: list[str] = []
    for predicate in query.predicates:
        if predicate.field is not InventoryField.RESOURCE_TYPE:
            continue
        if predicate.operator is InventoryOperator.EQ and isinstance(predicate.value, str):
            type_values.append(predicate.value)
        elif predicate.operator is InventoryOperator.IN and isinstance(predicate.value, tuple):
            type_values.extend(predicate.value)
    categories = default_inventory_resource_type_resolver().categories_for(type_values)
    return categories[0] if len(categories) == 1 else None


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
    "SemanticInventoryInterpretationRequiredError",
    "canonicalize_semantic_inventory_status_arguments",
    "ground_inventory_status_query",
    "merge_semantic_inventory_status",
    "merge_semantic_inventory_status_query",
    "validate_semantic_inventory_status_arguments",
]
