"""Bounded Kubernetes capacity evidence for operational event payloads."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

CapacityQuery = Callable[[str], Awaitable[Mapping[str, Any]]]


@dataclass(frozen=True, slots=True)
class KubernetesCapacityEventEvidenceCollector:
    """Adapt one namespace capacity query to Heimdall's read-only hook."""

    query: CapacityQuery
    max_bytes: int = 262_144

    def __post_init__(self) -> None:
        if self.max_bytes < 1:
            raise ValueError("operational evidence byte limit MUST be positive")

    async def collect_payload(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        namespace = _namespace(payload)
        if namespace is None:
            return {}
        try:
            capacity = dict(await self.query(namespace))
            if len(_encode(capacity)) > self.max_bytes:
                return _entry("unavailable", reason="response_over_limit")
        except Exception:  # noqa: BLE001 - isolate the read-only provider boundary
            return _entry("unavailable", reason="provider_error")
        return {
            "observe.kubernetes.capacity": {
                "status": "available",
                "payload": capacity,
            }
        }


def _namespace(payload: Mapping[str, Any]) -> str | None:
    if payload.get("resource_type") != "kubernetes.namespace":
        return None
    resource_ref = payload.get("resource_id") or payload.get("resource_ref")
    prefix = "kubernetes.namespace/"
    if not isinstance(resource_ref, str) or not resource_ref.startswith(prefix):
        return None
    namespace = resource_ref[len(prefix) :]
    return namespace if namespace else None


def _entry(status: str, *, reason: str) -> dict[str, dict[str, str]]:
    return {"observe.kubernetes.capacity": {"status": status, "reason": reason}}


def _encode(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


__all__ = ["CapacityQuery", "KubernetesCapacityEventEvidenceCollector"]
