"""Headless control-plane process lifecycle and shutdown coordination."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import httpx

from fdai.agents import (
    OWNED_OBJECT_TOPICS,
    PantheonRuntime,
    Saga,
    ShadowDivergenceLedger,
    StateStoreAuditChainAdapter,
)
from fdai.composition import (
    LlmBindings,
    default_container_from_env,
)
from fdai.core.chaos.coverage import ScenarioCoverageAggregator
from fdai.core.chaos.symptom_index import build_from_promoted
from fdai.core.control_loop import ControlLoop
from fdai.core.learning import PostTurnProposalModel, RuleHintSubmitter
from fdai.core.readiness import AuthorityCeiling
from fdai.delivery.read_api.streaming.agent_activity_stream import (
    runtime_agent_state_snapshot,
)
from fdai.delivery.read_api.streaming.agent_runtime_state_publisher import (
    AgentRuntimeStatePublisher,
)
from fdai.delivery.startup_probe import OpaCompileStartupProbe
from fdai.runtime.case_history import (
    CaseHistoryRetentionTickPublisher,
    CaseHistoryRuntime,
    build_case_history_runtime,
    case_history_retention_days,
    case_history_retention_tick_seconds,
)
from fdai.runtime.configuration import (
    _attach_runtime_github_change_feed,
    _attach_runtime_knowledge_source,
    _attach_runtime_metric_provider,
    _finalize_llm_bindings,
    _new_http_client,
    _resolve_catalog_root,
    _resolve_policies_root,
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
from fdai.runtime.post_turn_review import (
    build_azure_post_turn_models,
    build_post_turn_review_runtime,
    post_turn_review_dsn,
)
from fdai.runtime.providers import (
    _build_audit_store,
    _build_inventory_delta_projector,
    _build_operator_memory_store,
)
from fdai.runtime.readiness import (
    StartupReadinessRuntime,
    build_startup_readiness_runtime,
)
from fdai.shared.config.models import LlmMode
from fdai.shared.config.runtime_flags import pantheon_start_enabled
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger("fdai.startup")
_AUXILIARY_KAFKA_BOOTSTRAP_ENV = "FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS"


def _operational_event_bus(primary: EventBus, auxiliary: EventBus | None) -> EventBus:
    """Select the isolated bus for raw inventory and canary traffic when configured."""

    return auxiliary or primary


def _build_runtime_workload_identity(
    http_client: httpx.AsyncClient,
    *,
    client_id_env: str = "FDAI_MI_CLIENT_ID",
    require_client_id: bool = False,
) -> WorkloadIdentity:
    if (
        os.environ.get("RUNTIME_ENV", "").strip().lower() == "dev"
        and os.environ.get("FDAI_RUNTIME_LOCAL_AZURE_CLI", "").strip() == "1"
    ):
        from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity

        return AsyncAzureCliWorkloadIdentity()

    from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity

    if require_client_id and not os.environ.get(client_id_env, "").strip():
        raise RuntimeError(f"{client_id_env} MUST identify the dedicated workload identity")
    return ManagedIdentityWorkloadIdentity.from_env(
        http_client=http_client,
        client_id_env=client_id_env,
    )


def _case_history_identity_client_id(environment: Mapping[str, str]) -> str:
    client_id = environment.get("FDAI_CASE_HISTORY_MI_CLIENT_ID", "").strip()
    if not client_id:
        raise RuntimeError(
            "FDAI_CASE_HISTORY_MI_CLIENT_ID MUST identify the dedicated workload identity"
        )
    executor_client_id = environment.get("FDAI_MI_CLIENT_ID", "").strip()
    if executor_client_id and client_id == executor_client_id:
        raise RuntimeError("case history and executor workload identities MUST be distinct")
    return client_id


def _build_runtime_saga(state_store: StateStore) -> Saga:
    return Saga(audit_chain=StateStoreAuditChainAdapter(store=state_store))


def _raise_required_task_failure(done: set[asyncio.Task[Any]]) -> None:
    for task in done:
        if task.cancelled():
            continue
        failure = task.exception()
        if failure is None:
            continue
        _LOGGER.error(
            "required_runtime_task_failed",
            extra={"task": task.get_name()},
            exc_info=failure,
        )
        raise RuntimeError(f"required runtime task failed: {task.get_name()}") from failure


async def _run() -> int:
    container = default_container_from_env()
    summary = _summarize_config(container)
    _LOGGER.info("startup_ok", extra={"config": summary})

    http_client: httpx.AsyncClient | None = None
    identity: WorkloadIdentity | None = None
    bus: EventBus | None = None
    auxiliary_bus: EventBus | None = None
    pantheon_runtime: PantheonRuntime | None = None
    runtime_state_publisher: AgentRuntimeStatePublisher | None = None
    pantheon_heartbeat: float | None = None
    divergence_ledger: ShadowDivergenceLedger | None = None
    health_server: RuntimeHealthServer | None = None
    case_history_runtime: CaseHistoryRuntime | None = None
    case_history_retention_publisher: CaseHistoryRetentionTickPublisher | None = None
    startup_readiness_runtime: StartupReadinessRuntime | None = None

    try:
        telemetry_requested = bool(
            os.environ.get("FDAI_MONITOR_WORKSPACE_ID", "").strip()
            or os.environ.get("FDAI_PROMETHEUS_ENDPOINT", "").strip()
        )
        gateway_requested = bool(os.environ.get("FDAI_DEV_OPERATIONS_GATEWAY_URL", "").strip())
        case_history_requested = bool(os.environ.get("FDAI_CASE_HISTORY_CONTAINER_URL", "").strip())
        if case_history_requested:
            _case_history_identity_client_id(os.environ)
        if (
            container.config.llm.mode == LlmMode.AZURE
            or telemetry_requested
            or gateway_requested
            or case_history_requested
        ):
            http_client = _new_http_client()
            identity = _build_runtime_workload_identity(http_client)

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
                if http_client is None:
                    http_client = _new_http_client()
                identity = _build_runtime_workload_identity(http_client)

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
            auxiliary_bootstrap = os.environ.get(_AUXILIARY_KAFKA_BOOTSTRAP_ENV, "").strip()
            if auxiliary_bootstrap:
                auxiliary_bus = EventHubsKafkaBus(
                    identity=identity,
                    config=EventHubsKafkaBusConfig(
                        bootstrap_servers=auxiliary_bootstrap,
                        dlq_suffix=container.config.kafka.topic_dlq_suffix,
                    ),
                )
            operational_bus = _operational_event_bus(bus, auxiliary_bus)
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
                detected_incident_correlation_keys,
                detected_incident_event_id,
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
                await incident_workflow.open_from_agent(
                    producer_principal="Heimdall",
                    correlation_keys=detected_incident_correlation_keys(
                        resource_id=resource_id,
                        event_type=event_type,
                        correlation_id=str(candidate.get("correlation_id") or ""),
                    ),
                    severity=IncidentSeverity.SEV3,
                    member_event_ids=(detected_incident_event_id(evidence_key),),
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
                identity=identity,
            )
            _LOGGER.info(
                "control_loop_ready",
                extra={
                    "topic": container.config.kafka.topic_events,
                    "stage_topic": stage_topic,
                    "group_id": "fdai-core",
                },
            )
            startup_readiness_runtime = build_startup_readiness_runtime(
                state_store=incident_audit_store,
                event_bus=bus,
                event_validator=container.event_validator,
                identity=identity,
                embedding_model=container.require_llm_bindings().embedding_model,
                policy_compile_probe=OpaCompileStartupProbe(
                    probe_id="policy.compile",
                    policies_root=_resolve_policies_root(_resolve_catalog_root()),
                ),
                cross_check_models=container.require_llm_bindings().cross_check_models,
                environment=os.environ,
                registered_specs=container.startup_probe_specs,
                registered_probes=container.startup_probes,
            )
            startup_report = await startup_readiness_runtime.evaluate()
            _LOGGER.info(
                "startup_readiness_evaluated",
                extra={
                    "decision": startup_report.decision.value,
                    "probe_count": len(startup_report.results),
                    "missing_count": len(startup_report.missing_probe_ids),
                    "stale_count": len(startup_report.stale_probe_ids),
                },
            )

            # Pantheon: the 15 named agents consume the same
            # ingress topic under distinct consumer groups (fan-out) and
            # react immediately. Enabled by default; FDAI_START_PANTHEON=0
            # is the explicit maintenance escape hatch. Thor stays shadow
            # by default - the agents use in-memory audit / issue / admin
            # adapters and Thor's executor stays in shadow, so running it
            # beside the P1 loop adds no autonomous mutation. See
            # docs/roadmap/agents/agent-pantheon-implementation.md.
            start_pantheon = pantheon_start_enabled(os.environ)
            if start_pantheon:
                pantheon_enforce = os.environ.get("FDAI_PANTHEON_ENFORCE", "").lower() in (
                    "1",
                    "true",
                )
                if (
                    startup_report.authority_ceilings.get("autonomous-action")
                    is not AuthorityCeiling.DEPLOYMENT
                ):
                    pantheon_enforce = False
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
                post_turn_models: tuple[PostTurnProposalModel, ...] = ()
                if container.config.llm.mode == LlmMode.AZURE:
                    if http_client is None or identity is None:
                        raise RuntimeError(
                            "Azure post-turn review requires HTTP and workload identity bindings"
                        )
                    resolved_models_path = container.config.llm.resolved_models_path
                    if resolved_models_path is None:
                        raise RuntimeError(
                            "Azure post-turn review requires resolved model configuration"
                        )
                    post_turn_models = build_azure_post_turn_models(
                        repo_root=Path(__file__).resolve().parents[3],
                        resolved_models_path=resolved_models_path,
                        endpoint=os.environ["FDAI_LLM_ENDPOINT"],
                        identity=identity,
                        http_client=http_client,
                    )
                post_turn_review = build_post_turn_review_runtime(
                    state_store=incident_audit_store,
                    operator_memory=_build_operator_memory_store(),
                    models=post_turn_models,
                    dsn=post_turn_review_dsn(),
                )
                case_history_container_url = (
                    os.environ.get("FDAI_CASE_HISTORY_CONTAINER_URL", "").strip() or None
                )
                case_history_identity = None
                if case_history_container_url is not None:
                    if http_client is None:
                        raise RuntimeError("case history storage requires an HTTP client")
                    case_history_identity = _build_runtime_workload_identity(
                        http_client,
                        client_id_env="FDAI_CASE_HISTORY_MI_CLIENT_ID",
                        require_client_id=True,
                    )
                case_history_runtime = build_case_history_runtime(
                    container_url=case_history_container_url,
                    state_store=incident_audit_store,
                    identity=case_history_identity,
                    http_client=http_client,
                    models=post_turn_models,
                )
                if case_history_runtime is not None:
                    case_history_retention_publisher = CaseHistoryRetentionTickPublisher(
                        bus=bus,
                        topic=container.config.kafka.topic_events,
                        interval_seconds=case_history_retention_tick_seconds(
                            os.environ.get("FDAI_CASE_HISTORY_RETENTION_TICK_SECONDS")
                        ),
                    )
                case_retention_days, case_deletion_days = case_history_retention_days(
                    os.environ.get("FDAI_CASE_HISTORY_RETENTION_DAYS"),
                    os.environ.get("FDAI_CASE_HISTORY_DELETION_DAYS"),
                )
                pantheon_runtime = PantheonRuntime.build(
                    provider=bus,
                    raw_event_topic=container.config.kafka.topic_events,
                    consumer_group_prefix=os.environ.get(
                        "FDAI_PANTHEON_CONSUMER_GROUP_PREFIX",
                        "fdai-pantheon",
                    ).strip(),
                    enforce=pantheon_enforce,
                    saga=_build_runtime_saga(incident_audit_store),
                    disabled_agents=disabled_agents,
                    divergence=divergence_ledger,
                    incident_candidate_hook=_open_incident_candidate,
                    discovery_projector=_build_inventory_delta_projector(),
                    scenario_coverage_aggregator=ScenarioCoverageAggregator(
                        index=runtime_symptom_index
                    ),
                    post_turn_review=post_turn_review.coordinator,
                    case_history_materializer=(
                        case_history_runtime.materializer
                        if case_history_runtime is not None
                        else None
                    ),
                    case_history_analyzer=(
                        case_history_runtime.analyzer if case_history_runtime is not None else None
                    ),
                    case_history_retention=(
                        case_history_runtime.retention if case_history_runtime is not None else None
                    ),
                    case_retention_days=case_retention_days,
                    case_deletion_days=case_deletion_days,
                    action_types=control_loop.action_types,
                )
                runtime_state_publisher = AgentRuntimeStatePublisher(
                    event_bus=bus,
                    snapshot_factory=lambda: runtime_agent_state_snapshot(
                        pantheon_runtime.health()
                    ),
                    topic=stage_topic,
                )
                norns = pantheon_runtime.agents.get("Norns")
                if norns is not None:
                    post_turn_review.bind_rule_hints(cast(RuleHintSubmitter, norns))
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
        elif pantheon_start_enabled(os.environ):
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
            if startup_readiness_runtime is None:
                raise RuntimeError("FDAI_HEALTH_PORT requires startup readiness composition")
            health_server = RuntimeHealthServer(
                port=health_port,
                readiness=startup_readiness_runtime.state.is_ready,
            )
            await health_server.start()
            _LOGGER.info("health_server_ready", extra={"port": health_port})

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()

        def _signal_stop(signame: str) -> None:
            _LOGGER.info("shutdown_signal", extra={"signal": signame})
            stop.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _signal_stop, sig.name)

        if bus is not None and control_loop is not None and startup_readiness_runtime is not None:
            readiness_refresh_task = asyncio.create_task(
                startup_readiness_runtime.refresh_until_stopped(stop),
                name="startup-readiness-refresh",
            )
            consumer_task = asyncio.create_task(
                startup_readiness_runtime.run_when_ready(
                    stop,
                    lambda: _consume(
                        bus=bus,
                        topic=container.config.kafka.topic_events,
                        group_id=os.environ.get(
                            "FDAI_CORE_CONSUMER_GROUP_ID",
                            "fdai-core",
                        ).strip(),
                        control_loop=control_loop,
                        stop=stop,
                        divergence=divergence_ledger,
                        irp_handler=_build_irp_event_handler(container=container, bus=bus),
                    ),
                )
            )
            resource_change_task: asyncio.Task[None] | None = None
            inventory_raw_topic = os.environ.get("FDAI_INVENTORY_RAW_TOPIC", "").strip()
            if inventory_raw_topic:
                resource_change_task = asyncio.create_task(
                    startup_readiness_runtime.run_when_ready(
                        stop,
                        lambda: _consume_resource_changes(
                            bus=operational_bus,
                            raw_topic=inventory_raw_topic,
                            canonical_topic=container.config.kafka.topic_events,
                            resource_types=_load_resource_types(),
                            stop=stop,
                        ),
                    ),
                    name="huginn-resource-discovery",
                )
            canary_task: asyncio.Task[None] | None = None
            canary_topic = os.environ.get("FDAI_CANARY_TOPIC", "").strip()
            if canary_topic:
                canary_task = asyncio.create_task(
                    startup_readiness_runtime.run_when_ready(
                        stop,
                        lambda: _consume_canaries(
                            bus=operational_bus,
                            topic=canary_topic,
                            control_loop=control_loop,
                            stop=stop,
                        ),
                    ),
                    name="canary-consumer",
                )
            hil_decision_task: asyncio.Task[None] | None = None
            if control_loop._hil_resume_coordinator is not None:
                from fdai.delivery.chatops.hil_decision import DEFAULT_HIL_DECISION_TOPIC

                hil_coordinator = control_loop._hil_resume_coordinator
                hil_decision_task = asyncio.create_task(
                    startup_readiness_runtime.run_when_ready(
                        stop,
                        lambda: _consume_hil_decisions(
                            bus=bus,
                            topic=os.environ.get(
                                "FDAI_HIL_DECISION_TOPIC",
                                DEFAULT_HIL_DECISION_TOPIC,
                            ),
                            coordinator=hil_coordinator,
                            stop=stop,
                        ),
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
            runtime_state_task: asyncio.Task[None] | None = None
            case_history_retention_task: asyncio.Task[None] | None = None
            if pantheon_runtime is not None:
                pantheon_task = asyncio.create_task(
                    startup_readiness_runtime.run_when_ready(
                        stop,
                        lambda: pantheon_runtime.run(heartbeat_interval=pantheon_heartbeat),
                    ),
                    name="pantheon-runtime",
                )
                pantheon_task.add_done_callback(_log_pantheon_exit)
            if runtime_state_publisher is not None:
                runtime_state_task = asyncio.create_task(
                    startup_readiness_runtime.run_when_ready(
                        stop,
                        runtime_state_publisher.run,
                    ),
                    name="pantheon-runtime-state",
                )
            if case_history_retention_publisher is not None:
                case_history_retention_task = asyncio.create_task(
                    startup_readiness_runtime.run_when_ready(
                        stop,
                        lambda: case_history_retention_publisher.run(stop=stop),
                    ),
                    name="case-history-retention-ticks",
                )

            wait_set = {consumer_task, readiness_refresh_task, wait_task}
            if resource_change_task is not None:
                wait_set.add(resource_change_task)
            if canary_task is not None:
                wait_set.add(canary_task)
            if hil_decision_task is not None:
                wait_set.add(hil_decision_task)
            if case_history_retention_task is not None:
                wait_set.add(case_history_retention_task)
            done, _pending = await asyncio.wait(
                wait_set,
                return_when=asyncio.FIRST_COMPLETED,
            )
            consumer_task.cancel()
            readiness_refresh_task.cancel()
            wait_task.cancel()
            if resource_change_task is not None:
                resource_change_task.cancel()
            if canary_task is not None:
                canary_task.cancel()
            if hil_decision_task is not None:
                hil_decision_task.cancel()
            if pantheon_task is not None:
                pantheon_task.cancel()
            if runtime_state_task is not None:
                runtime_state_task.cancel()
            if case_history_retention_task is not None:
                case_history_retention_task.cancel()
            # Await the cancels so cleanup can drain the consumer's
            # ``async for`` + finally (which stops the AIOKafkaConsumer)
            # before we tear down the bus / HTTP client in the outer
            # ``finally``. Without this a cancelled consumer can be
            # racing the aiokafka close and log noisy warnings on exit.
            cleanup_tasks: list[asyncio.Task[Any]] = [
                consumer_task,
                readiness_refresh_task,
                wait_task,
            ]
            if resource_change_task is not None:
                cleanup_tasks.append(resource_change_task)
            if canary_task is not None:
                cleanup_tasks.append(canary_task)
            if hil_decision_task is not None:
                cleanup_tasks.append(hil_decision_task)
            if pantheon_task is not None:
                cleanup_tasks.append(pantheon_task)
            if runtime_state_task is not None:
                cleanup_tasks.append(runtime_state_task)
            if case_history_retention_task is not None:
                cleanup_tasks.append(case_history_retention_task)
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            _raise_required_task_failure(done)
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
        if runtime_state_publisher is not None:
            await runtime_state_publisher.stop()
        if auxiliary_bus is not None:
            close = getattr(auxiliary_bus, "close", None)
            if callable(close):
                try:
                    await close()
                except Exception:  # noqa: BLE001
                    _LOGGER.warning("auxiliary_bus_close_failed", exc_info=True)
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
