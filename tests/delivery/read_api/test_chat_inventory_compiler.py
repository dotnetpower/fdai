from __future__ import annotations

import itertools
from pathlib import Path

import pytest
import yaml

from fdai.delivery.read_api.routes.chat_inventory_compiler import (
    compile_inventory_query,
    is_inventory_question,
)
from fdai.delivery.read_api.routes.chat_inventory_query import (
    InventoryField,
    InventoryOperator,
    InventoryQueryGrouping,
    InventoryQuerySource,
)
from fdai.delivery.read_api.routes.chat_inventory_resource_types import (
    InventoryResourceTypeResolver,
)
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
VOCAB_YAML = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"

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


def _resource_type_resolver() -> InventoryResourceTypeResolver:
    registry = load_resource_type_registry_from_mapping(
        yaml.safe_load(VOCAB_YAML.read_text(encoding="utf-8"))
    )
    return InventoryResourceTypeResolver(registry)


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("Web App 목록을 보여줘", "compute.web-app"),
        ("함수 앱 목록을 보여줘", "compute.function"),
        ("Logic App 목록을 보여줘", "workflow.logic-app"),
        ("NSG 목록을 보여줘", "network.nsg"),
        ("Azure Firewall 목록을 보여줘", "network.firewall"),
        ("DCR 목록을 보여줘", "data-collection-rule"),
        ("PostgreSQL DB 목록을 보여줘", "postgresql-server"),
    ],
)
def test_catalog_terms_resolve_diverse_azure_resource_types(
    prompt: str,
    expected: str,
) -> None:
    resolver = _resource_type_resolver()

    query = compile_inventory_query(prompt, resources=_RESOURCES, resolver=resolver)

    assert query is not None
    predicate = next(
        item for item in query.predicates if item.field is InventoryField.RESOURCE_TYPE
    )
    assert predicate.operator is InventoryOperator.EQ
    assert predicate.value == expected


def test_catalog_entry_addition_needs_no_compiler_alias_change() -> None:
    registry = load_resource_type_registry_from_mapping(
        {
            "schema_version": "1.0.0",
            "version": "0.0.1",
            "category_query_terms": {},
            "types": [
                {
                    "id": "custom.widget",
                    "category": "compute",
                    "description": "Synthetic extensibility fixture.",
                    "query_terms": ["widget service", "위젯 서비스"],
                }
            ],
        }
    )
    resolver = InventoryResourceTypeResolver(registry)

    query = compile_inventory_query("위젯 서비스 목록은?", resolver=resolver)

    assert query is not None
    assert query.predicates[0].value == "custom.widget"


def test_observed_type_does_not_widen_exact_catalog_match() -> None:
    resources = (
        *_RESOURCES,
        {
            "type": "vm",
            "name": "provider-vm-alias",
            "status": "running",
            "location": "westus",
        },
    )

    query = compile_inventory_query("VM 목록은?", resources=resources)

    assert query is not None
    predicate = next(
        item for item in query.predicates if item.field is InventoryField.RESOURCE_TYPE
    )
    assert predicate.operator is InventoryOperator.EQ
    assert predicate.value == "compute.vm"


def test_database_category_with_korean_object_particle_preserves_status_scope() -> None:
    resources = (
        {
            "type": "mysql-server",
            "name": "mysql-data",
            "status": "Stopped",
            "resource_group": "rg-data",
            "location": "westus",
        },
        {
            "type": "postgresql-server",
            "name": "postgres-data",
            "status": "Stopped",
            "resource_group": "rg-data",
            "location": "westus",
        },
        {
            "type": "sql-database",
            "name": "sql-data",
            "status": "Paused",
            "resource_group": "rg-data",
            "location": "westus",
        },
        {
            "type": "compute.vm",
            "name": "vm-stopped",
            "status": "Stopped",
            "resource_group": "rg-app",
            "location": "koreacentral",
        },
    )

    query = compile_inventory_query(
        "현재 멈춰 있는 DB를 종류별로 보여줘.",
        resources=resources,
    )

    assert query is not None
    by_field = {predicate.field: predicate for predicate in query.predicates}
    resource_types = by_field[InventoryField.RESOURCE_TYPE].value
    assert isinstance(resource_types, tuple)
    assert "mysql-server" in resource_types
    assert "postgresql-server" in resource_types
    assert "compute.vm" not in resource_types
    assert query.kind.value == "types"
    assert by_field[InventoryField.STATUS].operator is InventoryOperator.IN
    assert by_field[InventoryField.STATUS].value == ("stopped", "deallocated", "paused")


