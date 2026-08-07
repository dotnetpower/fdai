"""Service-owned lifecycle record for the Operator ASGI application."""

from __future__ import annotations

from dataclasses import dataclass

from fdai_operator_service.contracts import ApplicationFactory, AsgiApplication
from fdai_operator_service.environment import OperatorEnvironment


@dataclass(frozen=True, slots=True)
class OperatorRuntime:
    """Bind validated process configuration to one injected application factory."""

    environment: OperatorEnvironment
    application_factory: ApplicationFactory

    def create_app(self) -> AsgiApplication:
        """Create an ASGI application without starting its external providers eagerly."""
        return self.application_factory(self.environment.values)
