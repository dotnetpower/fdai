"""Private subscription wiring for the pantheon runtime."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus_bridge import EventBusBridge
from fdai.agents.heimdall import Heimdall
from fdai.agents.mimir import Mimir
from fdai.core.rule_semantic_generation import (
    RULE_GENERATION_ACTIVATION_COMMAND_TOPIC,
    RULE_GENERATION_ACTIVATION_RESULT_TOPIC,
    RuleGenerationActivationBinder,
    RuleGenerationBuildHandler,
    RuleGenerationValidationHandler,
)
from fdai.shared.providers.state_store import StateStore


@dataclass(frozen=True, slots=True)
class RuleGenerationWorkerBindings:
    """Optional Mimir build and Heimdall validation handlers."""

    build: RuleGenerationBuildHandler
    validation: RuleGenerationValidationHandler


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


__all__ = ["RuleGenerationWorkerBindings", "bind_runtime_subscriptions"]
