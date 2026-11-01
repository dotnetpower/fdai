"""Deployment-bound Azure Metrics API templates for the AKS commerce scenario."""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType

from fdai.delivery.azure.metrics_api import (
    MetricsApiDimensionFilter,
    MetricsApiTemplate,
)

_ENTITY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SERVICE_BUS_TYPE = "Microsoft.ServiceBus/namespaces"
_COSMOS_TYPE = "Microsoft.DocumentDB/databaseAccounts"


def aks_commerce_service_bus_queries(queue_name: str) -> Mapping[str, MetricsApiTemplate]:
    """Return exact-queue Service Bus metric mappings for one deployment."""
    clean_queue = queue_name.strip() if isinstance(queue_name, str) else ""
    if _ENTITY_NAME.fullmatch(clean_queue) is None:
        raise ValueError("AKS commerce queue name must be a bounded Azure entity name")
    queue = (MetricsApiDimensionFilter("EntityName", clean_queue),)
    return MappingProxyType(
        {
            "stream.abandoned_messages": MetricsApiTemplate(
                "AbandonMessage",
                "Total",
                resource_type=_SERVICE_BUS_TYPE,
                dimension_filters=queue,
            ),
            "stream.active_messages": MetricsApiTemplate(
                "ActiveMessages",
                "Average",
                resource_type=_SERVICE_BUS_TYPE,
                dimension_filters=queue,
            ),
            "stream.completed_messages": MetricsApiTemplate(
                "CompleteMessage",
                "Total",
                resource_type=_SERVICE_BUS_TYPE,
                dimension_filters=queue,
            ),
            "stream.dead_letter_messages": MetricsApiTemplate(
                "DeadletteredMessages",
                "Average",
                resource_type=_SERVICE_BUS_TYPE,
                dimension_filters=queue,
            ),
            "stream.incoming_messages": MetricsApiTemplate(
                "IncomingMessages",
                "Total",
                resource_type=_SERVICE_BUS_TYPE,
                dimension_filters=queue,
            ),
        }
    )


def aks_commerce_cosmos_queries() -> Mapping[str, MetricsApiTemplate]:
    """Return account-level Cosmos DB pressure mappings."""

    return MappingProxyType(
        {
            "database.normalized_ru_consumption": MetricsApiTemplate(
                "NormalizedRUConsumption",
                "Maximum",
                resource_type=_COSMOS_TYPE,
            ),
            "database.request_count": MetricsApiTemplate(
                "TotalRequests",
                "Total",
                resource_type=_COSMOS_TYPE,
            ),
            "database.server_latency_ms": MetricsApiTemplate(
                "ServerSideLatency",
                "Average",
                resource_type=_COSMOS_TYPE,
            ),
        }
    )


def aks_commerce_metrics_queries(queue_name: str) -> Mapping[str, MetricsApiTemplate]:
    """Return the collision-free combined scenario mapping."""

    return MappingProxyType(
        {
            **aks_commerce_service_bus_queries(queue_name),
            **aks_commerce_cosmos_queries(),
        }
    )


def aks_commerce_cosmos_throttling_queries(
    collection_name: str | None = None,
) -> Mapping[str, MetricsApiTemplate]:
    """Return Cosmos DB HTTP 429 throttling and RU consumption templates."""
    extra_dims: tuple[MetricsApiDimensionFilter, ...] = ()
    if collection_name is not None:
        clean_coll = collection_name.strip()
        if _ENTITY_NAME.fullmatch(clean_coll) is None:
            raise ValueError("AKS commerce collection name must be a bounded Azure entity name")
        extra_dims = (MetricsApiDimensionFilter("CollectionName", clean_coll),)
    return MappingProxyType(
        {
            "database.throttled_requests": MetricsApiTemplate(
                "TotalRequests",
                "Total",
                resource_type=_COSMOS_TYPE,
                dimension_filters=(MetricsApiDimensionFilter("StatusCode", "429"), *extra_dims),
            ),
            "database.total_request_units": MetricsApiTemplate(
                "TotalRequestUnits",
                "Total",
                resource_type=_COSMOS_TYPE,
                dimension_filters=extra_dims,
            ),
        }
    )


__all__ = [
    "aks_commerce_cosmos_queries",
    "aks_commerce_cosmos_throttling_queries",
    "aks_commerce_metrics_queries",
    "aks_commerce_service_bus_queries",
]