def test_explicit_paused_database_filter_is_preserved_when_unobserved() -> None:
    resources = (
        {
            "type": "mysql-server",
            "name": "mysql-data",
            "status": "Stopped",
        },
    )

    query = compile_inventory_query(
        "List stopped and paused database services separately.",
        resources=resources,
    )

    assert query is not None
    status = next(
        predicate for predicate in query.predicates if predicate.field is InventoryField.STATUS
    )
    assert status.operator is InventoryOperator.IN
    assert status.value == ("stopped", "paused")


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


def test_korean_deallocated_vm_question_preserves_type_and_state() -> None:
    query = compile_inventory_query(
        "할당 해제된 가상 머신을 모두 찾아줘.",
        resources=_RESOURCES,
    )

    assert query is not None
    by_field = {predicate.field: predicate.value for predicate in query.predicates}
    assert by_field[InventoryField.RESOURCE_TYPE] == "compute.vm"
    assert by_field[InventoryField.STATUS] == "vm deallocated"


def test_multiple_vm_states_group_without_overlapping_deallocated_values() -> None:
    query = compile_inventory_query(
        "Which virtual machines are running, stopped, or deallocated?",
        resources=_RESOURCES,
    )

    assert query is not None
    assert query.group_by is InventoryQueryGrouping.STATUS
    assert [(group.id, group.values) for group in query.status_groups] == [
        ("stopped", ("stopped",)),
        ("deallocated", ("deallocated",)),
        ("running", ("running",)),
    ]


def test_unhealthy_aks_node_question_requires_workload_evidence() -> None:
    resources = (
        {
            "type": "kubernetes-cluster",
            "name": "aks-stopped",
            "status": "Stopped",
        },
        {
            "type": "kubernetes-cluster",
            "name": "aks-running",
            "status": "Running",
        },
    )

    query = compile_inventory_query(
        "비정상 상태인 AKS 클러스터나 노드가 있어?",
        resources=resources,
    )

    assert query is not None
    by_field = {predicate.field: predicate.value for predicate in query.predicates}
    assert by_field[InventoryField.RESOURCE_TYPE] == "kubernetes-cluster"
    assert by_field[InventoryField.STATUS] == "stopped"
    assert query.include_workloads is True


def test_unhealthy_kubernetes_workload_question_requires_history() -> None:
    query = compile_inventory_query(
        "Show unhealthy Kubernetes workloads and when they became unhealthy.",
        resources=(
            {
                "type": "kubernetes-cluster",
                "name": "aks-stopped",
                "status": "Stopped",
            },
            {
                "type": "log-analytics-solution",
                "name": "kubernetes",
                "status": "unknown",
            },
        ),
    )

    assert query is not None
    by_field = {predicate.field: predicate.value for predicate in query.predicates}
    assert by_field[InventoryField.RESOURCE_TYPE] == "kubernetes-cluster"
    assert by_field[InventoryField.STATUS] == "stopped"
    assert InventoryField.NAME not in by_field
    assert query.include_workloads is True
    assert query.require_state_history is True


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
        "resources in unknownregion?",
        "Which Azure assets are dormant?",
        "점검중인 리소스 있어?",
    ],
)
def test_unobserved_filter_abstains_instead_of_widening_to_all_resources(prompt: str) -> None:
    assert is_inventory_question(prompt)
    assert compile_inventory_query(prompt, resources=_RESOURCES) is None


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("suspended resources?", "paused"),
        ("degraded resources?", "degraded"),
    ],
)
def test_known_unobserved_state_is_preserved_as_zero_result_query(
    prompt: str,
    expected: str,
) -> None:
    query = compile_inventory_query(prompt, resources=_RESOURCES)

    assert query is not None
    status = next(
        predicate for predicate in query.predicates if predicate.field is InventoryField.STATUS
    )
    assert status.value == expected


def test_stopped_aks_question_does_not_drop_unobserved_status_filter() -> None:
    resources = (
        *_RESOURCES,
        {
            "type": "kubernetes-cluster",
            "name": "aks-example",
            "status": "unknown",
            "location": "koreacentral",
        },
    )

    assert is_inventory_question("중지된 AKS 클러스터 이름 목록으로 보여줄래?")
    query = compile_inventory_query(
        "중지된 AKS 클러스터 이름 목록으로 보여줄래?",
        resources=resources,
    )
    assert query is not None
    by_field = {predicate.field: predicate.value for predicate in query.predicates}
    assert by_field[InventoryField.RESOURCE_TYPE] == "kubernetes-cluster"
    assert by_field[InventoryField.STATUS] == ("stopped", "deallocated")


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
