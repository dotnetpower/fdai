"""Azure-backed command and progress transport for interactive local use."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fdai.core.incident import IncidentLifecycleWorkflow, IncidentRegistry
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.read_api.dev.incident_store import ProjectingIncidentStateStore
from fdai.delivery.read_api.routes.console_action import ConsoleActionSubmitter
from fdai.delivery.read_api.streaming.agent_activity_broadcaster import (
    DEFAULT_STAGE_TOPIC,
    AgentActivityBroadcaster,
)
from fdai.delivery.read_api.streaming.agent_activity_stream import AgentActivityStreamConfig
from fdai.delivery.read_api.streaming.live_stage_broadcaster import LiveStageBroadcaster
from fdai.delivery.read_api.streaming.live_stream import LiveStreamConfig
from fdai.delivery.workflow_action_dispatcher import EventBusWorkflowActionDispatcher

_BOOTSTRAP_ENV = "FDAI_KAFKA_BOOTSTRAP_SERVERS"
_EVENT_TOPIC_ENV = "KAFKA_TOPIC_EVENTS"
_STAGE_TOPIC_ENV = "FDAI_STAGE_TOPIC"


@dataclass(frozen=True, slots=True)
class LocalCommandTransport:
    console_action: ConsoleActionSubmitter
    action_dispatcher: EventBusWorkflowActionDispatcher
    live_stream: LiveStreamConfig
    agent_activity: AgentActivityStreamConfig
    shutdown: Callable[[], Awaitable[None]]


def build_local_command_transport(
    *,
    read_model: Any,
    action_types: tuple[Any, ...],
    environ: Mapping[str, str] | None = None,
) -> LocalCommandTransport | None:
    """Build real Event Hubs transport when both endpoint and event topic are configured."""
    env = environ if environ is not None else os.environ
    bootstrap = env.get(_BOOTSTRAP_ENV, "").strip()
    event_topic = env.get(_EVENT_TOPIC_ENV, "").strip()
    if not bootstrap and not event_topic:
        return None
    if not bootstrap or not event_topic:
        raise RuntimeError(f"{_BOOTSTRAP_ENV} and {_EVENT_TOPIC_ENV} MUST be configured together")

    event_bus = EventHubsKafkaBus(
        identity=AsyncAzureCliWorkloadIdentity(),
        config=EventHubsKafkaBusConfig(
            bootstrap_servers=bootstrap,
            client_id="fdai-local-command",
        ),
    )
    incident_workflow = IncidentLifecycleWorkflow(
        registry=IncidentRegistry(state_store=ProjectingIncidentStateStore(read_model=read_model))
    )
    stage_topic = env.get(_STAGE_TOPIC_ENV, "").strip() or DEFAULT_STAGE_TOPIC

    async def shutdown() -> None:
        await event_bus.close()

    return LocalCommandTransport(
        console_action=ConsoleActionSubmitter(
            event_bus=event_bus,
            raw_event_topic=event_topic,
            action_type_names=frozenset(item.name for item in action_types),
            incident_workflow=incident_workflow,
        ),
        action_dispatcher=EventBusWorkflowActionDispatcher(
            event_bus=event_bus,
            topic=event_topic,
        ),
        live_stream=LiveStreamConfig(
            broadcaster_factory=lambda publisher: LiveStageBroadcaster(
                event_bus=event_bus,
                publisher=publisher,
                stage_topic=stage_topic,
            )
        ),
        agent_activity=AgentActivityStreamConfig(
            broadcaster_factory=lambda publisher: AgentActivityBroadcaster(
                event_bus=event_bus,
                publisher=publisher,
                stage_topic=stage_topic,
            )
        ),
        shutdown=shutdown,
    )


__all__ = ["LocalCommandTransport", "build_local_command_transport"]
