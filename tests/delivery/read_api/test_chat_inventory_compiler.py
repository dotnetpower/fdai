from __future__ import annotations

import itertools

import pytest

from fdai.delivery.read_api.routes.chat_inventory_compiler import (
    compile_inventory_query,
    is_inventory_question,
)
from fdai.delivery.read_api.routes.chat_inventory_query import (
    InventoryField,
    InventoryOperator,
    InventoryQuerySource,
)

_RESOURCES = (
    {
        "type": "compute.vm",
        "name": "vm-app",
        "status": "VM running",
        "resource_group": "rg-app",
        "location": "koreacentral",
    },
    {
        "type": "compute.vm",
        "name": "vm-job",
        "status": "VM deallocated",
        "resource_group": "rg-app",
        "location": "koreacentral",
    },
    {
        "type": "postgresql-server",
        "name": "postgres-data",
        "status": "maintenance",
        "resource_group": "rg-data",
        "location": "westus",
    },
    {
        "type": "sql-database",
        "name": "sql-data",
        "status": "failed",
        "resource_group": "rg-data",
        "location": "westus",
    },
)


@pytest.mark.parametrize(
    "prompt,source,field,expected",
    [
        ("중지된 vm 은?", "current", "status", ("vm deallocated",)),
        ("running VM 목록", "current", "status", ("vm running",)),
        ("maintenance resources?", "current", "status", ("maintenance",)),
        ("failed resources in westus?", "current", "status", ("failed",)),
        ("최근 7일 시작된 리소스", "activity", "operation", ("start",)),
        ("deleted resources last 24 hours", "activity", "operation", ("delete",)),
        ("변경된 리소스 보여줘", "activity", "operation", ("write",)),
        (
            "최근 중지된 VM 목록",
            "activity",
            "operation",
            ("stop", "deallocate", "power off"),
        ),
    ],
)
def test_compiler_maps_current_facets_and_activity_operations(
    prompt: str,
    source: str,
    field: str,
    expected: tuple[str, ...],
) -> None:
    query = compile_inventory_query(prompt, resources=_RESOURCES)

    assert query is not None
    assert query.source.value == source
    predicate = next(item for item in query.predicates if item.field.value == field)
    values = predicate.value if isinstance(predicate.value, tuple) else (predicate.value,)
    assert values == expected


def test_compiler_combines_type_status_group_location_and_name() -> None:
    query = compile_inventory_query(
        "resource group rg-app 이름이 vm-job인 중지된 VM은?",
        resources=_RESOURCES,
    )

    assert query is not None
    by_field = {predicate.field: predicate for predicate in query.predicates}
    assert by_field[InventoryField.RESOURCE_TYPE].value == "compute.vm"
    assert by_field[InventoryField.STATUS].value == "vm deallocated"
    assert by_field[InventoryField.RESOURCE_GROUP].value == "rg-app"
    assert by_field[InventoryField.NAME].operator is InventoryOperator.CONTAINS
    assert by_field[InventoryField.NAME].value == "vm-job"


def test_observed_type_and_location_are_dynamic_facets() -> None:
    resources = (
        *_RESOURCES,
        {
            "type": "custom.widget",
            "name": "w1",
            "status": "updating",
            "location": "northpole",
        },
    )
    query = compile_inventory_query(
        "northpole의 updating custom.widget resources?",
        resources=resources,
    )

    assert query is not None
    by_field = {predicate.field: predicate.value for predicate in query.predicates}
    assert by_field[InventoryField.RESOURCE_TYPE] == "custom.widget"
    assert by_field[InventoryField.STATUS] == "updating"
    assert by_field[InventoryField.LOCATION] == "northpole"


@pytest.mark.parametrize(
    "prompt",
    [
        "suspended resources?",
        "degraded resources?",
        "resources in unknownregion?",
        "Which Azure assets are dormant?",
        "점검중인 리소스 있어?",
    ],
)
def test_unobserved_filter_abstains_instead_of_widening_to_all_resources(prompt: str) -> None:
    assert is_inventory_question(prompt)
    assert compile_inventory_query(prompt, resources=_RESOURCES) is None


def test_activity_window_is_bounded_by_query_contract() -> None:
    query = compile_inventory_query("resources deleted in the last 2 weeks", resources=_RESOURCES)
    assert query is not None
    assert query.source is InventoryQuerySource.ACTIVITY
    assert query.lookback_seconds == 14 * 24 * 3_600

    with pytest.raises(ValueError, match="out of bounds"):
        compile_inventory_query("resources deleted in the last 31 days", resources=_RESOURCES)


@pytest.mark.parametrize(
    "prompt",
    [
        "stop the VM",
        "VM을 중지해줘",
        "create a resource group",
        "리소스를 삭제해주세요",
        "why is the database slow?",
        "VM CPU usage",
    ],
)
def test_mutation_diagnosis_and_metric_requests_do_not_compile(prompt: str) -> None:
    assert not is_inventory_question(prompt)
    assert compile_inventory_query(prompt, resources=_RESOURCES) is None


def test_filter_word_order_does_not_change_compiled_predicates() -> None:
    fragments = ("running", "VM", "resource group rg-app")
    projections = set()
    for order in itertools.permutations(fragments):
        query = compile_inventory_query(" ".join(order) + "?", resources=_RESOURCES)
        assert query is not None
        projections.add(
            tuple(
                (predicate.field.value, predicate.operator.value, predicate.value)
                for predicate in query.predicates
            )
        )
    assert len(projections) == 1
