"""Production composition for principal-scoped semantic ontology queries."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import yaml
from fdai_service_contracts.ontology_query import QueryNodeKind, content_digest

from fdai.core.conversation.semantic_judgment import SemanticJudgmentBoundary
from fdai.core.conversation.semantic_manifest import CatalogQueryManifestProvider
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_models import (
    CompleteManifestSelector,
    SemanticPlanningModel,
)
from fdai.core.conversation.semantic_runtime import SemanticConversationRuntime
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import (
    METRIC_ARGUMENT_SCHEMAS,
    TOPOLOGY_ARGUMENT_SCHEMAS,
    AggregateNodeHandler,
    EvidenceJoinNodeHandler,
    FunctionInvocationContext,
    FunctionNodeHandler,
    MetricComparisonNodeHandler,
    MetricScopeSeriesNodeHandler,
    MetricSemanticRegistry,
    MetricSeriesNodeHandler,
    MetricWindowProvider,
    ObjectSetDefinition,
    ObjectSetService,
    OntologyFunctionRegistry,
    OntologyQueryPlanExecutor,
    OntologyQueryPlanVerifier,
    OrderNodeHandler,
    ProjectNodeHandler,
    QueryManifest,
    SecuredObjectSetNodeHandler,
    SecuredRelationshipTraversalNodeHandler,
    SecuredTypedPathNodeHandler,
    SetOperationNodeHandler,
    TopologyAtNodeHandler,
    TopologyDiffNodeHandler,
    TopologyHistoryReader,
    build_query_manifest,
    compile_interfaces,
)
from fdai.core.ontology_platform.catalog_queries import (
    CATALOG_SEARCH_RULES_FUNCTION_NAME,
    catalog_search_rules_function,
)
from fdai.core.ontology_platform.declaration_queries import (
    ONTOLOGY_DECLARATION_FUNCTION_NAME,
    ontology_declaration_function,
)
from fdai.core.ontology_platform.graph_query_refresh import (
    BoundedGraphLiveRefreshProvider,
    SecuredGraphEvidenceQueryRefresher,
)
from fdai.core.ontology_platform.incident_queries import (
    INCIDENT_EVIDENCE_FUNCTION_NAME,
    IncidentEvidenceReader,
    incident_evidence_function,
)
from fdai.core.ontology_platform.kubernetes_pod_recovery_queries import (
    KUBERNETES_POD_RECOVERY_FUNCTION_NAME,
    KUBERNETES_POD_RESTART_SYMPTOM_CONCEPT,
    kubernetes_pod_recovery_function,
)
from fdai.core.ontology_platform.kubernetes_rollout_queries import (
    KUBERNETES_ROLLOUT_FUNCTION_NAME,
    KUBERNETES_ROLLOUT_SYMPTOM_CONCEPT,
    kubernetes_rollout_function,
)
from fdai.core.ontology_platform.latency_recovery_evidence import (
    LATENCY_RECOVERY_FUNCTION_NAME,
    latency_recovery_function,
)
from fdai.core.ontology_platform.manifest_queries import (
    ONTOLOGY_MANIFEST_FUNCTION_NAME,
    ontology_manifest_function,
)
from fdai.core.ontology_platform.mysql_pressure_evidence import (
    MYSQL_DEMAND_BUNDLE_FUNCTION_NAME,
    MYSQL_PRESSURE_FUNCTION_NAME,
    MYSQL_SATURATION_BUNDLE_FUNCTION_NAME,
    mysql_demand_bundle_function,
    mysql_pressure_function,
    mysql_saturation_bundle_function,
)
from fdai.core.ontology_platform.network_path import (
    NETWORK_PATH_FUNCTION_NAME,
    network_path_function,
)
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.core.ontology_platform.pod_telemetry import (
    POD_TELEMETRY_FUNCTION_NAME,
    pod_telemetry_function,
)
from fdai.core.ontology_platform.property_values import PropertyValueDomain
from fdai.core.ontology_platform.query_execution import QueryNodeHandler
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.core.ontology_platform.query_receipt_authority import SecuredQueryReceiptAuthority
from fdai.core.ontology_platform.relationship_queries import (
    ONTOLOGY_RELATIONSHIPS_FUNCTION_NAME,
    ontology_relationships_function,
)
from fdai.core.ontology_platform.resource_activity_queries import (
    RESOURCE_ACTIVITY_FUNCTION_NAME,
)
from fdai.core.ontology_platform.resource_class_closure import (
    RESOURCE_CLASS_CLOSURE_FUNCTION_NAME,
    resource_class_closure_function,
)
from fdai.core.ontology_platform.resource_current_state_queries import (
    RESOURCE_CURRENT_STATE_FUNCTION_NAME,
)
from fdai.core.ontology_platform.resource_error_activity_correlation_queries import (
    ERROR_ACTIVITY_CORRELATION_FUNCTION_NAME,
    error_activity_correlation_function,
)
from fdai.core.ontology_platform.resource_event_queries import (
    RESOURCE_EVENT_FUNCTION_NAME,
    ResourceEventCollectionReader,
    resource_event_history_function,
)
from fdai.core.ontology_platform.resource_health_assessment_queries import (
    TARGET_HEALTH_ASSESSMENT_FUNCTION_NAME,
    target_health_assessment_function,
)
from fdai.core.ontology_platform.resource_health_queries import (
    RESOURCE_HEALTH_FUNCTION_NAME,
    ResourceHealthCollectionReader,
    resource_health_inventory_function,
)
from fdai.core.ontology_platform.resource_ingress_queries import (
    RESOURCE_INGRESS_FUNCTION_NAME,
)
from fdai.core.ontology_platform.resource_metric_queries import (
    RESOURCE_METRIC_FUNCTION_NAME,
    RESOURCE_METRIC_SERIES_FUNCTION_NAME,
    resource_metric_inventory_function,
    resource_metric_series_function,
)
from fdai.core.ontology_platform.resource_state_queries import (
    RESOURCE_STATE_FUNCTION_NAME,
    RESOURCE_STATE_MEASURE_CONCEPTS,
    resource_state_inventory_function,
)
from fdai.core.ontology_platform.service_health_queries import (
    SERVICE_HEALTH_FUNCTION_NAME,
    ServiceHealthReader,
    service_health_function,
)
from fdai.core.ontology_platform.vm_process_evidence import (
    VM_PROCESS_CPU_FUNCTION_NAME,
    VmProcessCpuReader,
    vm_process_cpu_function,
)
from fdai.core.prompts.registry import FileSystemPromptRegistry
from fdai.delivery.azure.llm.semantic_planning import (
    AzureOpenAISemanticPlanningModel,
    AzureOpenAISemanticPlanningModelConfig,
)
from fdai.delivery.azure.semantic_resource_current_state import (
    semantic_resource_current_state_function,
)
from fdai.delivery.azure.semantic_resource_ingress import (
    semantic_resource_ingress_function,
)
from fdai.delivery.semantic_resource_activity import semantic_resource_activity_function
from fdai.rule_catalog.schema.inventory_query_language import (
    InventoryQueryLanguageRegistry,
    QueryEvidenceAuthority,
    load_inventory_query_language_from_mapping,
)
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog, load_ontology_catalog
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.shared.config.models import LlmMode
from fdai.shared.contracts.models import CeilingRole, OntologyRelease
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.catalog_search import CatalogSemanticIndex
from fdai.shared.providers.ontology_instance import OntologyInstanceStore
from fdai.shared.providers.read_investigation import ReadInvestigationProvider
from fdai.shared.providers.workload_identity import WorkloadIdentity

from ._helpers import Container
from .resolved_models import _load_resolved_models
from .semantic_query_model_targets import t1_model_targets, t2_model_targets
from .semantic_query_value_domains import resource_type_value_domains

_FRAME_CAPABILITY = "semantic.query.frame"
_PLAN_CAPABILITY = "semantic.query.plan"
_ROLE_MAP = {
    Role.READER: CeilingRole.READER,
    Role.CONTRIBUTOR: CeilingRole.CONTRIBUTOR,
    Role.APPROVER: CeilingRole.APPROVER,
    Role.OWNER: CeilingRole.OWNER,
}


@dataclass(frozen=True, slots=True)
class SemanticQueryRuntimeComposition:
    """Optional runtime plus one stable reason when composition is unavailable."""

    runtime: SemanticConversationRuntime | None
    unavailable_reason: str | None

    def __post_init__(self) -> None:
        if (self.runtime is None) != (self.unavailable_reason is not None):
            raise ValueError("semantic runtime composition availability is inconsistent")


def build_semantic_query_runtime(
    *,
    model: SemanticPlanningModel,
    escalation_model: SemanticPlanningModel | None = None,
    semantic_judgment: SemanticJudgmentBoundary | None = None,
    ontology_release: OntologyRelease,
    ontology_catalog: OntologyCatalog,
    ontology_store: OntologyInstanceStore,
    catalog_index: CatalogSemanticIndex | None = None,
    catalog_digest: str | None = None,
    topology_reader: TopologyHistoryReader | None = None,
    metric_registry: MetricSemanticRegistry | None = None,
    metric_window_provider: MetricWindowProvider | None = None,
    incident_evidence_reader: IncidentEvidenceReader | None = None,
    read_investigation_provider: ReadInvestigationProvider | None = None,
    resource_health_reader: ResourceHealthCollectionReader | None = None,
    resource_event_reader: ResourceEventCollectionReader | None = None,
    service_health_reader: ServiceHealthReader | None = None,
    vm_process_cpu_reader: VmProcessCpuReader | None = None,
    property_values: Sequence[PropertyValueDomain] = (),
    inventory_query_language: InventoryQueryLanguageRegistry | None = None,
    purpose: str = "operations-review",
    now: Callable[[], datetime] | None = None,
    graph_live_refresh_provider: BoundedGraphLiveRefreshProvider | None = None,
    resource_freshness_seconds: int | None = None,
) -> SemanticConversationRuntime:
    """Build a read-only runtime over one exact catalog release and instance store."""

    if not purpose:
        raise ValueError("semantic query purpose MUST be non-empty")
    if (catalog_index is None) != (catalog_digest is None):
        raise ValueError("catalog semantic index and digest MUST be supplied together")
    if (metric_registry is None) != (metric_window_provider is None):
        raise ValueError("metric semantic registry and window provider MUST be supplied together")
    if resource_health_reader is not None and inventory_query_language is None:
        raise ValueError("Resource Health reader requires inventory query language semantics")
    function_types = operational_function_types(ontology_catalog.function_types)
    expected_release = build_ontology_release(
        object_types=ontology_catalog.object_types,
        link_types=ontology_catalog.link_types,
        action_types=ontology_catalog.action_types,
        interface_types=ontology_catalog.interface_types,
        function_types=function_types,
    )
    if expected_release.digest != ontology_release.digest:
        raise ValueError("semantic query catalog does not match the active ontology release")
    interfaces = compile_interfaces(
        interfaces=ontology_catalog.interface_types,
        implementations=ontology_catalog.interface_implementations,
        object_types=ontology_catalog.object_types,
        release=ontology_release,
    )
    evaluation_cutoff = now or (lambda: datetime.now(UTC))
    gateway = SecuredObjectSetQueryGateway(
        service=ObjectSetService(
            store=ontology_store,
            interfaces=interfaces,
            object_type_names=frozenset(item.name for item in ontology_catalog.object_types),
        ),
        object_types={item.name: item for item in ontology_catalog.object_types},
        ontology_release=ontology_release,
        evaluation_cutoff=evaluation_cutoff,
        max_as_of_skew=timedelta(seconds=5),
    )
    receipt_authority = SecuredQueryReceiptAuthority()
    graph_refresher = SecuredGraphEvidenceQueryRefresher(
        gateway=gateway,
        live_provider=graph_live_refresh_provider,
    )
    function_registry = OntologyFunctionRegistry(release=ontology_release)
    declarations = {item.name: item for item in function_types}
    bound_function_names: set[str] = set()

    async def select_resources(
        arguments: Mapping[str, object],
        context: FunctionInvocationContext,
    ) -> object:
        definition = ObjectSetDefinition.model_validate(arguments["object_set"])
        result = await gateway.materialize(
            definition,
            projection_request=ProjectionRequest(
                caller_role=context.caller_role,
                declared_purposes=frozenset(context.purposes),
            ),
        )
        receipt_authority.issue(result)
        return result

    inventory_function = declarations.get("inventory.select_resources")
    if inventory_function is not None:
        function_registry.register_contextual(inventory_function, select_resources)
        bound_function_names.add(inventory_function.name)
    if catalog_index is not None and catalog_digest is not None:
        catalog_declaration = declarations[CATALOG_SEARCH_RULES_FUNCTION_NAME]
        function_registry.register_contextual(
            catalog_declaration,
            catalog_search_rules_function(
                ontology_release,
                index=catalog_index,
                catalog_digest=catalog_digest,
            ),
        )
        bound_function_names.add(catalog_declaration.name)
    if incident_evidence_reader is not None:
        incident_declaration = declarations[INCIDENT_EVIDENCE_FUNCTION_NAME]
        function_registry.register_contextual(
            incident_declaration,
            incident_evidence_function(
                ontology_release,
                reader=incident_evidence_reader,
            ),
        )
        bound_function_names.add(incident_declaration.name)
    current_state_declaration = declarations[RESOURCE_CURRENT_STATE_FUNCTION_NAME]
    function_registry.register_contextual(
        current_state_declaration,
        semantic_resource_current_state_function(ontology_release),
    )
    bound_function_names.add(current_state_declaration.name)
    ingress_declaration = declarations[RESOURCE_INGRESS_FUNCTION_NAME]
    function_registry.register_contextual(
        ingress_declaration,
        semantic_resource_ingress_function(ontology_release),
    )
    bound_function_names.add(ingress_declaration.name)
    resource_state_declaration = declarations[RESOURCE_STATE_FUNCTION_NAME]
    function_registry.register_contextual(
        resource_state_declaration,
        resource_state_inventory_function(ontology_release),
    )
    bound_function_names.add(resource_state_declaration.name)
    if resource_event_reader is not None:
        resource_event_declaration = declarations[RESOURCE_EVENT_FUNCTION_NAME]
        function_registry.register_contextual(
            resource_event_declaration,
            resource_event_history_function(
                ontology_release,
                reader=resource_event_reader,
            ),
        )
        bound_function_names.add(resource_event_declaration.name)
    if resource_health_reader is not None and inventory_query_language is not None:
        resource_health_declaration = declarations[RESOURCE_HEALTH_FUNCTION_NAME]
        function_registry.register_contextual(
            resource_health_declaration,
            resource_health_inventory_function(
                ontology_release,
                reader=resource_health_reader,
                health_state_values=_resource_health_state_values(
                    inventory_query_language,
                ),
            ),
        )
        bound_function_names.add(resource_health_declaration.name)
    if service_health_reader is not None:
        service_health_declaration = declarations[SERVICE_HEALTH_FUNCTION_NAME]
        function_registry.register_contextual(
            service_health_declaration,
            service_health_function(
                ontology_release,
                reader=service_health_reader,
            ),
        )
        bound_function_names.add(service_health_declaration.name)
    if metric_registry is not None and metric_window_provider is not None:
        resource_metric_declaration = declarations[RESOURCE_METRIC_FUNCTION_NAME]
        function_registry.register_contextual(
            resource_metric_declaration,
            resource_metric_inventory_function(
                ontology_release,
                registry=metric_registry,
                provider=metric_window_provider,
                now=evaluation_cutoff,
            ),
        )
        bound_function_names.add(resource_metric_declaration.name)
        resource_metric_series_declaration = declarations[RESOURCE_METRIC_SERIES_FUNCTION_NAME]
        function_registry.register_contextual(
            resource_metric_series_declaration,
            resource_metric_series_function(
                ontology_release,
                registry=metric_registry,
                provider=metric_window_provider,
                now=evaluation_cutoff,
            ),
        )
        bound_function_names.add(resource_metric_series_declaration.name)
    correlation_declaration = declarations[ERROR_ACTIVITY_CORRELATION_FUNCTION_NAME]
    function_registry.register_contextual(
        correlation_declaration,
        error_activity_correlation_function(ontology_release),
    )
    bound_function_names.add(correlation_declaration.name)
    latency_recovery_declaration = declarations[LATENCY_RECOVERY_FUNCTION_NAME]
    function_registry.register_contextual(
        latency_recovery_declaration,
        latency_recovery_function(ontology_release),
    )
    bound_function_names.add(latency_recovery_declaration.name)
    mysql_pressure_declaration = declarations[MYSQL_PRESSURE_FUNCTION_NAME]
    function_registry.register_contextual(
        mysql_pressure_declaration,
        mysql_pressure_function(ontology_release),
    )
    bound_function_names.add(mysql_pressure_declaration.name)
    mysql_demand_declaration = declarations[MYSQL_DEMAND_BUNDLE_FUNCTION_NAME]
    function_registry.register_contextual(
        mysql_demand_declaration,
        mysql_demand_bundle_function(ontology_release),
    )
    bound_function_names.add(mysql_demand_declaration.name)
    mysql_saturation_declaration = declarations[MYSQL_SATURATION_BUNDLE_FUNCTION_NAME]
    function_registry.register_contextual(
        mysql_saturation_declaration,
        mysql_saturation_bundle_function(ontology_release),
    )
    bound_function_names.add(mysql_saturation_declaration.name)
    health_declaration = declarations[TARGET_HEALTH_ASSESSMENT_FUNCTION_NAME]
    function_registry.register_contextual(
        health_declaration,
        target_health_assessment_function(ontology_release),
    )
    bound_function_names.add(health_declaration.name)
    if read_investigation_provider is not None:
        activity_declaration = declarations[RESOURCE_ACTIVITY_FUNCTION_NAME]
        function_registry.register_contextual(
            activity_declaration,
            semantic_resource_activity_function(
                ontology_release,
                provider=read_investigation_provider,
            ),
        )
        bound_function_names.add(activity_declaration.name)
    if vm_process_cpu_reader is not None:
        process_declaration = declarations[VM_PROCESS_CPU_FUNCTION_NAME]
        function_registry.register_contextual(
            process_declaration,
            vm_process_cpu_function(
                ontology_release,
                reader=vm_process_cpu_reader,
            ),
        )
        bound_function_names.add(process_declaration.name)
    relationship_declaration = declarations[ONTOLOGY_RELATIONSHIPS_FUNCTION_NAME]
    function_registry.register_contextual(
        relationship_declaration,
        ontology_relationships_function(
            ontology_release,
            object_types=ontology_catalog.object_types,
            link_types=ontology_catalog.link_types,
        ),
    )
    bound_function_names.add(relationship_declaration.name)
    network_declaration = declarations[NETWORK_PATH_FUNCTION_NAME]
    function_registry.register_contextual(
        network_declaration,
        network_path_function(
            ontology_release,
            receipt_verifier=receipt_authority,
            verification_context=receipt_authority.verification_context,
        ),
    )
    bound_function_names.add(network_declaration.name)
    pod_declaration = declarations[POD_TELEMETRY_FUNCTION_NAME]
    function_registry.register_contextual(
        pod_declaration,
        pod_telemetry_function(
            ontology_release,
            receipt_verifier=receipt_authority,
            verification_context=receipt_authority.verification_context,
        ),
    )
    bound_function_names.add(pod_declaration.name)
    pod_recovery_declaration = declarations[KUBERNETES_POD_RECOVERY_FUNCTION_NAME]
    function_registry.register_contextual(
        pod_recovery_declaration,
        kubernetes_pod_recovery_function(
            ontology_release,
            receipt_verifier=receipt_authority,
            verification_context=receipt_authority.verification_context,
        ),
    )
    bound_function_names.add(pod_recovery_declaration.name)
    rollout_declaration = declarations[KUBERNETES_ROLLOUT_FUNCTION_NAME]
    function_registry.register_contextual(
        rollout_declaration,
        kubernetes_rollout_function(
            ontology_release,
            receipt_verifier=receipt_authority,
            verification_context=receipt_authority.verification_context,
        ),
    )
    bound_function_names.add(rollout_declaration.name)
    manifest_declaration = declarations[ONTOLOGY_MANIFEST_FUNCTION_NAME]

    def manifest_for_context(
        role: CeilingRole,
        purposes: tuple[str, ...],
    ) -> QueryManifest:
        return build_query_manifest(
            release=ontology_release,
            principal_role=role,
            purposes=purposes,
            principal_scope_digest=content_digest({"role": role.value, "purposes": purposes}),
            object_types=ontology_catalog.object_types,
            link_types=ontology_catalog.link_types,
            interfaces=ontology_catalog.interface_types,
            action_types=ontology_catalog.action_types,
            functions=function_types,
            bound_function_names=tuple(
                sorted(bound_function_names | {ONTOLOGY_MANIFEST_FUNCTION_NAME})
            ),
            property_values=property_values,
        )

    function_registry.register_contextual(
        manifest_declaration,
        ontology_manifest_function(
            ontology_release,
            manifest_for_context=manifest_for_context,
        ),
    )
    bound_function_names.add(manifest_declaration.name)
    declaration_query = declarations[ONTOLOGY_DECLARATION_FUNCTION_NAME]
    function_registry.register_contextual(
        declaration_query,
        ontology_declaration_function(
            ontology_release,
            object_types=ontology_catalog.object_types,
            link_types=ontology_catalog.link_types,
            action_types=ontology_catalog.action_types,
            interface_types=ontology_catalog.interface_types,
            interface_implementations=ontology_catalog.interface_implementations,
        ),
    )
    bound_function_names.add(declaration_query.name)
    if ontology_catalog.resource_classes is not None:
        resource_class_declaration = declarations[RESOURCE_CLASS_CLOSURE_FUNCTION_NAME]
        function_registry.register_contextual(
            resource_class_declaration,
            resource_class_closure_function(
                ontology_release,
                registry=ontology_catalog.resource_classes,
            ),
        )
        bound_function_names.add(resource_class_declaration.name)
    handlers: dict[QueryNodeKind, QueryNodeHandler] = {
        QueryNodeKind.UNION: SetOperationNodeHandler("union"),
        QueryNodeKind.INTERSECTION: SetOperationNodeHandler("intersection"),
        QueryNodeKind.SUBTRACTION: SetOperationNodeHandler("subtraction"),
        QueryNodeKind.ORDER: OrderNodeHandler(),
        QueryNodeKind.PROJECT: ProjectNodeHandler(),
        QueryNodeKind.AGGREGATE: AggregateNodeHandler(),
    }
    extension_schemas: dict[QueryNodeKind, Mapping[str, object]] = {}
    if topology_reader is not None:
        handlers.update(
            {
                QueryNodeKind.TOPOLOGY_AT: TopologyAtNodeHandler(topology_reader),
                QueryNodeKind.TOPOLOGY_DIFF: TopologyDiffNodeHandler(),
            }
        )
        extension_schemas.update(TOPOLOGY_ARGUMENT_SCHEMAS)
    if metric_registry is not None and metric_window_provider is not None:
        handlers.update(
            {
                QueryNodeKind.METRIC_SERIES: MetricSeriesNodeHandler(
                    registry=metric_registry,
                    provider=metric_window_provider,
                ),
                QueryNodeKind.METRIC_SCOPE_SERIES: MetricScopeSeriesNodeHandler(
                    registry=metric_registry,
                    provider=metric_window_provider,
                ),
                QueryNodeKind.METRIC_COMPARISON: MetricComparisonNodeHandler(
                    registry=metric_registry,
                ),
                QueryNodeKind.EVIDENCE_JOIN: EvidenceJoinNodeHandler(),
            }
        )
        extension_schemas.update(METRIC_ARGUMENT_SCHEMAS)
    available_kinds = (
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.RELATIONSHIP_TRAVERSAL,
        QueryNodeKind.TYPED_PATH,
        QueryNodeKind.FUNCTION,
        *handlers,
    )
    planner = SemanticPlanningService(
        model=model,
        escalation_model=escalation_model,
        semantic_judgment=semantic_judgment,
        # The planner stamps ObjectSet as_of and the gateway validates it against the same
        # cutoff within a 5s skew, so both MUST read one clock.
        now=evaluation_cutoff,
        manifests=CatalogQueryManifestProvider(
            release=ontology_release,
            object_types=ontology_catalog.object_types,
            link_types=ontology_catalog.link_types,
            interfaces=ontology_catalog.interface_types,
            action_types=ontology_catalog.action_types,
            functions=function_types,
            bound_function_names=tuple(sorted(bound_function_names)),
            property_values=property_values,
        ),
        verifier=OntologyQueryPlanVerifier(
            available_kinds=available_kinds,
            extension_argument_schemas=extension_schemas,
            reviewed_metric_concepts=(
                tuple(sorted(metric_registry.definitions)) if metric_registry is not None else ()
            ),
        ),
        descriptor_selector=CompleteManifestSelector(),
        metric_concepts=tuple(
            sorted(
                {
                    KUBERNETES_POD_RESTART_SYMPTOM_CONCEPT,
                    KUBERNETES_ROLLOUT_SYMPTOM_CONCEPT,
                    *(metric_registry.definitions if metric_registry is not None else ()),
                }
            )
        ),
        inventory_query_language=inventory_query_language,
        resource_freshness_seconds=resource_freshness_seconds,
    )

    def executor_for(principal: Principal) -> OntologyQueryPlanExecutor:
        try:
            role = _ROLE_MAP[principal.role]
        except KeyError as exc:
            raise PermissionError("break-glass principals cannot execute semantic queries") from exc
        return OntologyQueryPlanExecutor(
            handlers={
                QueryNodeKind.OBJECT_SET: SecuredObjectSetNodeHandler(
                    gateway,
                    caller_role=role,
                    purposes=(purpose,),
                    receipt_authority=receipt_authority,
                    graph_refresher=graph_refresher,
                ),
                QueryNodeKind.RELATIONSHIP_TRAVERSAL: SecuredRelationshipTraversalNodeHandler(
                    gateway,
                    caller_role=role,
                    purposes=(purpose,),
                    receipt_authority=receipt_authority,
                ),
                QueryNodeKind.TYPED_PATH: SecuredTypedPathNodeHandler(
                    gateway,
                    caller_role=role,
                    purposes=(purpose,),
                    receipt_authority=receipt_authority,
                ),
                QueryNodeKind.FUNCTION: FunctionNodeHandler(
                    function_registry,
                    context=FunctionInvocationContext(
                        caller_agent="Bragi",
                        caller_role=role,
                        purposes=(purpose,),
                    ),
                    receipt_authority=receipt_authority,
                ),
                **handlers,
            }
        )

    return SemanticConversationRuntime(
        planner=planner,
        executor_factory=executor_for,
        purpose=purpose,
    )


def compose_azure_semantic_query_runtime(
    *,
    container: Container,
    ontology_release: OntologyRelease | None,
    ontology_store: OntologyInstanceStore | None,
    identity: WorkloadIdentity | None,
    http_client: httpx.AsyncClient | None,
    endpoint: str | None,
    endpoint_resolver: Callable[[str], str] | None,
    catalog_root: Path,
    owner_loop: asyncio.AbstractEventLoop,
    purpose: str = "operations-review",
    catalog_index: CatalogSemanticIndex | None = None,
    catalog_digest: str | None = None,
    topology_reader: TopologyHistoryReader | None = None,
    metric_registry: MetricSemanticRegistry | None = None,
    metric_window_provider: MetricWindowProvider | None = None,
    incident_evidence_reader: IncidentEvidenceReader | None = None,
    read_investigation_provider: ReadInvestigationProvider | None = None,
    resource_health_reader: ResourceHealthCollectionReader | None = None,
    resource_event_reader: ResourceEventCollectionReader | None = None,
    service_health_reader: ServiceHealthReader | None = None,
    vm_process_cpu_reader: VmProcessCpuReader | None = None,
    graph_live_refresh_provider: BoundedGraphLiveRefreshProvider | None = None,
    resource_freshness_seconds: int | None = None,
) -> SemanticQueryRuntimeComposition:
    """Compose Azure semantic querying over optional exact Rule retrieval."""

    if container.config.llm.mode != LlmMode.AZURE:
        return _unavailable("semantic_llm_mode_unavailable")
    if container.config.llm.resolved_models_path is None:
        return _unavailable("semantic_resolved_models_unavailable")
    if ontology_release is None:
        return _unavailable("semantic_ontology_release_unavailable")
    if ontology_store is None:
        return _unavailable("semantic_ontology_store_unavailable")
    if identity is None or http_client is None:
        return _unavailable("semantic_model_transport_unavailable")
    try:
        resolved = _load_resolved_models(container.config.llm.resolved_models_path)
        t1_candidates = t1_model_targets(
            resolved,
            endpoint=endpoint,
            endpoint_resolver=endpoint_resolver,
        )
        if not t1_candidates:
            return _unavailable("semantic_t1_model_candidates_unavailable")
        t2_candidates = t2_model_targets(
            resolved,
            endpoint=endpoint,
            endpoint_resolver=endpoint_resolver,
        )
        prompts = FileSystemPromptRegistry(catalog_root)
        frame_system_prompt = prompts.get_base(_FRAME_CAPABILITY).body
        plan_system_prompt = prompts.get_base(_PLAN_CAPABILITY).body
        t1_model = AzureOpenAISemanticPlanningModel(
            identity=identity,
            http_client=http_client,
            config=AzureOpenAISemanticPlanningModelConfig(
                candidates=t1_candidates,
                frame_system_prompt=frame_system_prompt,
                plan_system_prompt=plan_system_prompt,
            ),
            owner_loop=owner_loop,
        )
        t2_model = (
            AzureOpenAISemanticPlanningModel(
                identity=identity,
                http_client=http_client,
                config=AzureOpenAISemanticPlanningModelConfig(
                    candidates=t2_candidates,
                    frame_system_prompt=frame_system_prompt,
                    plan_system_prompt=plan_system_prompt,
                ),
                owner_loop=owner_loop,
            )
            if t2_candidates
            else None
        )
        catalog = load_ontology_catalog(
            catalog_root,
            schema_registry=container.schema_registry,
            probes_root=(catalog_root / "probes" if (catalog_root / "probes").is_dir() else None),
        )
        runtime = build_semantic_query_runtime(
            model=t1_model,
            escalation_model=t2_model,
            semantic_judgment=(
                container.llm_bindings.conversation_semantic_judgment_factory(owner_loop)
                if container.llm_bindings is not None
                and container.llm_bindings.conversation_semantic_judgment_factory is not None
                else None
            ),
            ontology_release=ontology_release,
            ontology_catalog=catalog,
            ontology_store=ontology_store,
            catalog_index=catalog_index,
            catalog_digest=catalog_digest,
            topology_reader=topology_reader,
            metric_registry=metric_registry,
            metric_window_provider=metric_window_provider,
            incident_evidence_reader=incident_evidence_reader,
            read_investigation_provider=read_investigation_provider,
            resource_health_reader=resource_health_reader,
            resource_event_reader=resource_event_reader,
            service_health_reader=service_health_reader,
            vm_process_cpu_reader=vm_process_cpu_reader,
            graph_live_refresh_provider=graph_live_refresh_provider,
            resource_freshness_seconds=resource_freshness_seconds,
            property_values=_resource_type_property_values(catalog_root),
            inventory_query_language=_inventory_query_language(catalog_root),
            purpose=purpose,
        )
    except (OSError, LookupError, TypeError, ValueError):
        return _unavailable("semantic_composition_invalid")
    return SemanticQueryRuntimeComposition(runtime=runtime, unavailable_reason=None)


def _resource_type_property_values(catalog_root: Path) -> tuple[PropertyValueDomain, ...]:
    vocabulary = catalog_root / "vocabulary" / "resource-types.yaml"
    registry = load_resource_type_registry_from_mapping(
        yaml.safe_load(vocabulary.read_text(encoding="utf-8"))
    )
    return resource_type_value_domains(registry)


def _inventory_query_language(catalog_root: Path) -> InventoryQueryLanguageRegistry:
    vocabulary = catalog_root / "vocabulary" / "inventory-query-language.yaml"
    return load_inventory_query_language_from_mapping(
        yaml.safe_load(vocabulary.read_text(encoding="utf-8"))
    )


def _resource_health_state_values(
    registry: InventoryQueryLanguageRegistry,
) -> dict[str, tuple[str, ...]]:
    state_measures = frozenset(RESOURCE_STATE_MEASURE_CONCEPTS)
    groups: dict[str, tuple[str, ...]] = {}
    for state_id, state in registry.states.items():
        normalized = {f"resource_state.{value}" for value in state.values}
        if (
            state.evidence_authority is not QueryEvidenceAuthority.CURRENT_INVENTORY
            or not normalized <= state_measures
        ):
            groups[f"resource_health.{state_id}"] = state.values
    if not groups:
        raise ValueError("inventory query language declares no Resource Health semantics")
    return groups


def _unavailable(reason: str) -> SemanticQueryRuntimeComposition:
    return SemanticQueryRuntimeComposition(runtime=None, unavailable_reason=reason)


__all__ = [
    "SemanticQueryRuntimeComposition",
    "build_semantic_query_runtime",
    "compose_azure_semantic_query_runtime",
]
