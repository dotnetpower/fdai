from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.delivery.operator_api.application.conversation.capabilities.inventory.query import (
    InventoryField,
    InventoryOperator,
    InventoryPredicate,
    InventoryQuery,
    InventoryQueryGrouping,
    InventoryQueryKind,
    InventoryQueryProjection,
    InventoryQueryScope,
    InventoryQuerySource,
    InventoryScheduleWindow,
    inventory_query_argument_schema,
    inventory_query_matches,
    normalize_inventory_value,
)


def test_scheduled_shutdown_query_pins_aware_reference_time() -> None:
    query = InventoryQuery(
        source=InventoryQuerySource.CURRENT,
        kind=InventoryQueryKind.SCHEDULED_SHUTDOWN,
        predicates=(
            InventoryPredicate(
                InventoryField.RESOURCE_TYPE,
                InventoryOperator.EQ,
                "compute.vm-shutdown-schedule",
            ),
        ),
        require_fresh=True,
        schedule_window=InventoryScheduleWindow.TODAY_EVENING,
        reference_time=datetime(2026, 8, 5, 3, 0, tzinfo=UTC),
    )

    assert query.to_dict()["schedule_window"] == "today_evening"
    assert query.to_dict()["reference_time"] == "2026-08-05T03:00:00+00:00"
    assert InventoryQuery.from_mapping(query.to_dict()) == query


def test_scheduled_shutdown_query_rejects_missing_or_naive_reference_time() -> None:
    with pytest.raises(ValueError, match="requires a window and reference time"):
        InventoryQuery(
            source=InventoryQuerySource.CURRENT,
            kind=InventoryQueryKind.SCHEDULED_SHUTDOWN,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        InventoryQuery(
            source=InventoryQuerySource.CURRENT,
            kind=InventoryQueryKind.SCHEDULED_SHUTDOWN,
            schedule_window=InventoryScheduleWindow.TODAY_EVENING,
            reference_time=datetime(2026, 8, 5, 3, 0),
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
        "scope": "active_view",
        "group_by": "none",
        "projection": "details",
        "require_fresh": False,
        "include_workloads": False,
        "require_state_history": False,
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


def test_not_in_requires_bounded_values_and_excludes_exact_matches() -> None:
    query = InventoryQuery.from_mapping(
        {
            "source": "current",
            "kind": "list",
            "predicates": [
                {
                    "field": "status",
                    "operator": "not_in",
                    "value": ["VM stopped", "PowerState/deallocated"],
                }
            ],
            "lookback_seconds": None,
        }
    )

    assert inventory_query_matches(query, {"status": "VM running"})
    assert not inventory_query_matches(query, {"status": "VM stopped"})
    assert not inventory_query_matches(query, {"status": "PowerState/deallocated"})
    with pytest.raises(ValueError, match="not_in requires"):
        InventoryPredicate(
            InventoryField.STATUS,
            InventoryOperator.NOT_IN,
            "stopped",
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
                "unknown": "caller-supplied",
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
    assert normalize_inventory_value(" PowerState:RUNNING ") == "powerstate running"


def test_name_contains_does_not_match_inside_larger_token() -> None:
    query = InventoryQuery(
        InventoryQuerySource.CURRENT,
        InventoryQueryKind.LIST,
        (InventoryPredicate(InventoryField.NAME, InventoryOperator.CONTAINS, "sql"),),
    )

    assert inventory_query_matches(query, {"name": "sql-db"})
    assert inventory_query_matches(query, {"name": "my-sql-server"})
    assert not inventory_query_matches(query, {"name": "nosql-cache"})
    assert not inventory_query_matches(query, {"name": "postgresql-server"})


def test_semantic_schema_is_closed_and_bounded() -> None:
    schema = inventory_query_argument_schema()
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["source", "kind", "predicates", "lookback_seconds"]
    properties = schema["properties"]
    assert isinstance(properties, dict)
    predicates = properties["predicates"]
    assert isinstance(predicates, dict)
    assert predicates["maxItems"] == 8


def test_planned_query_preserves_subscription_table_selection() -> None:
    query = InventoryQuery.from_mapping(
        {
            "source": "current",
            "kind": "list",
            "predicates": [{"field": "resource_type", "operator": "eq", "value": "resource-group"}],
            "lookback_seconds": None,
            "scope": "subscription",
            "group_by": "none",
            "projection": "details",
            "require_fresh": True,
            "include_workloads": False,
            "require_state_history": False,
        }
    )

    assert query.scope is InventoryQueryScope.SUBSCRIPTION
    assert query.group_by is InventoryQueryGrouping.NONE
    assert query.projection is InventoryQueryProjection.DETAILS
    assert query.require_fresh is True
