"""Observer-path handler for independent recovery post-effect observations.

The recovery effect observation reaches its durable intake through a dedicated
observer consumer group on the Heimdall-owned
`object.recovery-effect-observation` topic, never through the executor and
never from the shared ingress topic. The handler adds no judgement: it takes
the producing principal the bus authenticated on the envelope, hands it to the
Core ingress together with the payload, and lets the ingress own every
validation.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai.core.workflow.recovery_effect_ingress import (
    RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE,
    RecoveryEffectObservationIngress,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RecoveryEffectObservationHandler:
    """Relay one versioned observation event into the durable intake."""

    ingress: RecoveryEffectObservationIngress

    async def observe(self, topic: str, payload: Mapping[str, Any]) -> None:
        """Route only the versioned observation event, ignoring every other."""

        del topic
        if payload.get("event_type") != RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE:
            return
        await self.handle(payload, str(payload.get("producer_principal") or ""))

    async def handle(
        self,
        payload: Mapping[str, Any],
        authenticated_principal: str,
    ) -> bool:
        """Return whether the independent observation is now durable."""

        result = await self.ingress.observe(
            payload,
            authenticated_principal=authenticated_principal,
        )
        if not result.accepted:
            _LOGGER.warning(
                "workflow_recovery_effect_observation_refused",
                extra={
                    "rejection": str(result.rejection),
                    "attempt_identity_digest": result.attempt_identity_digest,
                },
            )
        return result.accepted


__all__ = ["RecoveryEffectObservationHandler"]
