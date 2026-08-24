"""Runtime task creation and supervision for the headless control plane."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

from fdai.agents import PantheonRuntime, ShadowDivergenceLedger
from fdai.composition import Container
from fdai.composition.readiness import OperationalReadinessEventHandler
from fdai.core.control_loop import ControlLoop
from fdai.delivery.agent_activity import AgentRuntimeStatePublisher
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.runtime.bootstrap_bindings import (
    EffectReconciliationRequestRuntimeBinding,
    RuleGenerationRuntimeBinding,
)
from fdai.runtime.case_history import CaseHistoryRetentionTickPublisher
from fdai.runtime.discovery_activation import DiscoveryActivationRuntime
from fdai.runtime.readiness import StartupReadinessRuntime
from fdai.runtime.rule_generation_documents import RuleGenerationReconciliation
from fdai.shared.providers.event_bus import EventBus


@dataclass(frozen=True, slots=True)
class RuntimeTaskConfiguration:
    """Bound runtime resources consumed by task creation and supervision."""

    container: Container
    bus: EventBus
    operational_bus: EventBus
    control_loop: ControlLoop
    readiness: StartupReadinessRuntime
    stop: asyncio.Event
    runtime_settings: RuntimeSettingsService
    discovery_activation: DiscoveryActivationRuntime | None
    semantic_turn_binding: Any
    divergence_ledger: ShadowDivergenceLedger | None
    pantheon_runtime: PantheonRuntime | None
    pantheon_heartbeat: float | None
    agent_introspection_server: Any
    runtime_state_publisher: AgentRuntimeStatePublisher | None
    t2_recovery_maintenance: Any
    assignment_reconciliation_worker: Any
    effect_reconciliation_worker: Any
    effect_reconciliation_request_binding: EffectReconciliationRequestRuntimeBinding | None
    rule_generation_binding: RuleGenerationRuntimeBinding | None
    rule_generation_reconciliation: RuleGenerationReconciliation | None
    case_history_retention_publisher: CaseHistoryRetentionTickPublisher | None
    environment: Mapping[str, str]
    read_investigation_binding: Any = None
    operational_readiness_handler: OperationalReadinessEventHandler | None = None


@dataclass(frozen=True, slots=True)
class RuntimeTaskHooks:
    """Bootstrap-owned call seams used while constructing runtime tasks."""

    consume: Any
    consume_resource_changes: Any
    consume_canaries: Any
    consume_hil_decisions: Any
    consume_operational_readiness: Any
    build_irp_event_handler: Any
    load_resource_types: Any
    schedule_semantic_turn_consumer: Any
    log_pantheon_exit: Any
    run_effect_reconciliation: Any
    run_effect_reconciliation_request_outbox: Any
    run_rule_generation_outbox_publisher: Any
    log_rule_generation_outbox_exit: Any
    publish_rule_generation_reconciliation: Any
    supervise_runtime_tasks: Any


def schedule_semantic_turn_consumer(
    *,
    binding: Any,
    readiness: StartupReadinessRuntime,
    bus: EventBus,
    stop: asyncio.Event,
) -> asyncio.Task[None] | None:
    """Schedule the semantic-turn consumer only when its binding exists."""

    if binding is None:
        return None
    return asyncio.create_task(
        readiness.run_when_ready(
            stop,
            lambda: binding.run(bus=bus, stop=stop),
        ),
        name="semantic-turn-consumer",
    )


async def run_runtime_tasks(
    config: RuntimeTaskConfiguration,
    hooks: RuntimeTaskHooks,
) -> None:
    """Create, supervise, cancel, and drain the configured runtime tasks."""

    readiness_refresh_task = asyncio.create_task(
        config.readiness.refresh_until_stopped(config.stop),
        name="startup-readiness-refresh",
    )
    consumer_task = asyncio.create_task(
        config.readiness.run_when_ready(
            config.stop,
            lambda: hooks.consume(
                bus=config.bus,
                topic=config.container.config.kafka.topic_events,
                group_id=config.environment.get(
                    "FDAI_CORE_CONSUMER_GROUP_ID",
                    "fdai-core",
                ).strip(),
                control_loop=config.control_loop,
                stop=config.stop,
                divergence=config.divergence_ledger,
                irp_handler=hooks.build_irp_event_handler(
                    container=config.container,
                    bus=config.bus,
                    runtime_settings=config.runtime_settings,
                ),
            ),
        )
    )
    resource_change_task: asyncio.Task[None] | None = None
    inventory_raw_topic = config.environment.get("FDAI_INVENTORY_RAW_TOPIC", "").strip()
    if inventory_raw_topic:
        resource_change_task = asyncio.create_task(
            config.readiness.run_when_ready(
                config.stop,
                lambda: hooks.consume_resource_changes(
                    bus=config.operational_bus,
                    raw_topic=inventory_raw_topic,
                    canonical_topic=config.container.config.kafka.topic_events,
                    resource_types=hooks.load_resource_types(),
                    stop=config.stop,
                ),
            ),
            name="huginn-resource-discovery",
        )
    canary_task: asyncio.Task[None] | None = None
    canary_topic = config.environment.get("FDAI_CANARY_TOPIC", "").strip()
    if canary_topic:
        canary_task = asyncio.create_task(
            config.readiness.run_when_ready(
                config.stop,
                lambda: hooks.consume_canaries(
                    bus=config.operational_bus,
                    topic=canary_topic,
                    control_loop=config.control_loop,
                    stop=config.stop,
                ),
            ),
            name="canary-consumer",
        )
    hil_decision_task: asyncio.Task[None] | None = None
    hil_reminder_task: asyncio.Task[None] | None = None
    hil_escalation_task: asyncio.Task[None] | None = None
    semantic_turn_task = hooks.schedule_semantic_turn_consumer(
        binding=config.semantic_turn_binding,
        readiness=config.readiness,
        bus=config.bus,
        stop=config.stop,
    )
    read_investigation_task: asyncio.Task[None] | None = None
    if config.read_investigation_binding is not None:
        read_investigation_task = asyncio.create_task(
            config.readiness.run_when_ready(
                config.stop,
                lambda: config.read_investigation_binding.run(
                    bus=config.bus,
                    stop=config.stop,
                ),
            ),
            name="read-investigation-runtime",
        )
    operational_readiness_task: asyncio.Task[None] | None = None
    if config.operational_readiness_handler is not None:
        operational_readiness_task = asyncio.create_task(
            config.readiness.run_when_ready(
                config.stop,
                lambda: hooks.consume_operational_readiness(
                    bus=config.bus,
                    topic=config.container.config.kafka.topic_events,
                    group_id=config.environment.get(
                        "FDAI_OPERATIONAL_READINESS_CONSUMER_GROUP_ID",
                        "fdai-operational-readiness",
                    ).strip(),
                    handler=config.operational_readiness_handler,
                    stop=config.stop,
                ),
            ),
            name="operational-readiness-consumer",
        )
    if config.control_loop._hil_resume_coordinator is not None:
        from fdai.delivery.chatops.hil_decision import DEFAULT_HIL_DECISION_TOPIC

        hil_coordinator = config.control_loop._hil_resume_coordinator
        hil_decision_task = asyncio.create_task(
            config.readiness.run_when_ready(
                config.stop,
                lambda: hooks.consume_hil_decisions(
                    bus=config.bus,
                    topic=config.environment.get(
                        "FDAI_HIL_DECISION_TOPIC",
                        DEFAULT_HIL_DECISION_TOPIC,
                    ),
                    coordinator=hil_coordinator,
                    stop=config.stop,
                ),
            ),
            name="hil-decision-consumer",
        )
        reminder_dispatcher = hil_coordinator.reminder_dispatcher
        if reminder_dispatcher is not None:
            hil_reminder_task = asyncio.create_task(
                config.readiness.run_when_ready(
                    config.stop,
                    lambda: reminder_dispatcher.run(config.stop),
                ),
                name="hil-approval-reminders",
            )
        escalation_supervisor = hil_coordinator.escalation_supervisor
        if escalation_supervisor is not None:
            hil_escalation_task = asyncio.create_task(
                config.readiness.run_when_ready(
                    config.stop,
                    lambda: escalation_supervisor.run(config.stop),
                ),
                name="hil-escalation-supervisor",
            )
    wait_task = asyncio.create_task(config.stop.wait())

    pantheon_task: asyncio.Task[None] | None = None
    agent_introspection_task: asyncio.Task[None] | None = None
    runtime_state_task: asyncio.Task[None] | None = None
    t2_recovery_task: asyncio.Task[None] | None = None
    assignment_reconciliation_task: asyncio.Task[None] | None = None
    effect_reconciliation_task: asyncio.Task[None] | None = None
    effect_reconciliation_request_task: asyncio.Task[None] | None = None
    rule_generation_outbox_task: asyncio.Task[None] | None = None
    rule_generation_reconciliation_task: asyncio.Task[None] | None = None
    case_history_retention_task: asyncio.Task[None] | None = None
    discovery_activation_task: asyncio.Task[None] | None = None
    pantheon_runtime = config.pantheon_runtime
    if pantheon_runtime is not None:
        pantheon_task = asyncio.create_task(
            config.readiness.run_when_ready(
                config.stop,
                lambda: pantheon_runtime.run(heartbeat_interval=config.pantheon_heartbeat),
            ),
            name="pantheon-runtime",
        )
        pantheon_task.add_done_callback(partial(hooks.log_pantheon_exit, stop=config.stop))
    if config.agent_introspection_server is not None:
        agent_introspection_task = asyncio.create_task(
            config.readiness.run_when_ready(
                config.stop,
                config.agent_introspection_server.run,
            ),
            name="agent-introspection-server",
        )
    if config.runtime_state_publisher is not None:
        runtime_state_task = asyncio.create_task(
            config.readiness.run_when_ready(
                config.stop,
                config.runtime_state_publisher.run,
            ),
            name="pantheon-runtime-state",
        )
    if config.t2_recovery_maintenance is not None:
        t2_recovery_task = asyncio.create_task(
            config.readiness.run_when_ready(
                config.stop,
                lambda: config.t2_recovery_maintenance.run(config.stop),
            ),
            name="t2-recovery-maintenance",
        )
    if config.assignment_reconciliation_worker is not None:
        assignment_reconciliation_task = asyncio.create_task(
            config.readiness.run_when_ready(
                config.stop,
                lambda: config.assignment_reconciliation_worker.run(config.stop),
            ),
            name="human-assignment-reconciliation",
        )
    if config.effect_reconciliation_worker is not None:
        effect_reconciliation_task = asyncio.create_task(
            config.readiness.run_when_ready(
                config.stop,
                lambda: hooks.run_effect_reconciliation(
                    worker=config.effect_reconciliation_worker,
                    stop=config.stop,
                ),
            ),
            name="effect-reconciliation",
        )
    effect_reconciliation_request_binding = config.effect_reconciliation_request_binding
    if effect_reconciliation_request_binding is not None:
        effect_reconciliation_request_task = asyncio.create_task(
            config.readiness.run_when_ready(
                config.stop,
                lambda: hooks.run_effect_reconciliation_request_outbox(
                    publisher=effect_reconciliation_request_binding.outbox_publisher,
                    stop=config.stop,
                ),
            ),
            name="effect-reconciliation-request-outbox",
        )
    if config.rule_generation_binding is not None:
        rule_generation_outbox_task = asyncio.create_task(
            hooks.run_rule_generation_outbox_publisher(
                publisher=config.rule_generation_binding.outbox_publisher,
                stop=config.stop,
            ),
            name="rule-generation-outbox",
        )
        rule_generation_outbox_task.add_done_callback(
            partial(hooks.log_rule_generation_outbox_exit, stop=config.stop)
        )
    if (
        config.pantheon_runtime is not None
        and {"Mimir", "Heimdall"}.issubset(config.pantheon_runtime.agents)
        and config.rule_generation_reconciliation is not None
        and config.rule_generation_reconciliation.request is not None
    ):
        reconciliation_request = config.rule_generation_reconciliation.request
        rule_generation_reconciliation_task = asyncio.create_task(
            config.readiness.run_when_ready(
                config.stop,
                lambda: hooks.publish_rule_generation_reconciliation(
                    runtime=config.pantheon_runtime,
                    request=reconciliation_request,
                    stop=config.stop,
                ),
            ),
            name="rule-generation-reconciliation",
        )
    case_history_retention_publisher = config.case_history_retention_publisher
    if case_history_retention_publisher is not None:
        case_history_retention_task = asyncio.create_task(
            config.readiness.run_when_ready(
                config.stop,
                lambda: case_history_retention_publisher.run(stop=config.stop),
            ),
            name="case-history-retention-ticks",
        )
    if config.discovery_activation is not None:
        discovery_activation_task = asyncio.create_task(
            config.discovery_activation.refresh_until_stopped(config.stop),
            name="discovery-activation-refresh",
        )

    await hooks.supervise_runtime_tasks(
        required=(
            consumer_task,
            readiness_refresh_task,
            wait_task,
            resource_change_task,
            canary_task,
            hil_decision_task,
            hil_reminder_task,
            hil_escalation_task,
            case_history_retention_task,
            semantic_turn_task,
            read_investigation_task,
            operational_readiness_task,
            effect_reconciliation_request_task,
            discovery_activation_task,
        ),
        background=(
            pantheon_task,
            agent_introspection_task,
            runtime_state_task,
            t2_recovery_task,
            assignment_reconciliation_task,
            effect_reconciliation_task,
            rule_generation_outbox_task,
            rule_generation_reconciliation_task,
        ),
    )


__all__ = [
    "RuntimeTaskConfiguration",
    "RuntimeTaskHooks",
    "run_runtime_tasks",
    "schedule_semantic_turn_consumer",
]
