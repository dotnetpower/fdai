"""EventBus adapter for complete ordered operating-model snapshots."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass

from fdai.delivery.operating_model.json_file import operating_model_snapshot_from_mapping
from fdai.shared.providers.event_bus import EventBus, subscription
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceValidationError,
    normalize_json_value,
)
from fdai.shared.providers.operating_model import OperatingModelUpdate


@dataclass(frozen=True, slots=True)
class EventBusOperatingModelProviderConfig:
    """Validated topic binding for deployment-owned operating-model updates."""

    topic: str
    group_id: str = "fdai-operating-model"

    def __post_init__(self) -> None:
        if not self.topic.strip() or not self.group_id.strip():
            raise ValueError("operating model topic and group_id MUST be non-empty")


class EventBusOperatingModelProvider:
    """Yield bounded snapshots and dead-letter malformed records without applying them."""

    def __init__(self, *, bus: EventBus, config: EventBusOperatingModelProviderConfig) -> None:
        self._bus = bus
        self._config = config

    async def updates(
        self,
        *,
        after_cursor: str | None,
        stop: asyncio.Event,
    ) -> AsyncIterator[OperatingModelUpdate]:
        async with subscription(
            self._bus,
            self._config.topic,
            self._config.group_id,
        ) as stream:
            async for envelope in stream:
                if stop.is_set():
                    return
                try:
                    update = _decode_update(envelope.payload)
                except (ValueError, RecursionError, OntologyInstanceValidationError):
                    await self._bus.dead_letter(
                        self._config.topic,
                        envelope.key,
                        envelope.payload,
                        "operating_model_update_invalid",
                    )
                    continue
                if update.cursor == after_cursor:
                    continue
                yield update


def _decode_update(payload: Mapping[str, object]) -> OperatingModelUpdate:
    bounded = normalize_json_value(dict(payload), path="operating_model_update")
    if not isinstance(bounded, Mapping):  # pragma: no cover - dict normalizes to dict
        raise ValueError("operating model update MUST be an object")
    cursor = bounded.get("cursor")
    sequence = bounded.get("sequence")
    snapshot = bounded.get("snapshot")
    if not isinstance(cursor, str):
        raise ValueError("operating model update cursor MUST be a string")
    if isinstance(sequence, bool) or not isinstance(sequence, int):
        raise ValueError("operating model update sequence MUST be an integer")
    if not isinstance(snapshot, Mapping):
        raise ValueError("operating model update snapshot MUST be an object")
    return OperatingModelUpdate(
        cursor=cursor,
        sequence=sequence,
        snapshot=operating_model_snapshot_from_mapping(snapshot),
    )


__all__ = ["EventBusOperatingModelProvider", "EventBusOperatingModelProviderConfig"]
