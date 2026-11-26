"""Durable StateStore adapter for provider-rendered shadow notifications."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai.core.notifications import ShadowDeliveryConflictError, ShadowDeliveryRecord
from fdai.shared.providers.state_store import StateStore

_STATE_PREFIX = "notification-shadow:"


@dataclass(frozen=True, slots=True)
class StateStoreShadowDeliveryRecorder:
    """Persist one first-write-wins shadow record under its stable record id."""

    state_store: StateStore

    async def record(self, entry: ShadowDeliveryRecord) -> None:
        key = f"{_STATE_PREFIX}{entry.record_id}"
        value = _serialize(entry)
        if await self.state_store.write_state_if_absent(key, value):
            return
        existing = await self.state_store.read_state(key)
        if existing is None:
            raise RuntimeError("shadow delivery state disappeared after duplicate detection")
        if _semantic_value(existing) != _semantic_value(value):
            raise ShadowDeliveryConflictError(
                "shadow delivery id already exists with different bounded content"
            )


def _serialize(entry: ShadowDeliveryRecord) -> dict[str, Any]:
    envelope = entry.envelope
    rendered = entry.rendered_payload
    return {
        "schema_version": 1,
        "record_id": entry.record_id,
        "channel_id": entry.channel_id,
        "category": entry.category,
        "trust_tier": entry.trust_tier.value,
        "correlation_id": entry.correlation_id,
        "audit_id": entry.audit_id,
        "recorded_at": entry.recorded_at.isoformat(),
        "envelope": {
            "title": envelope.title,
            "body_markdown": envelope.body_markdown,
            "severity": envelope.severity.value,
            "links": [{"label": link.label, "url": link.url} for link in envelope.links],
            "metadata": dict(envelope.metadata),
        },
        "rendered_payload": (
            {
                "content_type": rendered.content_type,
                "body_base64": base64.b64encode(rendered.body).decode("ascii"),
            }
            if rendered is not None
            else None
        ),
    }


def _semantic_value(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(value)
    normalized.pop("recorded_at", None)
    return normalized


__all__ = [
    "ShadowDeliveryConflictError",
    "StateStoreShadowDeliveryRecorder",
]
