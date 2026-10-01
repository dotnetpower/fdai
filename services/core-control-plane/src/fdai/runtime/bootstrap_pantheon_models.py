"""Typed inputs and retained resources for Pantheon startup initialization."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from fdai.agents import (
    ContextIndexWorkerBindings,
    PantheonRuntime,
    Saga,
    SemanticRouterConfig,
    ShadowDivergenceLedger,
)
from fdai.composition import Container
from fdai.core.control_loop import ControlLoop
from fdai.core.executor import MutationDependencyReadiness
from fdai.core.ontology_platform import EffectReconciliationRequestSink
from fdai.delivery.agent_activity import AgentRuntimeStatePublisher
from fdai.delivery.post_turn_review_ingress import PostTurnReviewRequestConsumer
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.runtime.aks_commerce import VerifiedIncidentResolver
from fdai.runtime.bootstrap_bindings import RuleGenerationRuntimeBinding
from fdai.runtime.case_history import CaseHistoryRetentionTickPublisher
from fdai.runtime.discovery_activation import DiscoveryActivationRuntime
from fdai.runtime.readiness import RuntimeReadinessState
from fdai.runtime.rule_generation_documents import RuleGenerationReconciliation
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity


@dataclass(frozen=True, slots=True)
class PantheonInitialization:
    """Inputs required to bind the optional Pantheon overlay."""

    container: Container
    http_client: httpx.AsyncClient | None
    identity: WorkloadIdentity | None
    bus: EventBus
    incident_audit_store: StateStore
    startup_readiness: RuntimeReadinessState
    runtime_saga: Saga
    runtime_values: dict[str, object]
    runtime_settings: RuntimeSettingsService
    discovery_activation: DiscoveryActivationRuntime
    control_loop: ControlLoop
    rule_generation_reconciliation: RuleGenerationReconciliation | None
    rule_generation_binding: RuleGenerationRuntimeBinding
    open_incident_candidate: Callable[[dict[str, Any]], Awaitable[bool]]
    resolve_verified_incident: VerifiedIncidentResolver
    read_investigation_hook: Any
    runtime_symptom_index: Any
    stage_topic: str
    environment: Mapping[str, str]
    build_runtime_workload_identity: Callable[..., WorkloadIdentity]
    build_operator_memory_store: Callable[[], Any]
    build_inventory_delta_projector: Callable[[], Any]
    runtime_positive_integer: Callable[[dict[str, object], str], int]
    build_mutation_dependency_readiness: Callable[..., MutationDependencyReadiness]
    semantic_router_config_from_env: Callable[[], SemanticRouterConfig]
    assignment_workflow: Any = None
    effect_request_sink: EffectReconciliationRequestSink | None = None
    context_index_workers: ContextIndexWorkerBindings | None = None


@dataclass(frozen=True, slots=True)
class PantheonInitializationResult:
    """Pantheon resources retained by task supervision and ordered cleanup."""

    runtime: PantheonRuntime | None = None
    agent_introspection_server: Any = None
    runtime_state_publisher: AgentRuntimeStatePublisher | None = None
    heartbeat: float | None = None
    divergence_ledger: ShadowDivergenceLedger | None = None
    case_history_retention_publisher: CaseHistoryRetentionTickPublisher | None = None
    t2_recovery_maintenance: Any = None
    discovery_activation: DiscoveryActivationRuntime | None = None
    alert_noise_handler: Any = None
    post_turn_review_request_consumer: PostTurnReviewRequestConsumer | None = None


__all__ = ["PantheonInitialization", "PantheonInitializationResult"]
