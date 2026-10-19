"""Explicit resource ownership for the headless runtime bootstrap."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
from fdai_runtime_diagnostics import DevelopmentDiagnosticServer

from fdai.delivery.self_health_disagreement import RuntimeMixedModelHealthSource
from fdai.delivery.self_health_event_lag import RuntimeEventLagSource
from fdai.delivery.self_health_verifier import RuntimeVerifierHealthSource
from fdai.runtime.bootstrap_messaging import MessagingRuntime
from fdai.runtime.bootstrap_pantheon import PantheonInitializationResult
from fdai.runtime.bootstrap_shutdown import close_runtime_resources
from fdai.runtime.health import RuntimeHealthServer
from fdai.runtime.startup_observation import RuntimeStartupDurationSource


@dataclass(slots=True)
class RuntimeResources:
    """Resources acquired during startup and released in dependency order."""

    health_server: RuntimeHealthServer | None = None
    startup_duration_source: RuntimeStartupDurationSource | None = field(default=None, kw_only=True)
    verifier_health_source: RuntimeVerifierHealthSource | None = field(default=None, kw_only=True)
    event_lag_source: RuntimeEventLagSource | None = field(default=None, kw_only=True)
    mixed_model_health_source: RuntimeMixedModelHealthSource | None = field(
        default=None, kw_only=True
    )
    development_diagnostics: DevelopmentDiagnosticServer | None = None
    http_client: httpx.AsyncClient | None = None
    messaging: MessagingRuntime | None = None
    isolated_executor_client: Any = None
    task_workers: Any = None
    state_store: Any = None
    pantheon: PantheonInitializationResult = field(default_factory=PantheonInitializationResult)

    async def close(self) -> None:
        """Stop authority transport first, then close shared runtime resources."""

        if self.verifier_health_source is not None:
            self.verifier_health_source.close()
        if self.event_lag_source is not None:
            self.event_lag_source.close()
        if self.mixed_model_health_source is not None:
            self.mixed_model_health_source.close()
        if self.startup_duration_source is not None:
            self.startup_duration_source.close()
        try:
            try:
                try:
                    if self.development_diagnostics is not None:
                        await self.development_diagnostics.aclose()
                finally:
                    if self.isolated_executor_client is not None:
                        await self.isolated_executor_client.stop()
            finally:
                if self.task_workers is not None:
                    await self.task_workers.aclose()
        finally:
            await close_runtime_resources(
                health_server=self.health_server,
                pantheon_runtime=self.pantheon.runtime,
                runtime_state_publisher=self.pantheon.runtime_state_publisher,
                diagnostic_bus=(
                    self.messaging.diagnostic_bus if self.messaging is not None else None
                ),
                auxiliary_bus=(
                    self.messaging.auxiliary_bus if self.messaging is not None else None
                ),
                bus=self.messaging.bus if self.messaging is not None else None,
                http_client=self.http_client,
                state_store=self.state_store,
            )


__all__ = ["RuntimeResources"]
