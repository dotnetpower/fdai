"""Incident, Pantheon, and Python-task wiring for the local read API."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai.agents import AgentHandlerObserver, PantheonRuntime
from fdai.core.incident import (
    IncidentAutoOpenPolicy,
    IncidentLifecycleWorkflow,
    IncidentRegistry,
    incident_severity,
    open_detected_incident_candidate,
)
from fdai.core.scheduler.store import InMemoryScheduleStore
from fdai.delivery.read_api.dev.incident_store import ProjectingIncidentStateStore
from fdai.delivery.read_api.dev.operator_runtime import build_local_operator_runtime
from fdai.delivery.read_api.routes.console_action import ConsoleActionSubmitter
from fdai.delivery.read_api.routes.python_tasks import (
    PythonTaskRoutesConfig,
    PythonTaskRunSubmitter,
)
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


def _incident_runtime_policy(
    runtime_values: Mapping[str, object] | None,
) -> tuple[IncidentAutoOpenPolicy, int, int]:
    values = runtime_values or {}
    enabled = values.get("incident.auto_open.enabled", True)
    minimum_severity = values.get("incident.auto_open.min_severity", "HIGH")
    rate_threshold = values.get("incident.repeat_threshold", 5)
    rate_window = values.get("incident.repeat_window_seconds", 300)
    if not isinstance(enabled, bool):
        raise ValueError("incident.auto_open.enabled MUST be a boolean")
    if not isinstance(minimum_severity, str) or minimum_severity not in {
        "CRITICAL",
        "HIGH",
        "MEDIUM",
        "LOW",
        "INFO",
    }:
        raise ValueError("incident.auto_open.min_severity MUST be a supported severity")
    if not isinstance(rate_threshold, int) or isinstance(rate_threshold, bool):
        raise ValueError("incident.repeat_threshold MUST be an integer")
    if not 2 <= rate_threshold <= 100:
        raise ValueError("incident.repeat_threshold MUST be between 2 and 100")
    if not isinstance(rate_window, int) or isinstance(rate_window, bool):
        raise ValueError("incident.repeat_window_seconds MUST be an integer")
    if not 10 <= rate_window <= 86_400:
        raise ValueError("incident.repeat_window_seconds MUST be between 10 and 86400")
    return (
        IncidentAutoOpenPolicy(
            enabled=enabled,
            minimum_severity=incident_severity(minimum_severity),
        ),
        rate_threshold,
        rate_window,
    )


def build_interactive_pantheon_wiring(
    *,
    event_bus: EventBus,
    event_topic: str,
    read_model: Any,
    action_types: tuple[Any, ...],
    handler_observer: AgentHandlerObserver | None = None,
    runtime_values: Mapping[str, object] | None = None,
) -> LocalRuntimeWiring:
    """Wire all agents to the selected local transport without fixture executors."""
    incident_workflow = IncidentLifecycleWorkflow(
        registry=IncidentRegistry(state_store=ProjectingIncidentStateStore(read_model=read_model)),
        allowed_agent_principals={"Huginn", "Heimdall", "Forseti"},
    )
    incident_auto_open_policy, rate_threshold, rate_window = _incident_runtime_policy(
        runtime_values
    )

    async def open_incident_candidate(candidate: dict[str, Any]) -> None:
        await open_detected_incident_candidate(
            workflow=incident_workflow,
            candidate=candidate,
            policy=incident_auto_open_policy,
        )

    pantheon_runtime = PantheonRuntime.build(
        provider=event_bus,
        raw_event_topic=event_topic,
        consumer_group_prefix="fdai-local-pantheon",
        incident_candidate_hook=open_incident_candidate,
        heimdall_rate_threshold=rate_threshold,
        heimdall_rate_window=rate_window,
        action_types=action_types,
        handler_observer=handler_observer,
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
    runtime_values: Mapping[str, object] | None = None,
) -> LocalRuntimeWiring:
    """Compose local event processing and governed Python-task routes."""
    event_bus = LiveInMemoryEventBus()
    incident_workflow = IncidentLifecycleWorkflow(
        registry=IncidentRegistry(state_store=ProjectingIncidentStateStore(read_model=read_model)),
        allowed_agent_principals={"Huginn", "Heimdall", "Forseti"},
    )
    incident_auto_open_policy, rate_threshold, rate_window = _incident_runtime_policy(
        runtime_values
    )

    async def open_incident_candidate(candidate: dict[str, Any]) -> None:
        await open_detected_incident_candidate(
            workflow=incident_workflow,
            candidate=candidate,
            policy=incident_auto_open_policy,
        )

    local_action_types = frozenset(action_type.name for action_type in action_types)
    pantheon_runtime = PantheonRuntime.build(
        provider=event_bus,
        raw_event_topic=action_topic,
        operator_rbac={local_operator_oid: local_action_types},
        incident_candidate_hook=open_incident_candidate,
        heimdall_rate_threshold=rate_threshold,
        heimdall_rate_window=rate_window,
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
