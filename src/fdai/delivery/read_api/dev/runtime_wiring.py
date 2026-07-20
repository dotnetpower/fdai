"""Incident, Pantheon, and Python-task wiring for the local read API."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai.agents import PantheonRuntime
from fdai.core.incident import (
    IncidentLifecycleWorkflow,
    IncidentRegistry,
    detected_incident_correlation_keys,
    detected_incident_event_id,
)
from fdai.core.scheduler.store import InMemoryScheduleStore
from fdai.delivery.read_api.dev.incident_store import ProjectingIncidentStateStore
from fdai.delivery.read_api.dev.operator_runtime import build_local_operator_runtime
from fdai.delivery.read_api.routes.console_action import ConsoleActionSubmitter
from fdai.delivery.read_api.routes.python_tasks import (
    PythonTaskRoutesConfig,
    PythonTaskRunSubmitter,
)
from fdai.shared.contracts.models import IncidentSeverity
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.stage_publisher import StagePublisher
from fdai.shared.providers.testing.live_event_bus import LiveInMemoryEventBus
from fdai.shared.providers.testing.python_task_author import TemplatePythonTaskAuthor
from fdai.shared.providers.testing.vm_task import (
    InMemoryPythonTaskArtifactStore,
    InMemoryVmTaskRunner,
    InMemoryVmTaskTargetResolver,
)
from fdai.shared.providers.vm_task import PythonTaskCapability, VmTaskTarget
from fdai.shared.streaming.stage_publisher import SseSinkStagePublisher


@dataclass(frozen=True, slots=True)
class LocalRuntimeWiring:
    pantheon_runtime: PantheonRuntime
    console_action: ConsoleActionSubmitter | None
    python_tasks: PythonTaskRoutesConfig | None
    operator_runtime: Any
    start_pantheon_runtime: Any
    stop_pantheon_runtime: Any


def _runtime_callbacks(
    pantheon_runtime: PantheonRuntime,
) -> tuple[Any, Any]:
    runtime_task: asyncio.Task[None] | None = None

    async def start_pantheon_runtime() -> None:
        nonlocal runtime_task
        runtime_task = asyncio.create_task(
            pantheon_runtime.run(),
            name="local-pantheon-runtime",
        )
        await asyncio.sleep(0)
        if runtime_task.done():
            await runtime_task

    async def stop_pantheon_runtime() -> None:
        await pantheon_runtime.stop()
        if runtime_task is None:
            return
        if not runtime_task.done():
            runtime_task.cancel()
        await asyncio.gather(runtime_task, return_exceptions=True)

    return start_pantheon_runtime, stop_pantheon_runtime


def build_interactive_pantheon_wiring(
    *,
    event_bus: EventBus,
    event_topic: str,
    read_model: Any,
    action_types: tuple[Any, ...],
) -> LocalRuntimeWiring:
    """Wire all agents to the selected local transport without fixture executors."""
    incident_workflow = IncidentLifecycleWorkflow(
        registry=IncidentRegistry(state_store=ProjectingIncidentStateStore(read_model=read_model)),
        allowed_agent_principals={"Huginn", "Heimdall", "Forseti"},
    )

    async def open_incident_candidate(candidate: dict[str, Any]) -> None:
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

    pantheon_runtime = PantheonRuntime.build(
        provider=event_bus,
        raw_event_topic=event_topic,
        consumer_group_prefix="fdai-local-pantheon",
        incident_candidate_hook=open_incident_candidate,
        action_types=action_types,
    )
    start_pantheon_runtime, stop_pantheon_runtime = _runtime_callbacks(pantheon_runtime)
    return LocalRuntimeWiring(
        pantheon_runtime=pantheon_runtime,
        console_action=None,
        python_tasks=None,
        operator_runtime=None,
        start_pantheon_runtime=start_pantheon_runtime,
        stop_pantheon_runtime=stop_pantheon_runtime,
    )


def build_local_runtime_wiring(
    *,
    read_model: Any,
    action_types: tuple[Any, ...],
    workflows: tuple[Any, ...],
    live_stream_config: Any,
    local_operator_oid: str,
    action_topic: str,
    repo_root: Path,
) -> LocalRuntimeWiring:
    """Compose local event processing and governed Python-task routes."""
    event_bus = LiveInMemoryEventBus()
    incident_workflow = IncidentLifecycleWorkflow(
        registry=IncidentRegistry(state_store=ProjectingIncidentStateStore(read_model=read_model)),
        allowed_agent_principals={"Huginn", "Heimdall", "Forseti"},
    )

    async def open_incident_candidate(candidate: dict[str, Any]) -> None:
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

    local_action_types = frozenset(action_type.name for action_type in action_types)
    pantheon_runtime = PantheonRuntime.build(
        provider=event_bus,
        raw_event_topic=action_topic,
        operator_rbac={local_operator_oid: local_action_types},
        incident_candidate_hook=open_incident_candidate,
    )
    console_action = ConsoleActionSubmitter(
        event_bus=event_bus,
        raw_event_topic=action_topic,
        action_type_names=local_action_types,
        incident_workflow=incident_workflow,
    )

    artifacts = InMemoryPythonTaskArtifactStore()
    targets = InMemoryVmTaskTargetResolver(
        (
            VmTaskTarget(
                resource_ref="resource:compute/vm/gpu-worker",
                capabilities=frozenset(
                    {
                        PythonTaskCapability.GPU,
                        PythonTaskCapability.NETWORK,
                        PythonTaskCapability.FILESYSTEM_READ,
                        PythonTaskCapability.FILESYSTEM_WRITE,
                    }
                ),
            ),
        )
    )
    runner = InMemoryVmTaskRunner()
    python_tasks = PythonTaskRoutesConfig(
        artifacts=artifacts,
        targets=targets,
        runner=runner,
        submitter=PythonTaskRunSubmitter(event_bus=event_bus, topic=action_topic),
        schedule_store=InMemoryScheduleStore(),
        workflows=workflows,
        author=TemplatePythonTaskAuthor(),
    )
    live_stage_sink = live_stream_config.sink
    if live_stage_sink is None:  # pragma: no cover - local stream invariant
        raise RuntimeError("local operator runtime requires a live-stream sink")
    stage_publisher: StagePublisher = SseSinkStagePublisher(
        live_stage_sink,
        channel=live_stream_config.channel,
    )
    if live_stream_config.stage_publisher_wrapper is not None:
        stage_publisher = live_stream_config.stage_publisher_wrapper(stage_publisher)
    operator_runtime = build_local_operator_runtime(
        bus=event_bus,
        topic=action_topic,
        repo_root=repo_root,
        action_types=action_types,
        artifacts=artifacts,
        targets=targets,
        runner=runner,
        stage_publisher=stage_publisher,
    )

    start_pantheon_runtime, stop_pantheon_runtime = _runtime_callbacks(pantheon_runtime)

    return LocalRuntimeWiring(
        pantheon_runtime=pantheon_runtime,
        console_action=console_action,
        python_tasks=python_tasks,
        operator_runtime=operator_runtime,
        start_pantheon_runtime=start_pantheon_runtime,
        stop_pantheon_runtime=stop_pantheon_runtime,
    )


__all__ = [
    "LocalRuntimeWiring",
    "build_interactive_pantheon_wiring",
    "build_local_runtime_wiring",
]
