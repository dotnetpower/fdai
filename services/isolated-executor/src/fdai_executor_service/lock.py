"""Logical-target locking for isolated Executor shadow commands.

The wrapper holds the injected cross-replica ``ResourceLock`` while the
durable no-effect handler resolves one command. It adds no execution authority,
provider adapter, identity binding, or lock-backend composition.
"""

from __future__ import annotations

from typing import Protocol

from fdai_service_contracts.executor import ExecutorCommand, ExecutorShadowReceipt, ResourceLock


class ExecutorShadowCommandHandler(Protocol):
    """No-effect command handler invoked inside a logical-target lock."""

    async def handle(self, command: ExecutorCommand) -> ExecutorShadowReceipt:
        """Return a terminal shadow receipt without applying an effect."""

        ...


class LockedIsolatedExecutorShadowService:
    """Serialize isolated Executor shadow handling by logical target."""

    def __init__(
        self,
        *,
        delegate: ExecutorShadowCommandHandler,
        resource_lock: ResourceLock,
    ) -> None:
        self._delegate = delegate
        self._resource_lock = resource_lock

    async def handle(self, command: ExecutorCommand) -> ExecutorShadowReceipt:
        """Hold the exact target lock through durable terminal closure."""

        async with self._resource_lock.acquire(command.target_resource_ref):
            return await self._delegate.handle(command)


__all__ = [
    "ExecutorShadowCommandHandler",
    "LockedIsolatedExecutorShadowService",
]
