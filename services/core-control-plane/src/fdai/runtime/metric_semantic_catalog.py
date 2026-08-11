"""Fail-closed runtime loader for the reviewed metric semantic registry."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from fdai.core.ontology_platform.metric_semantics import (
    MetricAggregation,
    MetricSemanticDefinition,
    MetricSemanticRegistry,
)

_ALLOWED_KEYS = frozenset(
    {
        "concept_id",
        "provider_metric",
        "canonical_unit",
        "aggregation",
        "description",
        "monotonic",
    }
)


def load_metric_semantic_registry(path: Path) -> MetricSemanticRegistry:
    """Load one exact, alias-free metric concept catalog."""

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError("metric semantic registry is unavailable or invalid") from exc
    if not isinstance(raw, Mapping) or set(raw) != {"schema_version", "definitions"}:
        raise ValueError("metric semantic registry top level is invalid")
    if raw["schema_version"] != "1.0.0":
        raise ValueError("metric semantic registry schema_version is unsupported")
    definitions = raw["definitions"]
    if not isinstance(definitions, Sequence) or isinstance(definitions, (str, bytes)):
        raise ValueError("metric semantic definitions MUST be an array")
    return MetricSemanticRegistry.build(tuple(_definition(item) for item in definitions))


def _definition(raw: object) -> MetricSemanticDefinition:
    if not isinstance(raw, Mapping) or set(raw) != _ALLOWED_KEYS:
        raise ValueError("metric semantic definition fields are invalid")
    values: dict[str, Any] = dict(raw)
    if not isinstance(values["monotonic"], bool):
        raise ValueError("metric semantic monotonic MUST be boolean")
    try:
        aggregation = MetricAggregation(str(values["aggregation"]))
    except ValueError as exc:
        raise ValueError("metric semantic aggregation is unsupported") from exc
    return MetricSemanticDefinition(
        concept_id=_string(values, "concept_id"),
        provider_metric=_string(values, "provider_metric"),
        canonical_unit=_string(values, "canonical_unit"),
        aggregation=aggregation,
        description=_string(values, "description"),
        monotonic=values["monotonic"],
    )


def _string(values: Mapping[str, Any], key: str) -> str:
    value = values[key]
    if not isinstance(value, str):
        raise ValueError(f"metric semantic {key} MUST be a string")
    return value


__all__ = ["load_metric_semantic_registry"]
