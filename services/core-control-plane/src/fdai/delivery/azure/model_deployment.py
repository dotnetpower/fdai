"""Read-only projection helpers for Azure AI model deployment inventory."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

MODEL_DEPLOYMENT_RESOURCE_TYPE = "llm-model-deployment"
_TOKEN_RATE_KEYS = frozenset(
    {
        "token",
        "tokens",
        "tokenperminute",
        "tokensperminute",
        "tpm",
    }
)
_RATE_KEY_SEPARATOR = re.compile(r"[^a-z0-9]+")
_MAX_RATE_RULES = 64
_MAX_RATE_KEY_CHARS = 128


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
    current_capacity = _current_capacity_units(properties)
    if current_capacity is not None:
        summary["current_capacity_units"] = current_capacity
        if isinstance(capacity, int) and not isinstance(capacity, bool):
            summary["capacity_transitioning"] = current_capacity != capacity
    capacity_tpm = _tokens_per_minute(properties)
    if capacity_tpm is not None:
        summary["capacity_tpm"] = capacity_tpm
        summary["capacity_tpm_source"] = "properties.rateLimits"
    return summary


def _current_capacity_units(properties: object) -> int | None:
    if not isinstance(properties, Mapping):
        return None
    current = properties.get("currentCapacity")
    if not isinstance(current, int) or isinstance(current, bool):
        scale_settings = properties.get("scaleSettings")
        current = (
            scale_settings.get("activeCapacity") if isinstance(scale_settings, Mapping) else None
        )
    return (
        current
        if isinstance(current, int) and not isinstance(current, bool) and current >= 0
        else None
    )


def _tokens_per_minute(properties: object) -> int | None:
    if not isinstance(properties, Mapping):
        return None
    rate_limits = properties.get("rateLimits")
    if not isinstance(rate_limits, list) or len(rate_limits) > _MAX_RATE_RULES:
        return None
    observed: set[int] = set()
    for rule in rate_limits:
        if not isinstance(rule, Mapping):
            continue
        key = rule.get("key")
        if not isinstance(key, str) or len(key) > _MAX_RATE_KEY_CHARS:
            continue
        if _RATE_KEY_SEPARATOR.sub("", key.casefold()) not in _TOKEN_RATE_KEYS:
            continue
        count = rule.get("count")
        renewal_period = rule.get("renewalPeriod")
        if (
            not isinstance(count, int | float)
            or isinstance(count, bool)
            or not isinstance(renewal_period, int | float)
            or isinstance(renewal_period, bool)
            or not math.isfinite(float(count))
            or not math.isfinite(float(renewal_period))
            or count <= 0
            or renewal_period <= 0
        ):
            return None
        per_minute = float(count) * 60 / float(renewal_period)
        if not per_minute.is_integer() or per_minute > 2_147_483_647:
            return None
        observed.add(int(per_minute))
    return next(iter(observed)) if len(observed) == 1 else None


__all__ = ["MODEL_DEPLOYMENT_RESOURCE_TYPE", "model_deployment_summary"]
