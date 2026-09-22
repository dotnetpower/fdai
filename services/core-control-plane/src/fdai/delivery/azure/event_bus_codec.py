"""Payload codec helpers for the Azure Kafka event-bus adapter."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

_LOGGER = logging.getLogger("fdai.delivery.azure.event_bus")


def encode_payload(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(payload), separators=(",", ":"), sort_keys=True).encode("utf-8")


def decode_payload(
    value: bytes | None,
    *,
    topic: str = "",
    key: str = "",
) -> Mapping[str, Any]:
    """Decode malformed payloads into an explicit fail-closed sentinel."""

    if value is None:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        _LOGGER.warning(
            "event_bus_decode_error",
            extra={"topic": topic, "key": key, "bytes": len(value)},
        )
        return {"_raw": value.decode("utf-8", errors="replace"), "_decode_error": True}
    if not isinstance(parsed, dict):
        _LOGGER.warning(
            "event_bus_non_object_payload",
            extra={"topic": topic, "key": key, "type": type(parsed).__name__},
        )
        return {"_wrapped": parsed, "_decode_error": True}
    return parsed


def decode_key(value: bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace")


__all__ = ["decode_key", "decode_payload", "encode_payload"]
