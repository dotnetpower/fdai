"""Verified action-observation relay owned by Heimdall."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any

from fdai.agents._framework.bus import PantheonBus

ActionObservationHook = Callable[[dict[str, Any]], Awaitable[bool | Mapping[str, Any]]]


class HeimdallActionObservationMixin:
    """Validate and publish independent action effects on Heimdall's owned topic."""

    bus: PantheonBus | None
    _action_observation_hook: ActionObservationHook | None

    if TYPE_CHECKING:

        def record_behavior(self, key: str, count: int = 1) -> None: ...

    async def _observe_action_run(self, payload: dict[str, Any]) -> None:
        if self._action_observation_hook is None:
            self.record_behavior("action_effect_observation:unavailable")
            return
        observation = await self._action_observation_hook(payload)
        recorded = bool(observation)
        if isinstance(observation, Mapping):
            if (
                observation.get("event_type") != "action.execution.effect_verified.v1"
                or observation.get("producer_principal") != "Heimdall"
            ):
                raise ValueError("action effect observation returned an unsupported event")
            if self.bus is None:
                raise RuntimeError("action effect observation requires the Heimdall event bus")
            await self.bus.publish(
                "Heimdall",
                "object.recovery-effect-observation",
                dict(observation),
            )
        self.record_behavior(
            "action_effect_observation:recorded" if recorded else "action_effect_observation:held"
        )


__all__ = ["ActionObservationHook", "HeimdallActionObservationMixin"]
