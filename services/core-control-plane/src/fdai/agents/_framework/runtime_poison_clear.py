"""Runtime wiring for ordered-poison-halt clear requests."""

from __future__ import annotations

from fdai_service_contracts.bus_poison_halt_clear import ORDERED_POISON_HALT_CLEAR_TOPIC

from fdai.agents._framework.bus_bridge import EventBusBridge
from fdai.agents._framework.bus_poison_clear import OrderedPoisonHaltClearProcessor
from fdai.agents._framework.runtime_subscriptions import POISON_HALT_CLEAR_PRINCIPAL
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore


def bind_ordered_poison_halt_clear(
    *,
    bridge: EventBusBridge,
    provider: EventBus,
    state_store: StateStore | None,
    consumer_group_prefix: str,
) -> int:
    """Subscribe the framework maintenance clear handler when durable halt state is bound."""

    if state_store is None:
        return 0
    poison_clear = OrderedPoisonHaltClearProcessor(
        bus=provider,
        halt_state_store=state_store,
        audit_store=state_store,
        consumer_group_prefix=consumer_group_prefix,
    )

    async def _handle_ordered_poison_clear(
        request_topic: str,
        payload: dict[str, object],
    ) -> None:
        result = await poison_clear.handle(request_topic, payload)
        if result.status == "cleared":
            bridge.resume_ordered_consumer_after_clear(
                topic=str(payload.get("topic") or ""),
                agent_name=str(payload.get("agent_name") or ""),
            )

    bridge.subscribe(
        ORDERED_POISON_HALT_CLEAR_TOPIC,
        POISON_HALT_CLEAR_PRINCIPAL,
        _handle_ordered_poison_clear,
    )
    return 1


__all__ = ["bind_ordered_poison_halt_clear"]
