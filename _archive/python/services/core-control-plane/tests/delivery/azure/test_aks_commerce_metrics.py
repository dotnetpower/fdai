import pytest
from fdai.delivery.azure.aks_commerce_metrics import (
    aks_commerce_cosmos_queries,
    aks_commerce_cosmos_throttling_queries,
    aks_commerce_service_bus_queries,
)
from fdai.delivery.azure.host_cpu_queries import vm_and_vmss_host_metric_templates
from fdai.delivery.azure.metrics_api_queries import (
    azure_extended_platform_metrics_api_queries,
    resolve_azure_metrics_api_template,
)


def test_service_bus_queries_bind_one_exact_queue_dimension() -> None:
    queries = aks_commerce_service_bus_queries("orders")

    assert queries["stream.active_messages"].azure_metric_name == "ActiveMessages"
    assert queries["stream.active_messages"].resource_type == "Microsoft.ServiceBus/namespaces"
    assert queries["stream.active_messages"].dimension_filters[0].name == "EntityName"
    assert queries["stream.active_messages"].dimension_filters[0].value == "orders"
    assert queries["stream.dead_letter_messages"].azure_metric_name == "DeadletteredMessages"


def test_invalid_queue_name_fails_before_query_construction() -> None:
    with pytest.raises(ValueError, match="queue name"):
        aks_commerce_service_bus_queries("orders or EntityName eq other")


def test_cosmos_queries_cover_ru_request_and_latency_pressure() -> None:
    queries = aks_commerce_cosmos_queries()

    assert set(queries) == {
        "database.normalized_ru_consumption",
        "database.request_count",
        "database.server_latency_ms",
    }


def test_extended_platform_and_cosmos_throttling_templates() -> None:
    extended = azure_extended_platform_metrics_api_queries(include_defaults=False)
    assert "postgresql.cpu_percent" in extended
    assert "redis.server_load" in extended
    assert "key_vault.service_api_latency_ms" in extended
    assert "event_hub.throttled_requests" in extended
    assert "storage.availability" in extended
    resolved = resolve_azure_metrics_api_template("POSTGRESQL.CPU_PERCENT")
    assert resolved is not None and resolved.azure_metric_name == "cpu_percent"

    host_templates = vm_and_vmss_host_metric_templates()
    assert "vm.available_memory_bytes" in host_templates
    assert "vm.disk_read_iops" in host_templates

    throttling = aks_commerce_cosmos_throttling_queries("orders-coll")
    assert throttling["database.throttled_requests"].dimension_filters[0].value == "429"
    assert throttling["database.throttled_requests"].dimension_filters[1].value == "orders-coll"
