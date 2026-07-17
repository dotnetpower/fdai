"""Production event transport, HIL, and incident lifecycle wiring."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from fdai.delivery.persistence import (
    PostgresHilApprovalRegistry,
    PostgresIncidentNotificationDeliveryStore,
    PostgresIncidentProposalStore,
)
from fdai.delivery.read_api.production import env_contract as _env
from fdai.delivery.read_api.production.config import (
    ProdReadApiConfigError,
    _parse_positive_int,
    _require_env,
)
from fdai.delivery.read_api.routes.hil_callback import HilCallbackConfig
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry


@dataclass(frozen=True, slots=True)
class ProductionRuntimeWiring:
    hil_callback: Any
    hil_registry: Any
    hil_decision_publisher: Any
    live_stream: Any
    agent_activity: Any
    console_action: Any
    event_bus: Any
    event_topic: str
    startup_callbacks: tuple[Callable[[], Awaitable[None]], ...]
    shutdown_callbacks: tuple[Callable[[], Awaitable[None]], ...]


def build_production_runtime(
    *,
    env: Mapping[str, str],
    repo_root: Path,
    read_model: Any,
    state_store: Any,
    state_store_config: Any,
    startup_callbacks: tuple[Callable[[], Awaitable[None]], ...],
    shutdown_callbacks: tuple[Callable[[], Awaitable[None]], ...],
) -> ProductionRuntimeWiring:
    """Build optional Kafka, live-stream, HIL, and incident services."""
    hil_callback = None
    hil_registry = None
    hil_decision_publisher = None
    live_stream = None
    agent_activity = None
    console_action = None
    event_bus = None
    event_topic = ""
    http_client: httpx.AsyncClient | None = None
    incident_sla_stop: Callable[[], Awaitable[None]] | None = None
    hil_secret = env.get(_env.HIL_SECRET_ENV, "").strip()
    kafka_bootstrap = env.get("FDAI_KAFKA_BOOTSTRAP_SERVERS", "").strip()
    if hil_secret or kafka_bootstrap:
        from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
        from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
        from fdai.delivery.chatops.hil_decision import (
            DEFAULT_HIL_DECISION_TOPIC,
            EventBusHilDecisionPublisher,
        )
        from fdai.delivery.read_api.streaming.agent_activity_broadcaster import (
            DEFAULT_STAGE_TOPIC,
            AgentActivityBroadcaster,
        )
        from fdai.delivery.read_api.streaming.agent_activity_stream import (
            AgentActivityStreamConfig,
        )
        from fdai.delivery.read_api.streaming.live_stage_broadcaster import LiveStageBroadcaster
        from fdai.delivery.read_api.streaming.live_stream import LiveStreamConfig

        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=15.0, pool=5.0)
        )
        identity = ManagedIdentityWorkloadIdentity(http_client=http_client)
        event_bus = EventHubsKafkaBus(
            identity=identity,
            config=EventHubsKafkaBusConfig(
                bootstrap_servers=kafka_bootstrap
                or _require_env(env, "FDAI_KAFKA_BOOTSTRAP_SERVERS")
            ),
        )
        if kafka_bootstrap:
            stage_topic = env.get(_env.STAGE_TOPIC_ENV, "").strip() or DEFAULT_STAGE_TOPIC
            live_stream = LiveStreamConfig(
                broadcaster_factory=lambda publisher: LiveStageBroadcaster(
                    event_bus=event_bus,
                    publisher=publisher,
                    stage_topic=stage_topic,
                )
            )
            agent_activity = AgentActivityStreamConfig(
                broadcaster_factory=lambda publisher: AgentActivityBroadcaster(
                    event_bus=event_bus,
                    publisher=publisher,
                    stage_topic=stage_topic,
                )
            )

        if hil_secret:
            hil_callback = HilCallbackConfig(secret=hil_secret)
            hil_registry = PostgresHilApprovalRegistry(
                store=state_store,
                dsn=read_model._config.dsn,
                statement_timeout_ms=read_model._config.statement_timeout_ms,
                connect_timeout_s=read_model._config.connect_timeout_s,
            )
            hil_decision_publisher = EventBusHilDecisionPublisher(
                bus=event_bus,
                topic=env.get(_env.HIL_TOPIC_ENV, "").strip() or DEFAULT_HIL_DECISION_TOPIC,
            )

        event_topic = env.get(_env.EVENT_TOPIC_ENV, "").strip()
        if kafka_bootstrap and event_topic:
            from fdai.core.incident import (
                DurableIncidentLifecycleNotifier,
                IncidentLifecycleWorkflow,
                IncidentRegistry,
                RoutedIncidentLifecycleNotifier,
            )
            from fdai.core.incident.sla import IncidentSlaMonitor, IncidentSlaPolicy
            from fdai.core.notifications.matrix import load_matrix_from_yaml
            from fdai.core.notifications.router import ChannelRegistry, NotificationRouter
            from fdai.delivery.notifications import StateStoreHilEscalationSink
            from fdai.delivery.read_api.routes.console_action import ConsoleActionSubmitter

            incident_registry = IncidentRegistry(state_store=state_store)
            notification_router = NotificationRouter(
                matrix=load_matrix_from_yaml(repo_root / "config" / "notifications-matrix.yaml"),
                registry=ChannelRegistry(),
                audit_store=state_store,
                hil_sink=StateStoreHilEscalationSink(state_store=state_store),
            )
            incident_notifier = DurableIncidentLifecycleNotifier(
                delegate=RoutedIncidentLifecycleNotifier(dispatcher=notification_router),
                delivery_store=PostgresIncidentNotificationDeliveryStore(config=state_store_config),
            )
            action_types = load_action_type_catalog(
                repo_root / "rule-catalog" / "action-types",
                schema_registry=PackageResourceSchemaRegistry(),
                probes_root=repo_root / "rule-catalog" / "probes",
            )
            console_action = ConsoleActionSubmitter(
                event_bus=event_bus,
                raw_event_topic=event_topic,
                action_type_names=frozenset(item.name for item in action_types),
                incident_workflow=IncidentLifecycleWorkflow(
                    registry=incident_registry,
                    notifier=incident_notifier,
                ),
                incident_proposals=PostgresIncidentProposalStore(config=state_store_config),
            )

            async def _rehydrate_incidents() -> None:
                entries = await state_store.read_incident_transitions()
                incident_registry.rehydrate(entries)
                await incident_notifier.replay(entries)

            startup_callbacks = (*startup_callbacks, _rehydrate_incidents)
            raw_sla_policy = env.get(_env.INCIDENT_SLA_POLICY_ENV, "").strip()
            if raw_sla_policy:
                try:
                    decoded_sla_policy = json.loads(raw_sla_policy)
                    if not isinstance(decoded_sla_policy, dict):
                        raise ValueError("policy MUST be a JSON object")
                    sla_policy = IncidentSlaPolicy.from_mapping(decoded_sla_policy)
                except (json.JSONDecodeError, ValueError) as exc:
                    raise ProdReadApiConfigError(
                        f"{_env.INCIDENT_SLA_POLICY_ENV} is invalid: {exc}"
                    ) from exc
                sla_monitor = IncidentSlaMonitor(
                    source=state_store,
                    notifier=incident_notifier,
                    policy=sla_policy,
                    interval_seconds=_parse_positive_int(
                        env,
                        _env.INCIDENT_SLA_INTERVAL_ENV,
                        60,
                    ),
                )
                startup_callbacks = (*startup_callbacks, sla_monitor.start)
                incident_sla_stop = sla_monitor.stop

        async def _close_event_transport() -> None:
            await event_bus.close()
            await http_client.aclose()

        shutdown_callbacks = (
            *((incident_sla_stop,) if incident_sla_stop is not None else ()),
            _close_event_transport,
        )

    return ProductionRuntimeWiring(
        hil_callback=hil_callback,
        hil_registry=hil_registry,
        hil_decision_publisher=hil_decision_publisher,
        live_stream=live_stream,
        agent_activity=agent_activity,
        console_action=console_action,
        event_bus=event_bus,
        event_topic=event_topic,
        startup_callbacks=startup_callbacks,
        shutdown_callbacks=shutdown_callbacks,
    )


__all__ = ["ProductionRuntimeWiring", "build_production_runtime"]
