"""Compose assignment-owned semantic and membership callbacks after ordinary startup readiness."""

from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx

from fdai.composition import Container
from fdai.core.control_loop import ControlLoop
from fdai.runtime.assignment_transport import AssignmentTransportRuntime
from fdai.runtime.handover_semantics import bind_handover_semantics
from fdai.runtime.human_access_runtime import build_human_access_workflow
from fdai.runtime.human_access_workflow import HumanAccessWorkflowRuntime
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity


def bind_assignment_capabilities(
    *,
    transport: AssignmentTransportRuntime | None,
    container: Container,
    loop: ControlLoop,
    store: StateStore,
    catalog_root: Path,
    environment: Mapping[str, str],
    http_client: httpx.AsyncClient | None,
    identity: WorkloadIdentity | None,
    runtime_values: Mapping[str, Any],
    readiness: Any,
) -> tuple[AssignmentTransportRuntime | None, HumanAccessWorkflowRuntime | None]:
    """Keep owners bound through existing transport; never promote mode during composition."""
    if transport is None:
        return None, None
    transport = replace(
        transport,
        workflow=bind_handover_semantics(
            workflow=transport.workflow,
            core=transport.core_handover,
            container=container,
            catalog_root=catalog_root,
            ontology_release=loop.ontology_release,
            action_types=loop.action_types,
            environment=environment,
            http_client=http_client,
            identity=identity,
        ),
    )
    human_access = build_human_access_workflow(
        loop=loop,
        store=store,
        environment=environment,
        http_client=http_client,
        identity=identity,
        enforce_ready=lambda: (
            runtime_values["human_access.enabled"] is True
            and environment.get("FDAI_PANTHEON_ENFORCE", "").lower() in {"1", "true"}
            and readiness.authority_ceiling("autonomous-action").value == "deployment"
        ),
    )
    if human_access is not None:
        transport = replace(
            transport,
            workflow=replace(transport.workflow, human_access=human_access.agent_bindings()),
        )
    return transport, human_access


def bind_assignment_reconciliation(
    human_access: HumanAccessWorkflowRuntime | None, pantheon: Any
) -> Any:
    """Schedule only through the actual public Huginn ingress when that runtime exists."""
    if human_access is None or pantheon is None:
        return None
    from fdai.runtime.human_access_reconciliation import HumanAccessReconciliation

    return HumanAccessReconciliation(human_access, pantheon.ingest_raw_event)


def bind_assignment_outcomes(
    *,
    transport: AssignmentTransportRuntime | None,
    store: StateStore,
    environment: Mapping[str, str],
    http_client: httpx.AsyncClient | None,
    publisher: Any,
    merge_worker: Any,
    resource_lock: Callable[[Mapping[str, str]], Any],
) -> tuple[Any, Any]:
    """Bind current scoped ownership observations and the existing sealed result consumer."""
    from fdai_core_service.assignment_outcome_consumer import AssignmentOutcomeConsumer

    from fdai.runtime.scoped_duties import build_scoped_duty_projection

    projection = (
        build_scoped_duty_projection(
            processor=transport.scoped,
            environment=environment,
            http_client=http_client,
            publisher=publisher,
            locks=resource_lock(environment),
        )
        if transport is not None and transport.scoped is not None
        else None
    )
    consumer = (
        AssignmentOutcomeConsumer(
            store=store,
            scoped=projection.ownership if projection is not None else None,
            ownership=merge_worker.ownership if merge_worker is not None else None,
            base=merge_worker.base if merge_worker is not None else None,
        )
        if transport is not None
        else None
    )
    return projection, consumer


def build_assignment_observation_worker(
    *,
    store: StateStore,
    durable: bool,
    values: Mapping[str, Any],
    outcome_consumer: Any,
    scoped_projection: Any,
    positive_integer: Callable[..., int],
) -> Any:
    """Bind the existing bounded observation worker; missing durable storage never falls back."""
    if not durable:
        return None
    from fdai.core.human_assignment import AssignmentReconciler
    from fdai.core.human_assignment.readiness import HandoverReadinessPublisher
    from fdai.runtime.human_assignment_reconciliation import AssignmentReconciliationWorker

    return AssignmentReconciliationWorker(
        reconciler=AssignmentReconciler(store=store),
        readiness=HandoverReadinessPublisher(
            store=store, enabled=values["human_access.enabled"] is True
        ),
        removal_artifact=outcome_consumer.reconcile_revocation
        if outcome_consumer is not None
        else None,
        scoped_observation=scoped_projection.publish if scoped_projection is not None else None,
        interval_seconds=min(
            positive_integer(values, "human_access.reconciliation_interval_seconds"),
            30 if scoped_projection is not None else float("inf"),
        ),
    )


__all__ = [
    "bind_assignment_capabilities",
    "bind_assignment_reconciliation",
    "bind_assignment_outcomes",
    "build_assignment_observation_worker",
]
