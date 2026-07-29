from __future__ import annotations

import pytest

from fdai.delivery.read_api.routes.chat_inventory_query import (
    InventoryField,
    InventoryOperator,
    InventoryPredicate,
    InventoryQuery,
    InventoryQueryKind,
    InventoryQuerySource,
    inventory_query_argument_schema,
    inventory_query_matches,
    normalize_inventory_value,
)


def test_current_query_round_trips_and_matches_exact_normalized_status() -> None:
    query = InventoryQuery.from_mapping(
        {
            "source": "current",
            "kind": "list",
            "predicates": [
                {"field": "resource_type", "operator": "eq", "value": "compute.vm"},
                {"field": "status", "operator": "eq", "value": "PowerState/running"},
            ],
            "lookback_seconds": None,
        }
    )

    assert query.to_dict() == {
        "source": "current",
        "kind": "list",
        "predicates": [
            {"field": "resource_type", "operator": "eq", "value": "compute.vm"},
            {"field": "status", "operator": "eq", "value": "powerstate running"},
        ],
        "lookback_seconds": None,
    }
    assert inventory_query_matches(
        query,
        {"type": "compute.vm", "status": "PowerState/running"},
    )
    assert not inventory_query_matches(
        query,
        {"type": "compute.vm", "status": "not_running"},
    )


def test_activity_query_accepts_bounded_change_predicates() -> None:
    query = InventoryQuery(
        source=InventoryQuerySource.ACTIVITY,
        kind=InventoryQueryKind.COUNT,
        predicates=(
            InventoryPredicate(
                InventoryField.OPERATION,
                InventoryOperator.IN,
                ("start", "stop", "write"),
            ),
            InventoryPredicate(
                InventoryField.EVENT_STATUS,
                InventoryOperator.EQ,
                "Succeeded",
            ),
        ),
        lookback_seconds=7 * 24 * 3_600,
    )

    assert inventory_query_matches(
        query,
        {"operation": "stop", "event_status": "succeeded"},
    )
    assert not inventory_query_matches(
        query,
        {"operation": "delete", "event_status": "succeeded"},
    )


@pytest.mark.parametrize(
    "raw, message",
    [
        (
            {
                "source": "current",
                "kind": "list",
                "predicates": [],
                "lookback_seconds": None,
                "scope": "caller-supplied",
            },
            "unknown fields",
        ),
        (
            {
                "source": "current",
                "kind": "list",
                "predicates": [{"field": "operation", "operator": "eq", "value": "delete"}],
                "lookback_seconds": None,
            },
            "invalid for current",
        ),
        (
            {
                "source": "activity",
                "kind": "list",
                "predicates": [],
                "lookback_seconds": 31 * 24 * 3_600,
            },
            "out of bounds",
        ),
        (
            {
                "source": "current",
                "kind": "list",
                "predicates": [{"field": "status", "operator": "set", "value": "running"}],
                "lookback_seconds": None,
            },
            "enum is invalid",
        ),
    ],
)
def test_untrusted_query_rejects_scope_field_operator_and_lookback(
    raw: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        InventoryQuery.from_mapping(raw)


def test_query_rejects_partial_predicate_and_duplicate_in_values() -> None:
    with pytest.raises(ValueError, match="predicate fields"):
        InventoryQuery.from_mapping(
            {
                "source": "current",
                "kind": "list",
                "predicates": [{"field": "status", "operator": "eq"}],
                "lookback_seconds": None,
            }
        )
    with pytest.raises(ValueError, match="unique"):
        InventoryPredicate(
            InventoryField.STATUS,
            InventoryOperator.IN,
            ("Running", "running"),
        )


def test_exists_missing_contains_and_normalization_are_deterministic() -> None:
    current = {"name": "VM-App_01", "location": "Korea Central"}
    assert inventory_query_matches(
        InventoryQuery(
            InventoryQuerySource.CURRENT,
            InventoryQueryKind.LIST,
            (InventoryPredicate(InventoryField.NAME, InventoryOperator.CONTAINS, "app 01"),),
        ),
        current,
    )
    assert inventory_query_matches(
        InventoryQuery(
            InventoryQuerySource.CURRENT,
            InventoryQueryKind.LIST,
            (InventoryPredicate(InventoryField.STATUS, InventoryOperator.MISSING),),
        ),
        current,
    )
    assert normalize_inventory_value(" PowerState/DEALLOCATED ") == "powerstate deallocated"


def test_semantic_schema_is_closed_and_bounded() -> None:
    schema = inventory_query_argument_schema()
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["source", "kind", "predicates", "lookback_seconds"]
    properties = schema["properties"]
    assert isinstance(properties, dict)
    predicates = properties["predicates"]
    assert isinstance(predicates, dict)
    assert predicates["maxItems"] == 8
