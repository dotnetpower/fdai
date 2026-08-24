"""Provider-schema drift publication behavior for Heimdall."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from fdai.agents._framework.bus import PantheonBus
from fdai.shared.providers.provider_schema import ProviderSchemaDriftProjector


class HeimdallProviderSchemaMixin:
    """Validate and publish bounded provider-schema drift through Heimdall ownership."""

    bus: PantheonBus | None
    _provider_schema_drift_projector: ProviderSchemaDriftProjector | None

    if TYPE_CHECKING:

        def record_behavior(self, key: str, count: int = 1) -> None: ...

    async def publish_provider_schema_drift(self, package: Mapping[str, object]) -> bool:
        """Publish one strict no-authority provider-schema drift for governed review."""

        if self._provider_schema_drift_projector is None:
            self.record_behavior("provider_schema_drift:projector_unavailable")
            return False
        payload = self._provider_schema_drift_projector(package)
        self.record_behavior(f"provider_schema_drift:{payload['decision']}")
        if self.bus is None:
            return False
        await self.bus.publish("Heimdall", "object.drift", payload)
        return True


__all__ = ["HeimdallProviderSchemaMixin"]
