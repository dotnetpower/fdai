"""Role-owned alert callback bindings on existing typed Event/Drift/ActionRun topics.

These mixins retain callbacks on the owning agent instance. They create no agent,
shared workflow state, provider, authority or alternate event channel.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any

from fdai.agents._framework.bus import PantheonBus

_PlanHook = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
_ObserveHook = Callable[[dict[str, Any]], Awaitable[Mapping[str, Any]]]
_EffectHook = Callable[[dict[str, Any]], Awaitable[bool]]


class ForsetiAlertNoiseMixin:
    """Bind inert proposal/effect planning without execution or observation authority."""

    _alert_noise_hook: _PlanHook | None = None
    _alert_effect_hook: _PlanHook | None = None

    if TYPE_CHECKING:

        def record_behavior(self, key: str, count: int = 1) -> None: ...

    def bind_alert_noise_planner(self, hook: _PlanHook) -> None:
        """Bind exact-evidence proposal planning once on this Forseti instance."""
        if self._alert_noise_hook is not None:
            raise RuntimeError("alert noise planner is already bound")
        self._alert_noise_hook = hook

    def bind_alert_effect_planner(self, hook: _PlanHook) -> None:
        """Bind outcome-driven Process resume and holds on the existing Drift topic."""
        if self._alert_effect_hook is not None:
            raise RuntimeError("alert effect planner is already bound")
        self._alert_effect_hook = hook

    async def _alert_noise_message(self, topic: str, payload: dict[str, Any]) -> bool:
        if topic == "object.event" and payload.get("event_type") in {
            "alert_noise.assess",
            "alert_noise.propose",
        }:
            self.record_behavior("alert_noise:observation_deferred")
            return True
        if topic == "object.drift" and payload.get("kind") == "alert_noise":
            if self._alert_noise_hook is None:
                raise RuntimeError("alert noise planner is unavailable")
            await self._alert_noise_hook(payload)
            self.record_behavior("alert_noise:planned")
            return True
        if topic == "object.drift" and payload.get("kind") == "alert_noise_effect":
            if self._alert_effect_hook is None:
                raise RuntimeError("alert effect planner is unavailable")
            await self._alert_effect_hook(payload)
            self.record_behavior("alert_noise:effect_reviewed")
            return True
        return False


class HeimdallAlertNoiseMixin:
    """Bind independent observation without deciding, approving or executing an action."""

    bus: PantheonBus | None
    _alert_noise_hook: _ObserveHook | None = None
    _alert_effect_hook: _EffectHook | None = None

    if TYPE_CHECKING:

        def record_behavior(self, key: str, count: int = 1) -> None: ...

    def bind_alert_noise_observer(self, hook: _ObserveHook) -> None:
        """Bind the scope-authenticated observer once on this Heimdall instance."""
        if self._alert_noise_hook is not None:
            raise RuntimeError("alert noise observer is already bound")
        self._alert_noise_hook = hook

    def bind_alert_effect_observer(self, hook: _EffectHook) -> None:
        """Bind the independent observer on the existing Thor ActionRun subscription."""
        if self._alert_effect_hook is not None:
            raise RuntimeError("alert effect observer is already bound")
        self._alert_effect_hook = hook

    async def _alert_noise_message(self, topic: str, payload: dict[str, Any]) -> bool:
        if topic == "object.action-run" and payload.get("kind") == "alert_noise_publication":
            if self._alert_effect_hook is None:
                raise RuntimeError("alert effect observer is unavailable")
            await self._alert_effect_hook(payload)
            return True
        if topic == "object.event" and payload.get("event_type") in {
            "alert_noise.assess",
            "alert_noise.propose",
        }:
            if self._alert_noise_hook is None or self.bus is None:
                raise RuntimeError("alert noise observer is unavailable")
            signal = await self._alert_noise_hook(payload)
            await self.bus.publish("Heimdall", "object.drift", dict(signal))
            self.record_behavior("alert_noise:observed")
            return True
        return False
