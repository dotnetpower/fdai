import pytest
from fdai.delivery.azure.aks_commerce_metrics import (
    aks_commerce_cosmos_queries,
    aks_commerce_service_bus_queries,
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
