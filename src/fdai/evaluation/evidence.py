"""Bounded read-only evidence collection for evaluation capabilities."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from fdai_evaluation_sdk import EvaluationTask, SideEffectClass


class EvaluationEvidenceProvider(Protocol):
    """Collect one capability's untrusted evidence for a bounded task."""

    async def collect(self, task: EvaluationTask) -> Mapping[str, Any]: ...


class EvaluationEvidenceCollector(Protocol):
    """Collect only capabilities retained by FDAI authority attenuation."""

    async def collect(
        self,
        *,
        task: EvaluationTask,
        allowed_capabilities: frozenset[str],
    ) -> Mapping[str, Any]: ...


class NoopEvaluationEvidenceCollector:
    """Backward-compatible collector used when no evidence providers are bound."""

    async def collect(
        self,
        *,
        task: EvaluationTask,
        allowed_capabilities: frozenset[str],
    ) -> Mapping[str, Any]:
        del task, allowed_capabilities
        return {}


@dataclass(frozen=True, slots=True)
class BoundedEvaluationEvidenceCollector:
    """Normalize provider output under deterministic byte and capability limits."""

    providers: Mapping[str, EvaluationEvidenceProvider]
    max_item_bytes: int = 262_144
    max_total_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        if self.max_item_bytes < 1 or self.max_total_bytes < self.max_item_bytes:
            raise ValueError("evaluation evidence byte limits MUST be positive and ordered")

    async def collect(
        self,
        *,
        task: EvaluationTask,
        allowed_capabilities: frozenset[str],
    ) -> Mapping[str, Any]:
        requested = sorted(
            capability.capability_id
            for capability in task.requested_capabilities
            if capability.capability_id in allowed_capabilities
            and capability.side_effect_class is SideEffectClass.OBSERVE
        )
        evidence: dict[str, Any] = {}
        total_bytes = 0
        for capability_id in requested:
            provider = self.providers.get(capability_id)
            entry: dict[str, Any]
            if provider is None:
                entry = _unavailable("provider_unconfigured")
            else:
                try:
                    payload = dict(await provider.collect(task))
                    encoded = _encode(payload)
                except Exception:  # noqa: BLE001 - isolate the untrusted provider boundary
                    entry = _unavailable("provider_error")
                else:
                    if len(encoded) > self.max_item_bytes:
                        entry = _unavailable("response_over_limit")
                    else:
                        entry = {"status": "available", "payload": payload}
            entry_bytes = len(_encode(entry))
            if total_bytes + entry_bytes > self.max_total_bytes:
                evidence[capability_id] = _unavailable("collection_over_limit")
                continue
            evidence[capability_id] = entry
            total_bytes += entry_bytes
        return evidence


def _unavailable(reason: str) -> dict[str, str]:
    return {"status": "unavailable", "reason": reason}


def _encode(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


__all__ = [
    "BoundedEvaluationEvidenceCollector",
    "EvaluationEvidenceCollector",
    "EvaluationEvidenceProvider",
    "NoopEvaluationEvidenceCollector",
]
