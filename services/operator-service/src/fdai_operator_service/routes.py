"""Framework-neutral ASGI delegation owned by the Operator service."""

from __future__ import annotations

from dataclasses import dataclass

from fdai_operator_service.contracts import (
    AsgiApplication,
    AsgiReceive,
    AsgiScope,
    AsgiSend,
)


@dataclass(frozen=True, slots=True)
class DelegatingApplication:
    """Delegate each ASGI connection to an injected application unchanged."""

    application: AsgiApplication

    async def __call__(
        self,
        scope: AsgiScope,
        receive: AsgiReceive,
        send: AsgiSend,
    ) -> None:
        """Forward the exact ASGI scope and channels to the configured application."""
        await self.application(scope, receive, send)
