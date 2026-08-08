"""Ordered resource cleanup for the headless runtime bootstrap."""

from __future__ import annotations

import logging
from typing import Protocol

_LOGGER = logging.getLogger("fdai.startup")


class _AsyncCloseable(Protocol):
    async def close(self) -> None: ...


class _AsyncStoppable(Protocol):
    async def stop(self) -> None: ...


class _AsyncAcloseable(Protocol):
    async def aclose(self) -> None: ...


async def close_runtime_resources(
    *,
    health_server: _AsyncCloseable | None,
    pantheon_runtime: _AsyncStoppable | None,
    runtime_state_publisher: _AsyncStoppable | None,
    auxiliary_bus: object | None,
    bus: object | None,
    http_client: _AsyncAcloseable | None,
) -> None:
    """Close runtime resources in dependency order without hiding bounded failures."""

    if health_server is not None:
        try:
            await health_server.close()
        except Exception:  # noqa: BLE001
            _LOGGER.warning("health_server_stop_failed", exc_info=True)
    if pantheon_runtime is not None:
        try:
            await pantheon_runtime.stop()
        except Exception:  # noqa: BLE001
            _LOGGER.warning("pantheon_stop_failed", exc_info=True)
    if runtime_state_publisher is not None:
        await runtime_state_publisher.stop()
    await _close_bus(auxiliary_bus, warning="auxiliary_bus_close_failed")
    await _close_bus(bus, warning="bus_close_failed")
    if http_client is not None:
        try:
            await http_client.aclose()
        except Exception:  # noqa: BLE001
            _LOGGER.warning("http_client_close_failed", exc_info=True)


async def _close_bus(bus: object | None, *, warning: str) -> None:
    if bus is None:
        return
    close = getattr(bus, "close", None)
    if not callable(close):
        return
    try:
        await close()
    except Exception:  # noqa: BLE001
        _LOGGER.warning(warning, exc_info=True)


__all__ = ["close_runtime_resources"]
