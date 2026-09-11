"""Safeguard-bound execution-port composition for the runtime control loop.

The control loop never invokes a provider without the shared safeguard
lifecycle, so this module owns the one place the in-process Thor port, its
direct-API client, and the workflow action dispatcher are composed. A
production wiring that cannot prove the shared lifecycle, or that has no
workflow action dispatcher, fails closed at composition time instead of at
the first real dispatch.

Composition binds collaborators only. It grants no execution, approval, or
effect-verification authority.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

import httpx

from fdai.core.executor import (
    DirectApiExecutionPort,
    InProcessThorExecutionPort,
    ShadowExecutor,
    ThorExecutionPort,
)
from fdai.core.executor.renderer import TemplateRenderer
from fdai.core.executor.tool_call import ToolReceiptObserver
from fdai.core.workflow.workflow_runtime import WorkflowActionDispatcher
from fdai.runtime.delivery import _build_direct_api_executor, _build_tool_executor
from fdai.runtime.isolated_executor_client import EventBusDirectApiExecutionClient
from fdai.runtime.safeguard_isolated_executor import (
    SafeguardBoundEventBusDirectApiExecutionClient,
)
from fdai.runtime.workflow_action_dispatch import EventBusWorkflowActionDispatcher
from fdai.shared.contracts.models import OntologyActionType
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.workload_identity import WorkloadIdentity

_PRODUCTION_RUNTIME_ENVS = frozenset({"staging", "prod", "production"})


def production_runtime() -> bool:
    """Whether ``RUNTIME_ENV`` names a production-grade deployment."""

    return os.environ.get("RUNTIME_ENV", "").strip().lower() in _PRODUCTION_RUNTIME_ENVS


def require_production_safeguard_readiness(port: ThorExecutionPort | None) -> None:
    """Refuse a production wiring whose Thor port lacks the shared lifecycle.

    An injected port that cannot prove shared safeguard-lifecycle readiness
    would dispatch outside the evidence lifecycle, so composition fails closed
    rather than trusting the injection.
    """

    if production_runtime() and port is not None and port.safeguard_lifecycle_ready is not True:
        raise RuntimeError("production Thor port lacks shared safeguard lifecycle readiness")


def build_thor_execution_port(
    port: ThorExecutionPort | None,
    *,
    container: Any,
    audit_store: Any,
    publisher: Any,
    renderer: TemplateRenderer | None,
    resource_lock: Any,
    idempotency_store: Any,
    safeguard_coordinator: Any,
    direct_api_execution_port: DirectApiExecutionPort | None,
    tool_receipt_observer: ToolReceiptObserver | None,
    http_client: httpx.AsyncClient | None,
    identity: WorkloadIdentity | None,
    human_access_enabled: bool,
    execution_identities: Any,
    promotion_registry: Any,
    action_types_by_name: dict[str, OntologyActionType],
    ontology_release: Any,
    property_semantics: Any,
    catalog_root: Path,
) -> ThorExecutionPort:
    """Return the Thor port, composing the in-process one when none is injected.

    Every in-process executor is bound to the same safeguard lifecycle
    coordinator, and an event-bus direct-API client is wrapped so an isolated
    executor cannot bypass that lifecycle either.
    """

    if port is not None:
        return port
    graph_model_promotion_registry = None
    if os.environ.get("FDAI_STATE_STORE_DSN", "").strip():
        from fdai.delivery.persistence.state_store_graph_model_promotion import (
            StateStoreGraphModelPromotionRegistry,
        )

        graph_model_promotion_registry = StateStoreGraphModelPromotionRegistry(
            store=audit_store,
            ontology_release_digest=ontology_release.digest.removeprefix("sha256:"),
            property_semantics_digest=property_semantics.content_digest.removeprefix("sha256:"),
            decision_evidence_provider=container.decision_evidence_admission_provider,
        )
    executor = ShadowExecutor(
        publisher=publisher,
        audit_store=audit_store,
        renderer=cast(TemplateRenderer, renderer),
        resource_lock=resource_lock,
        idempotency=idempotency_store,
        safeguard_coordinator=safeguard_coordinator,
    )
    if isinstance(direct_api_execution_port, EventBusDirectApiExecutionClient):
        direct_api_executor: DirectApiExecutionPort | None = (
            SafeguardBoundEventBusDirectApiExecutionClient(
                client=direct_api_execution_port,
                coordinator=safeguard_coordinator,
            )
        )
    else:
        direct_api_executor = direct_api_execution_port or _build_direct_api_executor(
            audit_store=audit_store,
            resource_lock=resource_lock,
            idempotency=idempotency_store,
            http_client=http_client,
            identity=identity,
            human_access_enabled=human_access_enabled,
            promotion_registry=promotion_registry,
            graph_model_promotion_registry=graph_model_promotion_registry,
            action_types_by_name=action_types_by_name,
            execution_identities=execution_identities,
            safeguard_coordinator=safeguard_coordinator,
        )
    tool_executor = _build_tool_executor(
        audit_store=audit_store,
        resource_lock=resource_lock,
        idempotency=idempotency_store,
        receipt_observer=tool_receipt_observer,
        http_client=http_client,
        metric_provider=container.metric_provider,
        chaos_catalog_root=catalog_root / "chaos-scenarios",
        safeguard_coordinator=safeguard_coordinator,
    )
    return InProcessThorExecutionPort(
        pr_native=executor,
        direct_api=direct_api_executor,
        tool_call=tool_executor,
        safeguard_lifecycle_ready=True,
    )


def build_workflow_action_dispatcher(
    *,
    event_bus: EventBus | None,
    topic: str,
    workflows_present: bool,
) -> WorkflowActionDispatcher | None:
    """Return the event-bus workflow action dispatcher, or refuse in production.

    A production deployment that loaded workflows but has no dispatcher would
    strand every action step, so composition fails closed instead.
    """

    dispatcher = (
        EventBusWorkflowActionDispatcher(event_bus=event_bus, topic=topic)
        if event_bus is not None
        else None
    )
    if workflows_present and production_runtime() and dispatcher is None:
        raise RuntimeError("production Workflow action dispatcher is unavailable")
    return dispatcher


__all__ = [
    "build_thor_execution_port",
    "build_workflow_action_dispatcher",
    "production_runtime",
    "require_production_safeguard_readiness",
]
