"""Local inventory-cache invalidation after durable change projection."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import tempfile
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

InventoryDeltaProjector = Callable[[Mapping[str, Any]], Awaitable[Any]]
_LOGGER = logging.getLogger(__name__)


def inventory_cache_path(
    *,
    repo_root: Path,
    subscription_id: str,
    azure_config_dir: str | None,
) -> tuple[Path, str]:
    """Return a non-identifying cache path and its account-scope fingerprint."""
    normalized_subscription = subscription_id.strip()
    if not normalized_subscription:
        raise ValueError("subscription_id MUST NOT be empty")
    profile = (
        str(Path(azure_config_dir).expanduser().resolve(strict=False))
        if azure_config_dir
        else "<default>"
    )
    fingerprint = hashlib.sha256(f"{profile}\0{normalized_subscription}".encode()).hexdigest()
    return repo_root / ".fdai" / "cache" / "inventory" / f"{fingerprint}.json", fingerprint


def inventory_invalidation_path(cache_path: Path) -> Path:
    """Return the marker path paired with one account-scoped cache file."""
    return cache_path.with_suffix(".invalidated")


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
    os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            stream.write("inventory.resource_changed\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory_descriptor = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "InvalidatingInventoryDeltaProjector",
    "inventory_cache_path",
    "inventory_invalidation_path",
]
