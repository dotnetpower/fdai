"""Event transport assembly for the headless control-plane process."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.event_bus_multiplex import MultiplexedEventBus
from fdai.runtime.bootstrap_bindings import operational_event_bus
from fdai.runtime.bootstrap_plan import BootstrapPlan
from fdai.runtime.bootstrap_topics import RUNTIME_LOGICAL_TOPICS
from fdai.runtime.venue import bus_security_protocol
from fdai.shared.config.models import KafkaConfig
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.workload_identity import WorkloadIdentity
from fdai.shared.streaming.stage_publisher import EventBusStagePublisher


class EventBusFactory(Protocol):
    """Construct one event-bus adapter without starting network activity."""

    def __call__(
        self,
        *,
        identity: WorkloadIdentity | None,
        config: EventHubsKafkaBusConfig,
    ) -> EventBus: ...


@dataclass(frozen=True, slots=True)
class MessagingRuntime:
    """Bound event transports and publishers retained by runtime assembly."""

    bus: EventBus
    auxiliary_bus: EventBus | None
    operational_bus: EventBus
    stage_publisher: EventBusStagePublisher


def build_messaging_runtime(
    *,
    plan: BootstrapPlan,
    kafka: KafkaConfig,
    identity: WorkloadIdentity | None,
    bus_factory: EventBusFactory = EventHubsKafkaBus,
) -> MessagingRuntime:
    """Build primary and optional auxiliary Kafka transports for one startup plan."""

    if plan.venue is None:
        raise RuntimeError("enabled consumer requires an execution venue")

    primary_transport = bus_factory(
        identity=identity,
        config=EventHubsKafkaBusConfig(
            bootstrap_servers=kafka.bootstrap_servers,
            dlq_suffix=kafka.topic_dlq_suffix,
            security_protocol=bus_security_protocol(plan.venue),
        ),
    )
    bus: EventBus = MultiplexedEventBus(
        bus=primary_transport,
        logical_topics=RUNTIME_LOGICAL_TOPICS,
        physical_topic=plan.pantheon_object_topic,
    )
    auxiliary_bus: EventBus | None = None
    if plan.auxiliary_kafka_bootstrap_servers:
        auxiliary_bus = bus_factory(
            identity=identity,
            config=EventHubsKafkaBusConfig(
                bootstrap_servers=plan.auxiliary_kafka_bootstrap_servers,
                dlq_suffix=kafka.topic_dlq_suffix,
                security_protocol=bus_security_protocol(plan.venue),
            ),
        )

    return MessagingRuntime(
        bus=bus,
        auxiliary_bus=auxiliary_bus,
        operational_bus=operational_event_bus(bus, auxiliary_bus),
        stage_publisher=EventBusStagePublisher(bus, topic=plan.stage_topic),
    )


__all__ = [
    "EventBusFactory",
    "MessagingRuntime",
    "build_messaging_runtime",
]
