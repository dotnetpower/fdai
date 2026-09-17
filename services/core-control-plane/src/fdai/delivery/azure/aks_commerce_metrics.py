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

    if _ENTITY_NAME.fullmatch(queue_name) is None:
        raise ValueError("AKS commerce queue name must be a bounded Azure entity name")
    queue = (MetricsApiDimensionFilter("EntityName", queue_name),)
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


__all__ = [
    "aks_commerce_cosmos_queries",
    "aks_commerce_metrics_queries",
    "aks_commerce_service_bus_queries",
]
