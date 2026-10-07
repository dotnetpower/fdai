"""Code-security review publication behavior for Heimdall."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from fdai.agents._framework.bus import PantheonBus
from fdai.shared.providers.code_security import CodeSecurityDriftProjector


class HeimdallCodeSecurityMixin:
    """Validate and publish bounded code-security review drift through Heimdall ownership."""

    bus: PantheonBus | None
    _code_security_drift_projector: CodeSecurityDriftProjector | None

    if TYPE_CHECKING:

        def record_behavior(self, key: str, count: int = 1) -> None: ...

    async def publish_code_security_drift(self, package: Mapping[str, object]) -> bool:
        """Publish one strict no-authority code-security review for governed review."""

        if self._code_security_drift_projector is None:
            self.record_behavior("code_security_drift:projector_unavailable")
            return False
        payload = self._code_security_drift_projector(package)
        self.record_behavior(f"code_security_drift:{payload['decision']}")
        if self.bus is None:
            return False
        await self.bus.publish("Heimdall", "object.drift", payload)
        return True


__all__ = ["HeimdallCodeSecurityMixin"]
