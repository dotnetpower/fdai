"""Service-owned lifecycle record for the Operator ASGI application."""

from __future__ import annotations

from dataclasses import dataclass

from fdai_service_contracts import OperatorReadModel, ReadDataSource

from fdai_operator_service.auth import OperatorAuthenticator
from fdai_operator_service.contracts import ApplicationLifecycle, AsgiApplication, ReadinessProbe
from fdai_operator_service.environment import OperatorEnvironment
from fdai_operator_service.routes import OperatorRouteFamilies, build_operator_app
from fdai_operator_service.streaming import LiveStreamHub


@dataclass(frozen=True, slots=True)
class OperatorRuntime:
    """Bind validated HTTP configuration to non-privileged Operator dependencies."""

    environment: OperatorEnvironment
    authenticator: OperatorAuthenticator
    read_model: OperatorReadModel
    data_sources: tuple[ReadDataSource, ...]
    route_families: OperatorRouteFamilies
    readiness_probe: ReadinessProbe
    live_stream_hub: LiveStreamHub
    lifecycle: ApplicationLifecycle | None = None

    def create_app(self) -> AsgiApplication:
        """Create the service-owned Starlette application without privileged identity."""
        return build_operator_app(
            authenticator=self.authenticator,
            read_model=self.read_model,
            data_sources=self.data_sources,
            route_families=self.route_families,
            readiness_probe=self.readiness_probe,
            live_stream_hub=self.live_stream_hub,
            cors_allow_origins=self.environment.cors_allow_origins,
            lifecycle=self.lifecycle,
        )
