"""Service-owned lifecycle record for the Operator ASGI application."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

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
    agent_stream_hub: LiveStreamHub
    local_cli_profile: Mapping[str, Any] | None = None
    local_cli_session_token: str | None = None
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
            agent_stream_hub=self.agent_stream_hub,
            cors_allow_origins=self.environment.cors_allow_origins,
            local_cli_profile=self.local_cli_profile,
            local_cli_session_token=self.local_cli_session_token,
            lifecycle=self.lifecycle,
        )
