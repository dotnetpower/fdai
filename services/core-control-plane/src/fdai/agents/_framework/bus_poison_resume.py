"""Resume helpers for cleared ordered-poison consumers."""

from __future__ import annotations

import asyncio
from typing import Any


def resume_ordered_consumer(bridge: Any, *, topic: str, agent_name: str) -> bool:
    """Restart one bridge consumer after its durable halt has been cleared."""

    bridge._halted_ordered_topics.discard(topic)
    subscribers = bridge._subs.get(topic, ())
    agent_handlers = [(name, handler) for name, handler in subscribers if name == agent_name]
    if not agent_handlers:
        return False
    total = len(agent_handlers)
    for ordinal, (_name, handler) in enumerate(agent_handlers, start=1):
        group_id = bridge._consumer_group_id(agent_name, topic, ordinal, total)
        consumer_id = bridge._consumer_id(agent_name, topic, ordinal, total)
        task_name = f"pantheon-consumer.{agent_name}.{topic}"
        if any(not task.done() and task.get_name() == task_name for task in bridge._tasks):
            continue
        bridge._tasks.append(
            asyncio.create_task(
                bridge._consume(
                    agent_name=agent_name,
                    topic=topic,
                    group_id=group_id,
                    consumer_id=consumer_id,
                    handler=handler,
                ),
                name=task_name,
            )
        )
    return True


__all__ = ["resume_ordered_consumer"]
