"""Validate reviewed forecast history mappings exactly as runtime composition consumes them.

Runtime composition and the Settings projection share this parser, so a configuration that the
runtime would reject can never appear bound or opted in. Parsing grants no coverage, scoring, or
execution authority.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from fdai.core.detection.forecast_history import (
    ForecastHistoryBinding,
    group_forecast_history_bindings,
)
from fdai.core.detection.forecast_history_producer import validate_forecast_history_producer
from fdai.core.detection.forecast_history_source import ForecastHistoryProducerBinding
from fdai.delivery.forecast_history_sources import (
    FORECAST_ACTION_HISTORY_SOURCE_IDENTITY,
    FORECAST_ACTION_HISTORY_SOURCE_REVISION,
    FORECAST_CHANGE_HISTORY_SOURCE_IDENTITY,
    FORECAST_CHANGE_HISTORY_SOURCE_REVISION,
    FORECAST_LIFECYCLE_HISTORY_SOURCE_IDENTITY,
    FORECAST_LIFECYCLE_HISTORY_SOURCE_REVISION,
)

FORECAST_HISTORY_PRODUCER_SOURCES = {
    "actions": (FORECAST_ACTION_HISTORY_SOURCE_IDENTITY, FORECAST_ACTION_HISTORY_SOURCE_REVISION),
    "changes": (FORECAST_CHANGE_HISTORY_SOURCE_IDENTITY, FORECAST_CHANGE_HISTORY_SOURCE_REVISION),
    "resource_lifecycle": (
        FORECAST_LIFECYCLE_HISTORY_SOURCE_IDENTITY,
        FORECAST_LIFECYCLE_HISTORY_SOURCE_REVISION,
    ),
}
_MAX_BYTES = 262_144


@dataclass(frozen=True, slots=True)
class ForecastHistoryConfiguration:
    """Reviewed collector mappings plus each producer paired with its exact collector mapping."""

    bindings: tuple[ForecastHistoryBinding, ...]
    producers: tuple[tuple[ForecastHistoryProducerBinding, ForecastHistoryBinding], ...]


def parse_forecast_history_configuration(
    *, bindings_json: str, producers_json: str | None = None
) -> ForecastHistoryConfiguration:
    """Parse bounded unique-field JSON and apply every structural rule runtime composition uses."""
    bindings = tuple(
        ForecastHistoryBinding.model_validate(item) for item in _array(bindings_json, "source")
    )
    group_forecast_history_bindings(bindings)
    if producers_json is None or not producers_json.strip():
        return ForecastHistoryConfiguration(bindings, ())
    reviewed = {(item.access_scope_digest, item.target_ref, item.kind): item for item in bindings}
    producers: list[tuple[ForecastHistoryProducerBinding, ForecastHistoryBinding]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in _array(producers_json, "producer"):
        binding = ForecastHistoryProducerBinding.model_validate(item)
        identity = (binding.access_scope_digest, binding.target_ref, binding.kind)
        history = reviewed.get(identity)
        if history is None:
            raise ValueError("forecast history producer has no reviewed collector mapping")
        if identity in seen:
            raise ValueError("forecast history producer is duplicated for one target")
        seen.add(identity)
        source = FORECAST_HISTORY_PRODUCER_SOURCES.get(binding.kind)
        if source is None:
            raise ValueError(f"forecast history {binding.kind} producer source is unavailable")
        if (history.source_identity, history.source_revision) != source:
            raise ValueError("forecast history producer source identity is not the reviewed one")
        validate_forecast_history_producer(binding, history)
        producers.append((binding, history))
    return ForecastHistoryConfiguration(bindings, tuple(producers))


def _array(raw: str, name: str) -> list[object]:
    if len(raw.encode()) > _MAX_BYTES:
        raise ValueError(f"forecast history {name} mappings exceed the byte limit")
    decoded = json.loads(raw, object_pairs_hook=_unique_fields)
    if not isinstance(decoded, list) or not 1 <= len(decoded) <= 256:
        raise ValueError(f"forecast history {name} mappings MUST be a bounded array")
    return decoded


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("forecast history mappings contain a duplicate field")
        result[name] = value
    return result


__all__ = [
    "FORECAST_HISTORY_PRODUCER_SOURCES",
    "ForecastHistoryConfiguration",
    "parse_forecast_history_configuration",
]
