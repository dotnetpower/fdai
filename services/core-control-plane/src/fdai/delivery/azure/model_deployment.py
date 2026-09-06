"""Read-only projection helpers for Azure AI model deployment inventory."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MODEL_DEPLOYMENT_RESOURCE_TYPE = "llm-model-deployment"


def model_deployment_summary(row: Mapping[str, Any]) -> dict[str, object]:
    """Lift bounded model identity and SKU facts without deriving throughput."""

    summary: dict[str, object] = {}
    properties = row.get("properties")
    model = properties.get("model") if isinstance(properties, Mapping) else None
    sku = row.get("sku")
    for container, source_key, target_key in (
        (model, "name", "model_name"),
        (model, "version", "model_version"),
        (model, "format", "model_format"),
        (properties, "provisioningState", "provisioning_state"),
        (sku, "name", "sku_name"),
    ):
        value = container.get(source_key) if isinstance(container, Mapping) else None
        if isinstance(value, str) and value.strip() and len(value) <= 256:
            summary[target_key] = value
    capacity = sku.get("capacity") if isinstance(sku, Mapping) else None
    if isinstance(capacity, int) and not isinstance(capacity, bool) and capacity >= 0:
        summary["capacity_units"] = capacity
    return summary


__all__ = ["MODEL_DEPLOYMENT_RESOURCE_TYPE", "model_deployment_summary"]
