"""Interactive local command transport configuration."""

from __future__ import annotations

import pytest

from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.event_bus import EventHubsKafkaBus
from fdai.delivery.read_api.dev.command_transport import build_local_command_transport
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.read_api.streaming.agent_activity_stream import AgentActivityEvent
from fdai.shared.providers.local import LocalEventBus


class _AgentPublisher:
    async def publish(self, event: AgentActivityEvent) -> None:
        pass


def test_transport_defaults_to_local_without_azure_configuration() -> None:
    wiring = build_local_command_transport(
        read_model=InMemoryConsoleReadModel(),
        action_types=(),
        environ={},
    )

    assert wiring.kind == "local"
    assert isinstance(wiring.event_bus, LocalEventBus)
    assert wiring.event_topic == "aw.events"
    assert wiring.live_stream.sink is not None
    assert wiring.agent_activity.sink is not None
    assert wiring.live_stream.broadcaster_factory is None
    assert wiring.agent_activity.broadcaster_factory is None


@pytest.mark.parametrize(
    "environ",
    [
        {"FDAI_KAFKA_BOOTSTRAP_SERVERS": "example.servicebus.windows.net:9093"},
        {"KAFKA_TOPIC_EVENTS": "fdai.events"},
    ],
)
def test_partial_transport_configuration_fails_fast(environ: dict[str, str]) -> None:
    with pytest.raises(RuntimeError, match="MUST be configured together"):
        build_local_command_transport(
            read_model=InMemoryConsoleReadModel(),
            action_types=(),
            environ=environ,
        )


def test_configured_transport_uses_real_broadcasters_without_connecting_eagerly() -> None:
    wiring = build_local_command_transport(
        read_model=InMemoryConsoleReadModel(),
        action_types=(),
        environ={
            "FDAI_KAFKA_BOOTSTRAP_SERVERS": "example.servicebus.windows.net:9093",
            "KAFKA_TOPIC_EVENTS": "fdai.events",
            "FDAI_STAGE_TOPIC": "fdai.stage-events",
            "FDAI_READ_API_CONSUMER_INSTANCE": "local-developer-a",
            "AZURE_SUBSCRIPTION_ID": "subscription-a",
            "AZURE_TENANT_ID": "tenant-a",
        },
    )

    assert wiring.kind == "azure"
    assert isinstance(wiring.event_bus, EventHubsKafkaBus)
    assert isinstance(wiring.event_bus._identity, AsyncAzureCliWorkloadIdentity)
    assert wiring.event_bus._identity.credential.subscription_id == "subscription-a"
    assert wiring.event_bus._identity.credential.tenant_id == "tenant-a"
    assert wiring.live_stream.broadcaster_factory is not None
    assert wiring.live_stream.emitter_factory is None
    assert wiring.agent_activity.broadcaster_factory is not None
    broadcaster = wiring.agent_activity.broadcaster_factory(_AgentPublisher())
    assert broadcaster._group_id == "fdai-agent-activity.local-developer-a"
