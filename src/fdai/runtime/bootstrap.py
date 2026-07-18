"""Headless control-plane process lifecycle and shutdown coordination."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx

from fdai.agents import OWNED_OBJECT_TOPICS, PantheonRuntime, ShadowDivergenceLedger
from fdai.composition import (
    LlmBindings,
    default_container_from_env,
)
from fdai.core.chaos.coverage import ScenarioCoverageAggregator
from fdai.core.chaos.symptom_index import build_from_promoted
from fdai.core.control_loop import ControlLoop
from fdai.runtime.configuration import (
    _attach_runtime_github_change_feed,
    _attach_runtime_knowledge_source,
    _attach_runtime_metric_provider,
    _finalize_llm_bindings,
    _new_http_client,
    _summarize_config,
)
from fdai.runtime.consumers import (
    _consume,
    _consume_canaries,
    _consume_hil_decisions,
    _consume_resource_changes,
    _log_pantheon_exit,
)
from fdai.runtime.control_loop import (
    _build_control_loop,
    _build_irp_event_handler,
    _load_resource_types,
)
from fdai.runtime.delivery import _build_incident_notifier
from fdai.runtime.health import RuntimeHealthServer
from fdai.runtime.providers import _build_audit_store, _build_inventory_delta_projector
from fdai.shared.config.models import LlmMode
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger("fdai.startup")


async def _run() -> int:
    container = default_container_from_env()
    summary = _summarize_config(container)
    _LOGGER.info("startup_ok", extra={"config": summary})

    http_client: httpx.AsyncClient | None = None
    identity: WorkloadIdentity | None = None
    bus: EventBus | None = None
    pantheon_runtime: PantheonRuntime | None = None
    pantheon_heartbeat: float | None = None
    divergence_ledger: ShadowDivergenceLedger | None = None
    health_server: RuntimeHealthServer | None = None

    try:
        telemetry_requested = bool(
            os.environ.get("FDAI_MONITOR_WORKSPACE_ID", "").strip()
            or os.environ.get("FDAI_PROMETHEUS_ENDPOINT", "").strip()
        )
        if container.config.llm.mode == LlmMode.AZURE or telemetry_requested:
            from fdai.delivery.azure.workload_identity import (
                ManagedIdentityWorkloadIdentity,
            )

            http_client = _new_http_client()
            identity = ManagedIdentityWorkloadIdentity(http_client=http_client)

        if container.config.llm.mode == LlmMode.AZURE:
            if http_client is None or identity is None:
                raise RuntimeError("Azure LLM mode requires HTTP and workload identity bindings")
            container = await _finalize_llm_bindings(
                container, http_client=http_client, identity=identity
            )
            bindings: LlmBindings = container.require_llm_bindings()
            _LOGGER.info(
                "azure_llm_bindings_attached",
                extra={"cross_check_models": len(bindings.cross_check_models)},
            )
        elif telemetry_requested:
            if http_client is None or identity is None:
                raise RuntimeError("Azure telemetry requires HTTP and workload identity bindings")
            container = _attach_runtime_metric_provider(
                container,
                http_client=http_client,
                identity=identity,
            )
            container = _attach_runtime_knowledge_source(container)

        start_consumer = os.environ.get("FDAI_START_CONSUMER", "").lower() in (
            "1",
            "true",
        )
        control_loop: ControlLoop | None = None

        if start_consumer:
            from fdai.delivery.azure.event_bus import (
                EventHubsKafkaBus,
                EventHubsKafkaBusConfig,
            )

            if identity is None:
                from fdai.delivery.azure.workload_identity import (
                    ManagedIdentityWorkloadIdentity,
                )

                if http_client is None:
                    http_client = _new_http_client()
                identity = ManagedIdentityWorkloadIdentity(http_client=http_client)

            bus = EventHubsKafkaBus(
                identity=identity,
                config=EventHubsKafkaBusConfig(
                    bootstrap_servers=container.config.kafka.bootstrap_servers,
                    dlq_suffix=container.config.kafka.topic_dlq_suffix,
                ),
            )
            from fdai.delivery.event_bus_multiplex import MultiplexedEventBus

            bus = MultiplexedEventBus(
                bus=bus,
                logical_topics=OWNED_OBJECT_TOPICS,
                physical_topic=os.environ.get(
                    "FDAI_PANTHEON_OBJECT_TOPIC", "aw.pantheon.objects"
                ).strip(),
            )
            from fdai.delivery.read_api.streaming.agent_activity_broadcaster import (
                DEFAULT_STAGE_TOPIC,
            )
            from fdai.shared.streaming.stage_publisher import EventBusStagePublisher

            stage_topic = os.environ.get("FDAI_STAGE_TOPIC", "").strip() or DEFAULT_STAGE_TOPIC
            stage_publisher = EventBusStagePublisher(bus, topic=stage_topic)
            # A GitOps token opts into the real publisher; ensure an
            # http_client exists before _build_control_loop needs one.
            if os.environ.get("FDAI_GITOPS_TOKEN") and http_client is None:
                http_client = _new_http_client()
            if os.environ.get("FDAI_GITOPS_TOKEN") and http_client is not None:
                container = _attach_runtime_github_change_feed(
                    container,
                    http_client=http_client,
                )
            # Same for the HIL channel - an Incoming Webhook URL opts in.
            if os.environ.get("FDAI_CHATOPS_WEBHOOK_URL") and http_client is None:
                http_client = _new_http_client()
            if os.environ.get("FDAI_EMAIL_ENDPOINT") and http_client is None:
                http_client = _new_http_client()
            from fdai.core.incident import (
                IncidentLifecycleWorkflow,
                IncidentRegistry,
                link_ticket_receipt,
            )
            from fdai.shared.contracts.models import IncidentSeverity

            incident_audit_store = _build_audit_store()
            incident_registry = IncidentRegistry(state_store=incident_audit_store)
            incident_entries = await incident_audit_store.read_incident_transitions()
            incident_registry.rehydrate(incident_entries)
            incident_notifier = _build_incident_notifier(
                incident_audit_store,
                http_client=http_client,
            )
            await incident_notifier.replay(incident_entries)
            incident_workflow = IncidentLifecycleWorkflow(
                registry=incident_registry,
                notifier=incident_notifier,
                allowed_agent_principals={"Huginn", "Heimdall", "Forseti"},
            )

            async def _open_incident_candidate(candidate: dict[str, Any]) -> None:
                evidence_key = str(candidate.get("evidence_key") or "")
                resource_id = str(candidate.get("resource_id") or "")
                event_type = str(candidate.get("event_type") or "generic")
                if not evidence_key or not resource_id:
                    return
                evidence_id = uuid5(
                    NAMESPACE_URL,
                    f"fdai.incident.evidence://{evidence_key}",
                )
                await incident_workflow.open_from_agent(
                    producer_principal="Heimdall",
                    correlation_keys=(
                        f"resource:{resource_id}",
                        f"signal:{event_type}",
                    ),
                    severity=IncidentSeverity.SEV3,
                    member_event_ids=(evidence_id,),
                    reason=str(candidate.get("reason_code") or "detected_anomaly"),
                )

            async def _observe_tool_receipt(request: Any, receipt: Any) -> None:
                incident_id = request.metadata.get("incident_id") or request.arguments.get(
                    "incident_id"
                )
                provider = request.metadata.get("ticket_provider") or request.arguments.get(
                    "ticket_provider"
                )
                if not incident_id or not provider:
                    return
                await link_ticket_receipt(
                    registry=incident_registry,
                    request=request,
                    receipt=receipt,
                    actor_oid="Thor",
                )

            runtime_symptom_index = build_from_promoted()
            control_loop = _build_control_loop(
                container,
                http_client=http_client,
                stage_publisher=stage_publisher,
                audit_store=incident_audit_store,
                tool_receipt_observer=_observe_tool_receipt,
                symptom_index=runtime_symptom_index,
            )
            _LOGGER.info(
                "control_loop_ready",
                extra={
                    "topic": container.config.kafka.topic_events,
                    "stage_topic": stage_topic,
                    "group_id": "fdai-core",
                },
            )

            # Optional pantheon: the 15 named agents consume the same
            # ingress topic under distinct consumer groups (fan-out) and
            # react immediately. Opt-in via FDAI_START_PANTHEON and shadow
            # by default - the agents use in-memory audit / issue / admin
            # adapters and Thor's executor stays in shadow, so running it
            # beside the P1 loop adds no autonomous mutation. See
            # docs/roadmap/agents/agent-pantheon-implementation.md.
            start_pantheon = os.environ.get("FDAI_START_PANTHEON", "").lower() in (
                "1",
                "true",
            )
            if start_pantheon:
                pantheon_enforce = os.environ.get("FDAI_PANTHEON_ENFORCE", "").lower() in (
                    "1",
                    "true",
                )
                disabled_raw = os.environ.get("FDAI_PANTHEON_DISABLED_AGENTS", "").strip()
                disabled_agents = (
                    frozenset(n.strip() for n in disabled_raw.split(",") if n.strip())
                    if disabled_raw
                    else None
                )
                # Shared ledger: the pantheon observer records its shadow
                # verdict, the P1 consumer records the authoritative
                # decision; joined by correlation id to measure shadow
                # agreement (the promotion baseline).
                divergence_ledger = ShadowDivergenceLedger()
                pantheon_runtime = PantheonRuntime.build(
                    provider=bus,
                    raw_event_topic=container.config.kafka.topic_events,
                    enforce=pantheon_enforce,
                    disabled_agents=disabled_agents,
                    divergence=divergence_ledger,
                    incident_candidate_hook=_open_incident_candidate,
                    discovery_projector=_build_inventory_delta_projector(),
                    scenario_coverage_aggregator=ScenarioCoverageAggregator(
                        index=runtime_symptom_index
                    ),
                    action_types=control_loop.action_types,
                )
                hb_raw = os.environ.get("FDAI_PANTHEON_HEARTBEAT_SECONDS", "").strip()
                if hb_raw:
                    try:
                        pantheon_heartbeat = float(hb_raw)
                    except ValueError as hb_exc:
                        raise RuntimeError(
                            f"FDAI_PANTHEON_HEARTBEAT_SECONDS={hb_raw!r} is not a float"
                        ) from hb_exc
                    if pantheon_heartbeat <= 0:
                        raise RuntimeError(
                            f"FDAI_PANTHEON_HEARTBEAT_SECONDS MUST be > 0; got {pantheon_heartbeat}"
                        )
                _LOGGER.info(
                    "pantheon_ready",
                    extra={
                        "agents": len(pantheon_runtime.agents),
                        "subscriptions": pantheon_runtime.subscription_count,
                        "enforce": pantheon_enforce,
                        "heartbeat_s": pantheon_heartbeat,
                    },
                )
        elif os.environ.get("FDAI_START_PANTHEON", "").lower() in ("1", "true"):
            # Pantheon needs the same Kafka bus the consumer builds; without
            # FDAI_START_CONSUMER there is no bus to bind to. Warn rather
            # than silently no-op so a miswired container is visible.
            _LOGGER.warning("pantheon_requested_without_consumer")

        health_port_raw = os.environ.get("FDAI_HEALTH_PORT", "").strip()
        if health_port_raw:
            if control_loop is None:
                raise RuntimeError(
                    "FDAI_HEALTH_PORT requires a ready control loop; set FDAI_START_CONSUMER=1"
                )
            try:
                health_port = int(health_port_raw)
            except ValueError as port_error:
                raise RuntimeError("FDAI_HEALTH_PORT MUST be an integer") from port_error
            health_server = RuntimeHealthServer(port=health_port)
            await health_server.start()
            _LOGGER.info("health_server_ready", extra={"port": health_port})

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()

        def _signal_stop(signame: str) -> None:
            _LOGGER.info("shutdown_signal", extra={"signal": signame})
            stop.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _signal_stop, sig.name)

        if bus is not None and control_loop is not None:
            consumer_task = asyncio.create_task(
                _consume(
                    bus=bus,
                    topic=container.config.kafka.topic_events,
                    group_id="fdai-core",
                    control_loop=control_loop,
                    stop=stop,
                    divergence=divergence_ledger,
                    irp_handler=_build_irp_event_handler(container=container, bus=bus),
                )
            )
            resource_change_task: asyncio.Task[None] | None = None
            inventory_raw_topic = os.environ.get("FDAI_INVENTORY_RAW_TOPIC", "").strip()
            if inventory_raw_topic:
                resource_change_task = asyncio.create_task(
                    _consume_resource_changes(
                        bus=bus,
                        raw_topic=inventory_raw_topic,
                        canonical_topic=container.config.kafka.topic_events,
                        resource_types=_load_resource_types(),
                        stop=stop,
                    ),
                    name="huginn-resource-discovery",
                )
            canary_task: asyncio.Task[None] | None = None
            canary_topic = os.environ.get("FDAI_CANARY_TOPIC", "").strip()
            if canary_topic:
                canary_task = asyncio.create_task(
                    _consume_canaries(
                        bus=bus,
                        topic=canary_topic,
                        control_loop=control_loop,
                        stop=stop,
                    ),
                    name="canary-consumer",
                )
            hil_decision_task: asyncio.Task[None] | None = None
            if control_loop._hil_resume_coordinator is not None:
                from fdai.delivery.chatops.hil_decision import DEFAULT_HIL_DECISION_TOPIC

                hil_decision_task = asyncio.create_task(
                    _consume_hil_decisions(
                        bus=bus,
                        topic=os.environ.get("FDAI_HIL_DECISION_TOPIC", DEFAULT_HIL_DECISION_TOPIC),
                        coordinator=control_loop._hil_resume_coordinator,
                        stop=stop,
                    ),
                    name="hil-decision-consumer",
                )
            wait_task = asyncio.create_task(stop.wait())

            # Blast-radius isolation: the pantheon runs OUTSIDE the P1 wait
            # set. A pantheon crash is logged via a done-callback but MUST
            # NOT bring down the P1 control plane; P1 shutdown cancels it
            # in turn. The pantheon is a shadow overlay, never a dependency
            # of the primary pipeline.
            pantheon_task: asyncio.Task[None] | None = None
            if pantheon_runtime is not None:
                pantheon_task = asyncio.create_task(
                    pantheon_runtime.run(heartbeat_interval=pantheon_heartbeat),
                    name="pantheon-runtime",
                )
                pantheon_task.add_done_callback(_log_pantheon_exit)

            wait_set = {consumer_task, wait_task}
            if resource_change_task is not None:
                wait_set.add(resource_change_task)
            if canary_task is not None:
                wait_set.add(canary_task)
            if hil_decision_task is not None:
                wait_set.add(hil_decision_task)
            done, _pending = await asyncio.wait(
                wait_set,
                return_when=asyncio.FIRST_COMPLETED,
            )
            consumer_task.cancel()
            wait_task.cancel()
            if resource_change_task is not None:
                resource_change_task.cancel()
            if canary_task is not None:
                canary_task.cancel()
            if hil_decision_task is not None:
                hil_decision_task.cancel()
            if pantheon_task is not None:
                pantheon_task.cancel()
            # Await the cancels so cleanup can drain the consumer's
            # ``async for`` + finally (which stops the AIOKafkaConsumer)
            # before we tear down the bus / HTTP client in the outer
            # ``finally``. Without this a cancelled consumer can be
            # racing the aiokafka close and log noisy warnings on exit.
            cleanup_tasks: list[asyncio.Task[Any]] = [consumer_task, wait_task]
            if resource_change_task is not None:
                cleanup_tasks.append(resource_change_task)
            if canary_task is not None:
                cleanup_tasks.append(canary_task)
            if hil_decision_task is not None:
                cleanup_tasks.append(hil_decision_task)
            if pantheon_task is not None:
                cleanup_tasks.append(pantheon_task)
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            for task in done:
                exc = task.exception()
                if exc is not None:
                    _LOGGER.error("consumer_task_failed", exc_info=exc)
        else:
            await stop.wait()

        _LOGGER.info("shutdown_complete")
        return 0
    finally:
        if health_server is not None:
            try:
                await health_server.close()
            except Exception:  # noqa: BLE001
                _LOGGER.warning("health_server_stop_failed", exc_info=True)
        if pantheon_runtime is not None:
            try:
                await pantheon_runtime.stop()
            except Exception:  # noqa: BLE001
                _LOGGER.warning("pantheon_stop_failed", exc_info=True)
        if bus is not None:
            close = getattr(bus, "close", None)
            if callable(close):
                try:
                    await close()
                except Exception:  # noqa: BLE001
                    _LOGGER.warning("bus_close_failed", exc_info=True)
        if http_client is not None:
            try:
                await http_client.aclose()
            except Exception:  # noqa: BLE001
                _LOGGER.warning("http_client_close_failed", exc_info=True)


def main() -> int:
    # Bootstrap the plain-text formatter for the tiny window before
    # `default_container_from_env()` swaps in the marked JSON handler via
    # `configure_telemetry`. `force=True` guarantees that if the caller
    # already installed a root handler (uvicorn, pytest fixtures) we
    # override cleanly instead of stacking - otherwise every log line
    # would emit twice, once as plain text and once as JSON, once the
    # composition root wires the JSON formatter.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s :: %(message)s",
        force=True,
    )
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 0
