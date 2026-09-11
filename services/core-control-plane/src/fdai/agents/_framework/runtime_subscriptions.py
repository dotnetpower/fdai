"""Private subscription wiring for the pantheon runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import Handler
from fdai.agents._framework.bus_bridge import EventBusBridge
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn
from fdai.agents.mimir import Mimir
from fdai.core.rule_semantic_generation import (
    RULE_GENERATION_ACTIVATION_COMMAND_TOPIC,
    RULE_GENERATION_ACTIVATION_RESULT_TOPIC,
    RuleGenerationActivationBinder,
    RuleGenerationBuildHandler,
    RuleGenerationValidationHandler,
)
from fdai.shared.providers.state_store import StateStore

RECOVERY_EFFECT_OBSERVER_PRINCIPAL = "recovery-effect-observer"
"""Consumer group that relays independent recovery post-effect observations."""


@dataclass(frozen=True, slots=True)
class RuleGenerationWorkerBindings:
    """Optional Mimir build and Heimdall validation handlers."""

    build: RuleGenerationBuildHandler
    validation: RuleGenerationValidationHandler


def build_ingress_handler(
    *,
    agent: Agent,
    on_unkeyed: Callable[[ValueError], None],
) -> Callable[[str, dict[str, Any]], Awaitable[None]]:
    """Return the raw-event handler that feeds Huginn without DLQ noise."""
    if not isinstance(agent, Huginn):  # pragma: no cover - factory guarantee
        raise TypeError("Huginn agent is missing from the pantheon")

    async def _ingress(_topic: str, payload: dict[str, Any]) -> None:
        try:
            await agent.ingest(payload)
        except ValueError as exc:
            on_unkeyed(exc)

    return _ingress


def bind_runtime_subscriptions(
    *,
    bridge: EventBusBridge,
    instantiated: dict[str, Agent],
    agents: dict[str, Agent],
    rule_generation_workers: RuleGenerationWorkerBindings | None,
    rule_generation_activation_binder: RuleGenerationActivationBinder | None,
    rule_generation_state_store: StateStore | None,
) -> int:
    """Bind declared subscriptions and optional Mimir Rule-generation wiring."""
    mimir = instantiated["Mimir"]
    heimdall = instantiated["Heimdall"]
    if rule_generation_workers is not None:
        if not isinstance(mimir, Mimir):
            raise TypeError("Pantheon Mimir implementation does not support Rule generation")
        if not isinstance(heimdall, Heimdall):
            raise TypeError("Pantheon Heimdall implementation does not support Rule validation")
        mimir.bind_rule_generation_build_handler(rule_generation_workers.build)
        heimdall.bind_rule_generation_validation_handler(rule_generation_workers.validation)
    if rule_generation_activation_binder is not None:
        if not isinstance(mimir, Mimir):
            raise TypeError("Pantheon Mimir implementation does not support Rule activation")
        mimir.bind_rule_generation_activation_binder(rule_generation_activation_binder)
    if rule_generation_state_store is not None:
        if not isinstance(mimir, Mimir):
            raise TypeError("Pantheon Mimir implementation does not support Rule receipts")
        mimir.bind_rule_generation_state_store(rule_generation_state_store)

    subscription_count = 0
    for name, agent in agents.items():
        for topic in agent.spec.subscribes:
            bridge.subscribe(topic, name, agent.on_typed_message)
            subscription_count += 1
    if rule_generation_activation_binder is not None and "Mimir" in agents:
        bridge.subscribe(
            RULE_GENERATION_ACTIVATION_COMMAND_TOPIC,
            "Mimir",
            agents["Mimir"].on_typed_message,
        )
        subscription_count += 1
    if rule_generation_state_store is not None and "Mimir" in agents:
        bridge.subscribe(
            RULE_GENERATION_ACTIVATION_RESULT_TOPIC,
            "Mimir",
            agents["Mimir"].on_typed_message,
        )
        subscription_count += 1
    return subscription_count


def bind_recovery_effect_observation(
    bridge: EventBusBridge,
    handler: Handler | None,
) -> int:
    """Subscribe the independent recovery post-effect observation intake.

    A dedicated observer group receives the versioned observation event without
    taking records from the agents that also subscribe `object.event`. The sole
    privileged executor never publishes here, and the intake re-authenticates
    the producing principal the bus recorded on the envelope.
    """

    if handler is None:
        return 0
    bridge.subscribe("object.event", RECOVERY_EFFECT_OBSERVER_PRINCIPAL, handler)
    return 1


__all__ = [
    "RECOVERY_EFFECT_OBSERVER_PRINCIPAL",
    "RuleGenerationWorkerBindings",
    "bind_recovery_effect_observation",
    "bind_runtime_subscriptions",
    "build_ingress_handler",
]
