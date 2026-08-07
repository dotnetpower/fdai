from __future__ import annotations

import itertools
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from fdai.delivery.operator_api.application.conversation.capabilities.inventory import (
    InventoryResourceTypeResolver,
)
from fdai.delivery.operator_api.application.conversation.capabilities.inventory.compiler import (
    compile_inventory_query,
    inventory_query_evidence_authorities,
    is_inventory_question,
)
from fdai.delivery.operator_api.application.conversation.capabilities.inventory.query import (
    InventoryField,
    InventoryOperator,
    InventoryQueryGrouping,
    InventoryQueryKind,
    InventoryQueryScope,
    InventoryQuerySource,
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


def test_scope_counts_compile_without_resource_group_narrowing() -> None:
    query = compile_inventory_query(
        "How many resources and resource groups are in the managed scope?",
        resources=_RESOURCES,
    )

    assert query is not None
    assert query.kind is InventoryQueryKind.SCOPE_COUNTS
    assert query.predicates == ()


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


@pytest.mark.parametrize(
    "prompt",
    [
        "실행중인 vm",
        "현재 구독에서 실행중인 vm 목록",
        "지금 설정된 Azure 범위 안에서 실제로 돌아가고 있는, 그러니까 켜져서 살아있는 "
        "가상머신들만 골라서 각 항목의 현재 상태값과 함께 읽기 전용 인벤토리 근거로 "
        "알려주시겠어요?",
        "가상머신 중에 켜져 있는 것만 알려줘.",
        "가상머신들 중에 돌아가고 있는 애들만 보여줘.",
    ],
)
def test_colloquial_running_vm_question_resolves_type_and_state(prompt: str) -> None:
    # Korean often writes the VM compound noun without the formal space
    # ("가상머신" instead of "가상 머신") and describes a running instance with
    # verb-conjugated slang ("켜져서", "돌아가고 있는") rather than the noun form
    # ("켜짐"/"가동 중"). Both spellings and conjugations must resolve to the
    # same canonical resource type and running state.
    query = compile_inventory_query(prompt, resources=_RESOURCES)

    assert query is not None
    by_field = {predicate.field: predicate.value for predicate in query.predicates}
    assert by_field[InventoryField.RESOURCE_TYPE] == "compute.vm"
    assert by_field[InventoryField.STATUS] == "vm running"


def test_subscription_running_vm_question_preserves_subscription_scope() -> None:
    query = compile_inventory_query(
        "현재 구독에서 실행중인 vm 목록",
        resources=_RESOURCES,
    )

    assert query is not None
    assert query.scope.value == "subscription"


@pytest.mark.parametrize(
    "prompt",
    [
        "Which virtual machines are running, stopped, or deallocated?",
        "Group all virtual machines by running, stopped, and deallocated state.",
        "실행 중, 중지됨, 할당 해제 상태별로 가상 머신을 보여줘.",
        "VM들 지금 켜짐, 중지, 할당 해제별로 나눠줘.",
    ],
)
def test_multiple_vm_states_preserve_unobserved_predicates_without_overlap(prompt: str) -> None:
    query = compile_inventory_query(prompt, resources=_RESOURCES)

    assert query is not None
    assert query.group_by is InventoryQueryGrouping.STATUS
    status = next(
        predicate for predicate in query.predicates if predicate.field is InventoryField.STATUS
    )
    assert status.value == ("vm deallocated", "vm running", "stopped")
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


def test_storage_health_question_preserves_unavailable_and_degraded_states() -> None:
    query = compile_inventory_query(
        "사용 불가능하거나 성능이 저하된 스토리지 계정이 있어?",
    )

    assert query is not None
    by_field = {predicate.field: predicate.value for predicate in query.predicates}
    assert by_field[InventoryField.RESOURCE_TYPE] == "object-storage"
    assert by_field[InventoryField.STATUS] == ("degraded", "unavailable")
    assert query.group_by is InventoryQueryGrouping.STATUS
    assert [(group.id, group.values) for group in query.status_groups] == [
        ("degraded", ("degraded",)),
        ("unavailable", ("unavailable",)),
    ]


def test_cache_service_health_question_selects_both_cache_provider_types() -> None:
    for prompt in (
        "Are any cache services unavailable or under memory pressure?",
        "Check whether any cache is down or experiencing high memory pressure.",
    ):
        query = compile_inventory_query(prompt)

        assert query is not None
        by_field = {predicate.field: predicate.value for predicate in query.predicates}
        assert by_field[InventoryField.RESOURCE_TYPE] == ("cache", "redis-enterprise")
        assert by_field[InventoryField.STATUS] == "unavailable"


def test_inventory_coverage_cohort_ignores_status_words() -> None:
    for prompt in (
        "What inventory types did you check, skip, or fail to read?",
        "Separate inventory types into checked, skipped, and failed-to-read groups.",
        "Which resource types were inspected, omitted, or unavailable to the inventory reader?",
    ):
        query = compile_inventory_query(prompt)

        assert query is not None
        assert query.kind is InventoryQueryKind.INVENTORY_COVERAGE
        assert all(predicate.field is not InventoryField.STATUS for predicate in query.predicates)
        assert inventory_query_evidence_authorities(prompt) == ()


@pytest.mark.parametrize(
    ("prompt", "expected_kind"),
    (
        ("이 구독에서 관리 중인 리소스를 유형별로 요약해줘.", InventoryQueryKind.TYPES),
        ("현재 구독의 관리 리소스를 종류별 개수로 정리해줘.", InventoryQueryKind.TYPES),
        ("이 구독에 있는 리소스를 유형 기준으로 요약해줘.", InventoryQueryKind.TYPES),
        (
            "How many resources and resource groups are in the managed scope?",
            InventoryQueryKind.SCOPE_COUNTS,
        ),
        (
            "Count the resources and resource groups in the current managed scope.",
            InventoryQueryKind.SCOPE_COUNTS,
        ),
        (
            "What are the total resource and resource-group counts for this managed scope?",
            InventoryQueryKind.SCOPE_COUNTS,
        ),
    ),
)
def test_inventory_summary_and_scope_count_cohorts_keep_specific_kind(
    prompt: str,
    expected_kind: InventoryQueryKind,
) -> None:
    query = compile_inventory_query(prompt)

    assert query is not None
    assert query.kind is expected_kind


def test_app_service_question_separates_not_running_and_not_ready() -> None:
    query = compile_inventory_query(
        "실행 중이 아니거나 준비되지 않은 앱 서비스를 보여줘.",
    )

    assert query is not None
    by_field = {predicate.field: predicate.value for predicate in query.predicates}
    assert by_field[InventoryField.RESOURCE_TYPE] == "compute.web-app"
    assert by_field[InventoryField.STATUS] == (
        "stopped",
        "deallocated",
        "failed",
        "degraded",
        "unavailable",
    )
    assert [(group.id, group.values) for group in query.status_groups] == [
        ("inactive", ("stopped", "deallocated")),
        ("not ready", ("failed", "degraded", "unavailable")),
    ]


def test_function_or_container_application_group_is_bounded() -> None:
    query = compile_inventory_query(
        "Which function or container applications are not ready?",
    )

    assert query is not None
    by_field = {predicate.field: predicate.value for predicate in query.predicates}
    assert by_field[InventoryField.RESOURCE_TYPE] == (
        "compute.container-app",
        "compute.function",
    )
    assert by_field[InventoryField.STATUS] == ("failed", "degraded", "unavailable")
    assert compile_inventory_query("What is a function?") is None


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


def test_today_evening_shutdown_compiles_to_pinned_schedule_query() -> None:
    query = compile_inventory_query(
        "오늘 저녁에 꺼지는 vm은?",
        now=datetime(2026, 8, 5, 3, 0, tzinfo=UTC),
    )

    assert query is not None
    assert query.kind is InventoryQueryKind.SCHEDULED_SHUTDOWN
    assert query.scope is InventoryQueryScope.SUBSCRIPTION
    assert query.to_dict()["schedule_window"] == "today_evening"
    assert query.to_dict()["reference_time"] == "2026-08-05T03:00:00+00:00"
    assert query.to_dict()["predicates"] == [
        {
            "field": "resource_type",
            "operator": "eq",
            "value": "compute.vm-shutdown-schedule",
        }
    ]


@pytest.mark.parametrize(
    "prompt",
    [
        "stop the VM",
        "VM을 중지해줘",
        "create a resource group",
        "리소스를 삭제해주세요",
        "why is the database slow?",
        "why is this unavailable storage account?",
        "이 unavailable 스토리지 계정의 원인이 뭐야?",
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
