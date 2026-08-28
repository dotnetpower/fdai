from __future__ import annotations

from fdai.delivery.azure.event_bus import EventHubsKafkaBusConfig
from fdai.delivery.event_bus_multiplex import MultiplexedEventBus
from fdai.runtime.bootstrap_messaging import build_messaging_runtime
from fdai.runtime.bootstrap_plan import build_bootstrap_plan
from fdai.runtime.bootstrap_topics import RUNTIME_LOGICAL_TOPICS
from fdai.shared.config.models import KafkaConfig, LlmMode
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.workload_identity import WorkloadIdentity


class _RecordingBusFactory:
    def __init__(self) -> None:
        self.configs: list[EventHubsKafkaBusConfig] = []
        self.buses: list[InMemoryEventBus] = []

    def __call__(
        self,
        *,
        identity: WorkloadIdentity | None,
        config: EventHubsKafkaBusConfig,
    ) -> EventBus:
        del identity
        self.configs.append(config)
        bus = InMemoryEventBus()
        self.buses.append(bus)
        return bus


def _kafka_config() -> KafkaConfig:
    return KafkaConfig(
        bootstrap_servers="primary:9093",
        topic_events="fdai.events",
    )


def test_messaging_runtime_builds_local_primary_transport() -> None:
    plan = build_bootstrap_plan(
        llm_mode=LlmMode.LOCAL_FAKE,
        environment={
            "FDAI_START_CONSUMER": "1",
            "FDAI_EXECUTION_VENUE": "local",
        },
    )
    factory = _RecordingBusFactory()

    runtime = build_messaging_runtime(
        plan=plan,
        kafka=_kafka_config(),
        identity=None,
        bus_factory=factory,
    )

    assert len(factory.configs) == 1
    assert factory.configs[0].bootstrap_servers == "primary:9093"
    assert factory.configs[0].security_protocol == "PLAINTEXT"
    assert isinstance(runtime.bus, MultiplexedEventBus)
    assert runtime.bus.logical_topics == RUNTIME_LOGICAL_TOPICS
    assert runtime.operational_bus is runtime.bus
    assert runtime.auxiliary_bus is None


def test_messaging_runtime_selects_auxiliary_operational_transport() -> None:
    plan = build_bootstrap_plan(
        llm_mode=LlmMode.LOCAL_FAKE,
        environment={
            "FDAI_START_CONSUMER": "1",
            "FDAI_EXECUTION_VENUE": "deployed",
            "FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS": "auxiliary:9093",
            "FDAI_PANTHEON_OBJECT_TOPIC": "custom.objects",
        },
    )
    factory = _RecordingBusFactory()

    runtime = build_messaging_runtime(
        plan=plan,
        kafka=_kafka_config(),
        identity=None,
        bus_factory=factory,
    )

    assert [config.bootstrap_servers for config in factory.configs] == [
        "primary:9093",
        "auxiliary:9093",
    ]
    assert all(config.security_protocol == "SASL_SSL" for config in factory.configs)
    assert runtime.auxiliary_bus is factory.buses[1]
    assert runtime.operational_bus is factory.buses[1]
    assert isinstance(runtime.bus, MultiplexedEventBus)
    assert runtime.bus.physical_topic == "custom.objects"


def test_messaging_runtime_requires_consumer_venue() -> None:
    plan = build_bootstrap_plan(llm_mode=LlmMode.LOCAL_FAKE, environment={})

    try:
        build_messaging_runtime(
            plan=plan,
            kafka=_kafka_config(),
            identity=None,
            bus_factory=_RecordingBusFactory(),
        )
    except RuntimeError as exc:
        assert str(exc) == "enabled consumer requires an execution venue"
    else:
        raise AssertionError("missing consumer venue did not fail")


def test_messaging_runtime_builds_dedicated_diagnostic_transport() -> None:
    plan = build_bootstrap_plan(
        llm_mode=LlmMode.LOCAL_FAKE,
        environment={
            "FDAI_START_CONSUMER": "1",
            "FDAI_EXECUTION_VENUE": "deployed",
            "FDAI_DIAGNOSTIC_KAFKA_BOOTSTRAP_SERVERS": "diagnostics:9093",
            "FDAI_DIAGNOSTIC_TOPIC": "azure.diagnostics",
            "FDAI_DIAGNOSTIC_METRIC_WHITELIST_JSON": '["node_cpu_percent"]',
        },
    )
    factory = _RecordingBusFactory()

    runtime = build_messaging_runtime(
        plan=plan,
        kafka=_kafka_config(),
        identity=None,
        bus_factory=factory,
    )

    assert [config.bootstrap_servers for config in factory.configs] == [
        "primary:9093",
        "diagnostics:9093",
    ]
    assert factory.configs[1].auto_offset_reset == "earliest"
    assert runtime.diagnostic_bus is factory.buses[1]
