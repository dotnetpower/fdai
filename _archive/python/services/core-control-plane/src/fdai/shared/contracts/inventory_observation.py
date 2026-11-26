"""Bounded transport contract for complete promoted inventory observations."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

INVENTORY_OBSERVATION_EVENT_TYPE = "inventory.resource_observed"
INVENTORY_OBSERVATION_SOURCE = "fdai.delivery.inventory_configuration_events"
INVENTORY_CHANGE_EVENT_TYPE = "inventory.resource_changed"
INVENTORY_CHANGE_SOURCE = "fdai.delivery.azure.arg_resource_changes"
INVENTORY_CHANGE_SIGNAL_KIND = "azure.resource_graph_change_feed"
MAX_INVENTORY_OBSERVATION_BYTES = 131_072
MAX_INVENTORY_OBSERVATION_DEPTH = 24
MAX_INVENTORY_OBSERVATION_KEYS = 256
MAX_INVENTORY_OBSERVATION_LIST_ITEMS = 512
MAX_INVENTORY_OBSERVATION_STRING_CHARS = 4_096

_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")


class InventoryObservationTransportError(ValueError):
    """A complete inventory observation exceeded or violated its transport contract."""

    def __init__(self, reason_code: str, *, field: str) -> None:
        super().__init__(f"inventory observation transport rejected: {reason_code}")
        self.reason_code = reason_code
        self.field = field


def is_inventory_observation_event(value: Mapping[str, Any]) -> bool:
    """Return whether ``value`` claims the exact complete-inventory event identity."""
    return (
        value.get("event_type") == INVENTORY_OBSERVATION_EVENT_TYPE
        and value.get("source") == INVENTORY_OBSERVATION_SOURCE
    )


def is_inventory_change_event(value: Mapping[str, Any]) -> bool:
    """Return whether ``value`` claims the exact hydrated provider change-feed identity."""
    payload = value.get("payload")
    return (
        value.get("event_type") == INVENTORY_CHANGE_EVENT_TYPE
        and value.get("source") == INVENTORY_CHANGE_SOURCE
        and isinstance(payload, Mapping)
        and payload.get("signal_kind") == INVENTORY_CHANGE_SIGNAL_KIND
    )


def validate_inventory_change_event(value: Mapping[str, Any]) -> None:
    """Validate one hydrated provider change against the same finite transport bounds."""
    payload = value.get("payload")
    change = payload.get("inventory_change") if isinstance(payload, Mapping) else None
    resource = change.get("resource") if isinstance(change, Mapping) else None
    if (
        not is_inventory_change_event(value)
        or not isinstance(resource, Mapping)
        or not isinstance(resource.get("props"), Mapping)
    ):
        raise InventoryObservationTransportError("inventory_observation_shape", field="payload")
    _validate_bounded_event(value)


def validate_inventory_observation_event(value: Mapping[str, Any]) -> None:
    """Validate one complete inventory Event against finite transport bounds."""
    if not is_inventory_observation_event(value):
        raise InventoryObservationTransportError(
            "inventory_observation_identity",
            field="event_type",
        )
    payload = value.get("payload")
    if not isinstance(payload, Mapping):
        raise InventoryObservationTransportError(
            "inventory_observation_shape",
            field="payload",
        )
    resource = payload.get("resource")
    observation = payload.get("inventory_observation")
    if (
        payload.get("signal_kind") != "inventory.full_reconciliation"
        or not isinstance(resource, Mapping)
        or not isinstance(resource.get("props"), Mapping)
        or not isinstance(observation, Mapping)
        or observation.get("kind") != "full"
        or observation.get("properties_complete") is not True
        or _SHA256.fullmatch(str(observation.get("generation_digest") or "")) is None
        or not str(observation.get("scope_ref") or "").strip()
        or resource.get("resource_id") != value.get("resource_ref")
        or not str(resource.get("type") or "").strip()
    ):
        raise InventoryObservationTransportError(
            "inventory_observation_shape",
            field="payload",
        )
    _validate_bounded_event(value)


def _validate_bounded_event(value: Mapping[str, Any]) -> None:
    _validate_value(value, path="raw")
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise InventoryObservationTransportError(
            "inventory_observation_json",
            field="raw",
        ) from exc
    if len(encoded) > MAX_INVENTORY_OBSERVATION_BYTES:
        raise InventoryObservationTransportError(
            "raw_payload_too_large",
            field="raw",
        )


def _validate_value(value: Any, *, path: str, depth: int = 0) -> None:
    if depth > MAX_INVENTORY_OBSERVATION_DEPTH:
        raise InventoryObservationTransportError("raw_depth_exceeded", field=path)
    if value is None or isinstance(value, bool | int | float):
        return
    if isinstance(value, str):
        if len(value) > MAX_INVENTORY_OBSERVATION_STRING_CHARS:
            raise InventoryObservationTransportError("invalid_string", field=path)
        return
    if isinstance(value, Mapping):
        if len(value) > MAX_INVENTORY_OBSERVATION_KEYS:
            raise InventoryObservationTransportError("raw_object_too_large", field=path)
        for key, nested in value.items():
            if not isinstance(key, str):
                raise InventoryObservationTransportError("invalid_field_name", field=path)
            if len(key) > MAX_INVENTORY_OBSERVATION_STRING_CHARS:
                raise InventoryObservationTransportError("invalid_field_name", field=path)
            _validate_value(nested, path=f"{path}.{key}", depth=depth + 1)
        return
    if isinstance(value, list | tuple):
        if len(value) > MAX_INVENTORY_OBSERVATION_LIST_ITEMS:
            raise InventoryObservationTransportError("raw_list_too_large", field=path)
        for index, nested in enumerate(value):
            _validate_value(nested, path=f"{path}[{index}]", depth=depth + 1)
        return
    raise InventoryObservationTransportError("invalid_type", field=path)


__all__ = [
    "INVENTORY_OBSERVATION_EVENT_TYPE",
    "INVENTORY_OBSERVATION_SOURCE",
    "InventoryObservationTransportError",
    "INVENTORY_CHANGE_EVENT_TYPE",
    "INVENTORY_CHANGE_SIGNAL_KIND",
    "INVENTORY_CHANGE_SOURCE",
    "MAX_INVENTORY_OBSERVATION_BYTES",
    "MAX_INVENTORY_OBSERVATION_DEPTH",
    "MAX_INVENTORY_OBSERVATION_KEYS",
    "MAX_INVENTORY_OBSERVATION_LIST_ITEMS",
    "MAX_INVENTORY_OBSERVATION_STRING_CHARS",
    "is_inventory_change_event",
    "is_inventory_observation_event",
    "validate_inventory_change_event",
    "validate_inventory_observation_event",
]
