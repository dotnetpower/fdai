"""Local inventory-cache invalidation after durable change projection."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

InventoryDeltaProjector = Callable[[Mapping[str, Any]], Awaitable[Any]]
_LOGGER = logging.getLogger(__name__)


class InvalidatingInventoryDeltaProjector:
    """Advance a local invalidation marker after the durable projector succeeds."""

    def __init__(self, *, inner: InventoryDeltaProjector, marker_path: Path) -> None:
        self._inner = inner
        self._marker_path = marker_path

    async def __call__(self, payload: Mapping[str, Any]) -> Any:
        result = await self._inner(payload)
        if not _contains_inventory_change(payload):
            return result
        try:
            await asyncio.to_thread(_advance_marker, self._marker_path)
        except OSError as exc:
            _LOGGER.warning(
                "inventory_cache_invalidation_marker_failed",
                extra={"error_type": type(exc).__name__},
            )
        return result


def _contains_inventory_change(payload: Mapping[str, Any]) -> bool:
    if isinstance(payload.get("inventory_change"), Mapping):
        return True
    nested = payload.get("payload")
    return isinstance(nested, Mapping) and isinstance(nested.get("inventory_change"), Mapping)


def _advance_marker(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            stream.write("inventory.resource_changed\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = ["InvalidatingInventoryDeltaProjector"]
