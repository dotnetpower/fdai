"""Resume helpers for cleared ordered-poison consumers."""

from __future__ import annotations

import asyncio
from typing import Any

from fdai.agents._framework.bus_poison_halt import clear_ordered_halt


async def clear_ordered_poison_halt(bridge: Any, *, topic: str, agent_name: str) -> bool:
    if bridge.halt_state_store is None:
        return False
    group_id = f"{bridge.consumer_group_prefix}.{agent_name}"
    cleared = await clear_ordered_halt(bridge.halt_state_store, group_id=group_id, topic=topic)
    consumer_id = f"{agent_name}:{topic}"
    if cleared and bridge._consumer_states.get(consumer_id) == "halted":
        bridge._consumer_states[consumer_id] = "cleared"
        resume_ordered_consumer(bridge, topic=topic, agent_name=agent_name)
    return bool(cleared)


def consumer_id_for_group(
    bridge: Any,
    *,
    agent_name: str,
    topic: str,
    group_id: str | None,
) -> str:
    if group_id is None:
        return f"{agent_name}:{topic}"
    subscribers = bridge._subs.get(topic, ())
    total = sum(1 for name, _handler in subscribers if name == agent_name)
    if total <= 1:
        return f"{agent_name}:{topic}"
    for ordinal in range(1, total + 1):
        if bridge._consumer_group_id(agent_name, topic, ordinal, total) == group_id:
            return str(bridge._consumer_id(agent_name, topic, ordinal, total))
    return f"{agent_name}:{topic}"


def resume_ordered_consumer(
    bridge: Any,
    *,
    topic: str,
    agent_name: str,
    group_id: str | None = None,
) -> bool:
    """Restart one bridge consumer after its durable halt has been cleared."""

    bridge._halted_ordered_topics.discard(topic)
    subscribers = bridge._subs.get(topic, ())
    agent_handlers = [(name, handler) for name, handler in subscribers if name == agent_name]
    if not agent_handlers:
        return False
    total = len(agent_handlers)
    resumed = False
    for ordinal, (_name, handler) in enumerate(agent_handlers, start=1):
        candidate_group_id = bridge._consumer_group_id(agent_name, topic, ordinal, total)
        if group_id is not None and candidate_group_id != group_id:
            continue
        consumer_id = bridge._consumer_id(agent_name, topic, ordinal, total)
        task_name = f"pantheon-consumer.{consumer_id}"
        if any(not task.done() and task.get_name() == task_name for task in bridge._tasks):
            continue
        bridge._tasks.append(
            asyncio.create_task(
                bridge._consume(
                    agent_name=agent_name,
                    topic=topic,
                    group_id=candidate_group_id,
                    consumer_id=consumer_id,
                    handler=handler,
                ),
                name=task_name,
            )
        )
        resumed = True
    return resumed


__all__ = ["clear_ordered_poison_halt", "consumer_id_for_group", "resume_ordered_consumer"]
