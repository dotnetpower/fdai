"""Immutable Operator API composition values and capability bindings."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from fdai.core.conversation_assurance import ConversationAssuranceLedger
from fdai.core.hil_resume import HilResumeCoordinator
from fdai.core.rbac.resolver import Principal
from fdai.core.skills import RuntimeSkillDisclosure
from fdai.delivery.operator_api.routes.busy_input_runtime import BusyInputRuntime
from fdai.delivery.operator_api.routes.data_sources import ReadDataSourceStatus
from fdai.delivery.operator_api.routes.hil_callback import HilCallbackConfig
from fdai.delivery.operator_api.routes.panels import ReadPanel
from fdai.delivery.operator_api.streaming.agent_activity_stream import AgentActivityStreamConfig
from fdai.delivery.operator_api.streaming.live_stream import LiveStreamConfig
from fdai.delivery.operator_api.streaming.provision_stream import ProvisionStreamConfig
from fdai.shared.providers.conversation_delivery import ConversationDeliveryStore
from fdai.shared.providers.hil_registry import HilApprovalRegistry
from fdai.shared.telemetry import ConversationProgressMetrics


@dataclass(frozen=True, slots=True)
class OperatorApiValues:
    """Carry inert Operator API values shared by local and production assembly.

    These records own no runtime state or authority and depend only on immutable,
    environment-derived values. Provider, store, publisher, credential, and
    lifecycle implementations are excluded.
    """

    dev_mode: bool = False
    local_cli_profile: Mapping[str, object] | None = None
    cors_allow_origins: tuple[str, ...] = ()
    conversation_delivery_source: str = "postgres"
    webhook_path: str = "/webhook"
    chat_probe_interval_seconds: int = 300
    iam_identity_provider: str = "entra"
    iam_role_group_ids: Mapping[str, str] = field(default_factory=dict)
    expose_pantheon: bool = False

    def __post_init__(self) -> None:
        if self.local_cli_profile is not None:
            object.__setattr__(
                self,
                "local_cli_profile",
                MappingProxyType(dict(self.local_cli_profile)),
            )
        object.__setattr__(
            self,
            "iam_role_group_ids",
            MappingProxyType(dict(self.iam_role_group_ids)),
        )


@dataclass(frozen=True, slots=True)
class StreamRouteBindings:
    """Own read-only SSE routes and their process-local producer lifecycles.

    State belongs to the injected sinks and producers; this record grants no
    execution authority. Local and production roots supply the same binding
    shape with venue-specific transport implementations.
    """

    live_stream: LiveStreamConfig | None = None
    provision_stream: ProvisionStreamConfig | None = None
    agent_activity: AgentActivityStreamConfig | None = None


@dataclass(frozen=True, slots=True)
class ProjectionRouteBindings:
    """Own read projection, catalog, workflow, and task route dependencies.

    Injected readers retain their own state and evidence authority; the record
    only binds them to HTTP registration and cannot execute managed-resource
    changes. Both deployment venues use this shape.
    """

    blast_radius_graph: Any = None
    ontology_object_types: tuple[Any, ...] = ()
    ontology_link_types: tuple[Any, ...] = ()
    ontology_action_types: tuple[Any, ...] = ()
    ontology_function_types: tuple[Any, ...] = ()
    operating_model_status_reader: Any = None
    inventory_graph_provider: Any = None
    detection_readiness_reader: Any = None
    best_practice_controls: tuple[Any, ...] = ()
    mcsb_catalogs: tuple[Any, ...] = ()
    rule_catalog_rules: tuple[Any, ...] = ()
    rule_catalog_collected_rules: tuple[Any, ...] = ()
    rule_catalog_policies_root: Any = None
    rule_catalog_remediation_root: Any = None
    rule_catalog_findings_provider: Any = None
    rule_catalog_findings_summary_provider: Any = None
    rule_catalog_semantic_index: Any = None
    promotion_gate_action_types: tuple[Any, ...] = ()
    promotion_gate_source: Any = None
    scope_source: Any = None
    stewardship_map: Any = None
    stewardship_health_reader: Any = None
    workflow_authoring: Any = None
    workflow_execution: Any = None
    python_tasks: Any = None


@dataclass(frozen=True, slots=True)
class LifecycleBindings:
    """Own ASGI startup, readiness-probe, and shutdown dependencies.

    Callback and probe state stays in the injected services. This record owns
    process lifecycle ordering, not route or execution authority, and is used
    identically by local and production app assembly.
    """

    startup_callbacks: tuple[Callable[[], Awaitable[None]], ...] = ()
    shutdown_callbacks: tuple[Callable[[], Awaitable[None]], ...] = ()
    chat_backend: Any = None
    web_search_resolver: Any = None


@dataclass(frozen=True, slots=True)
class ReadViewBindings:
    """Own dynamic read-view, trace, bitemporal, and what-if dependencies.

    Readers and evaluators retain their own state; this process-local record
    grants no mutation authority. Its immutable evaluator map is safe to share
    across local and production route registration.
    """

    reporting: Any = None
    process_views: Any = None
    trace_reader: Any = None
    bitemporal_reader: Any = None
    what_if_reader: Any = None
    what_if_evaluators: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "what_if_evaluators",
            MappingProxyType(dict(self.what_if_evaluators)),
        )


@dataclass(frozen=True, slots=True)
class ConversationRouteBindings:
    """Own chat, principal-context, and conversational evidence dependencies.

    Stateful stores and providers remain injected implementations. This record
    can translate and submit governed requests but cannot approve, execute, or
    receive Thor's identity; both deployment venues bind the same shape.
    """

    chat: Any = None
    skill_disclosure: RuntimeSkillDisclosure | None = None
    knowledge_context: Any = None
    configuration_drift_context: Any = None
    busy_input_runtime: BusyInputRuntime | None = None
    conversation_progress_metrics: ConversationProgressMetrics | None = None
    chat_agent_delegate: Any = None
    chat_web_search: Any = None
    conversation_policy_store: Any = None
    conversation_assurance_runtime: Any = None
    conversation_history_store: Any = None
    conversation_search: Any = None
    llm_usage_reader: Any = None
    inventory_graph_provider: Any = None
    inventory_semantic_resolver: Any = None
    inventory_activity_provider: Any = None
    kubernetes_workload_provider: Any = None
    detection_readiness_reader: Any = None
    t2_recovery_reader: Any = None
    subscription_health_provider: Any = None
    log_query_provider: Any = None
    network_reachability_provider: Any = None
    data_sources: tuple[ReadDataSourceStatus, ...] = ()
    post_turn_review_submitter: Any = None
    chat_document_evidence: Any = None
    user_context_ontology_projector: Any = None
    model_settings: Any = None
    console_action: Any = None
    handover_availability_publisher: Any = None
    extra_panels: tuple[ReadPanel, ...] = ()
    user_context: Any = None


@dataclass(frozen=True, slots=True)
class GovernedRouteBindings:
    """Own bounded command, settings, workflow, and worker dependencies.

    Injected services own durable state and enforce their domain authorization;
    this record only registers non-executing Operator API requests. Local and
    production roots use the same capability shape.
    """

    handover_goals: Any = None
    task_worker_store: Any = None
    background_tasks: Any = None
    read_investigations: Any = None
    trajectory_datasets: Any = None
    skill_sources: Any = None
    model_settings: Any = None
    runtime_settings: Any = None
    workflow_definitions: Any = None


@dataclass(frozen=True, slots=True)
class HttpSurfaceBindings:
    """Own fixed HTTP, middleware, identity, HIL, and ingress dependencies.

    The record carries process-local services but no credentials or executor
    identity. Each service retains its state and domain authority while local
    and production roots share this registration contract. The optional local
    CLI principal is a debug-only human identity snapshot, never an executor,
    and app construction refuses it outside local development.
    """

    local_cli_principal: Principal | None = None
    extra_panels: tuple[ReadPanel, ...] = ()
    data_sources: tuple[ReadDataSourceStatus, ...] = ()
    authoritative_read_proxy: Any = None
    conversation_delivery_store: ConversationDeliveryStore | None = None
    conversation_progress_metrics: ConversationProgressMetrics | None = None
    conversation_assurance_ledger: ConversationAssuranceLedger | None = None
    conversation_history_store: Any = None
    configuration_review_runtime: Any = None
    automation_blueprint_review: Any = None
    kill_switch_command: Any = None
    iam_access: Any = None
    iam_directory: Any = None
    human_assignments: Any = None
    execution_access_grants: Any = None
    stewardship_map: Any = None
    hil_callback: HilCallbackConfig | None = None
    hil_registry: HilApprovalRegistry | None = None
    hil_coordinator: HilResumeCoordinator | None = None
    hil_decision_publisher: Any = None
    webhook_ingress: Any = None
    console_action: Any = None


@dataclass(frozen=True, slots=True)
class OperatorApiRuntimeBindings:
    """Group process-local dependencies by their route or lifecycle owner.

    The nested records reference stateful implementations without owning their
    state or widening authority. The complete shape is deployment-neutral and
    contains neither raw credentials nor executor identity.
    """

    streams: StreamRouteBindings = field(default_factory=StreamRouteBindings)
    projections: ProjectionRouteBindings = field(default_factory=ProjectionRouteBindings)
    lifecycle: LifecycleBindings = field(default_factory=LifecycleBindings)
    read_views: ReadViewBindings = field(default_factory=ReadViewBindings)
    conversation: ConversationRouteBindings = field(default_factory=ConversationRouteBindings)
    governed: GovernedRouteBindings = field(default_factory=GovernedRouteBindings)
    http: HttpSurfaceBindings = field(default_factory=HttpSurfaceBindings)


@dataclass(frozen=True, slots=True)
class OperatorApiComposition:
    """Validate inert values and process-local bindings before registration.

    This deployment-neutral top-level record owns no runtime state or authority.
    Validation requires intentionally shared dependencies to be the same object,
    preventing local and production capability consumers from drifting.
    """

    values: OperatorApiValues = field(default_factory=OperatorApiValues)
    bindings: OperatorApiRuntimeBindings = field(default_factory=OperatorApiRuntimeBindings)

    def validate(self) -> None:
        """Fail before registration when required or shared bindings conflict."""
        if self.bindings.conversation.busy_input_runtime is not None and (
            self.bindings.conversation.chat is None
        ):
            raise ValueError("busy_input_runtime requires a configured chat backend")
        if self.bindings.http.hil_callback is not None and (
            self.bindings.http.hil_registry is None
        ):
            raise ValueError("hil_callback requires hil_registry")
        if (self.bindings.http.local_cli_principal is None) != (
            self.values.local_cli_profile is None
        ):
            raise ValueError("local CLI principal and profile MUST be configured together")

        _require_same_reference(
            "chat backend",
            self.bindings.lifecycle.chat_backend,
            self.bindings.conversation.chat,
        )
        _require_same_reference(
            "web search resolver",
            self.bindings.lifecycle.web_search_resolver,
            self.bindings.conversation.chat_web_search,
        )
        _require_same_reference(
            "inventory graph provider",
            self.bindings.projections.inventory_graph_provider,
            self.bindings.conversation.inventory_graph_provider,
        )
        _require_same_reference(
            "detection readiness reader",
            self.bindings.projections.detection_readiness_reader,
            self.bindings.conversation.detection_readiness_reader,
        )
        _require_same_reference(
            "stewardship map",
            self.bindings.projections.stewardship_map,
            self.bindings.http.stewardship_map,
        )
        _require_same_reference(
            "model settings",
            self.bindings.conversation.model_settings,
            self.bindings.governed.model_settings,
        )
        _require_same_reference(
            "extra panels",
            self.bindings.conversation.extra_panels,
            self.bindings.http.extra_panels,
        )
        _require_same_reference(
            "data sources",
            self.bindings.conversation.data_sources,
            self.bindings.http.data_sources,
        )
        _require_same_reference(
            "conversation progress metrics",
            self.bindings.conversation.conversation_progress_metrics,
            self.bindings.http.conversation_progress_metrics,
        )
        _require_same_reference(
            "conversation history store",
            self.bindings.conversation.conversation_history_store,
            self.bindings.http.conversation_history_store,
        )
        _require_same_reference(
            "console action submitter",
            self.bindings.conversation.console_action,
            self.bindings.http.console_action,
        )


def _require_same_reference(label: str, *values: object) -> None:
    if values and any(value is not values[0] for value in values[1:]):
        raise ValueError(f"shared {label} bindings MUST reference the same object")


__all__ = [
    "ConversationRouteBindings",
    "GovernedRouteBindings",
    "HttpSurfaceBindings",
    "LifecycleBindings",
    "OperatorApiComposition",
    "OperatorApiRuntimeBindings",
    "OperatorApiValues",
    "ProjectionRouteBindings",
    "ReadViewBindings",
    "StreamRouteBindings",
]
