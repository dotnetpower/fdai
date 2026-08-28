"""Explicit resource ownership for the headless runtime bootstrap."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from fdai.runtime.bootstrap_messaging import MessagingRuntime
from fdai.runtime.bootstrap_pantheon import PantheonInitializationResult
from fdai.runtime.bootstrap_shutdown import close_runtime_resources
from fdai.runtime.health import RuntimeHealthServer


@dataclass(slots=True)
class RuntimeResources:
    """Resources acquired during startup and released in dependency order."""

    health_server: RuntimeHealthServer | None = None
    http_client: httpx.AsyncClient | None = None
    messaging: MessagingRuntime | None = None
    isolated_executor_client: Any = None
    pantheon: PantheonInitializationResult = field(default_factory=PantheonInitializationResult)

    async def close(self) -> None:
        """Stop authority transport first, then close shared runtime resources."""

        if self.isolated_executor_client is not None:
            await self.isolated_executor_client.stop()
        await close_runtime_resources(
            health_server=self.health_server,
            pantheon_runtime=self.pantheon.runtime,
            runtime_state_publisher=self.pantheon.runtime_state_publisher,
            diagnostic_bus=(self.messaging.diagnostic_bus if self.messaging is not None else None),
            auxiliary_bus=(self.messaging.auxiliary_bus if self.messaging is not None else None),
            bus=self.messaging.bus if self.messaging is not None else None,
            http_client=self.http_client,
        )


__all__ = ["RuntimeResources"]
