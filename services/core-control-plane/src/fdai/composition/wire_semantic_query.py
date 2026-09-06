"""Production composition for principal-scoped semantic ontology queries."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fdai_service_contracts.ontology_query import (
    EvidenceAuthority,
    QueryNodeKind,
    content_digest,
)

from fdai.core.conversation.adaptive_service import AdaptiveConversationService
from fdai.core.conversation.semantic_judgment import SemanticJudgmentBoundary
from fdai.core.conversation.semantic_manifest import (
    CatalogQueryManifestProvider,
    semantic_principal_scope_digest,
)
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_models import (
    CompleteManifestSelector,
    SemanticPlanningModel,
)
from fdai.core.conversation.semantic_runtime import SemanticConversationRuntime
from fdai.core.conversation.session import Principal
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
    SecuredOntologyInstancePathNodeHandler,
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
from fdai.core.ontology_platform.contextual_resource_queries import (
    CONTEXTUAL_RESOURCE_FUNCTION_NAME,
    contextual_resource_function,
)
from fdai.core.ontology_platform.declaration_queries import (
    ONTOLOGY_DECLARATION_FUNCTION_NAME,
    ontology_declaration_function,
)
from fdai.core.ontology_platform.gateway_diagnostics import (
    GATEWAY_DIAGNOSTIC_FUNCTION_NAME,
    gateway_diagnostic_function,
)
from fdai.core.ontology_platform.governed_document_queries import (
    GOVERNED_DOCUMENT_FUNCTION_NAME,
    GovernedDocumentReader,
    governed_document_function,
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
from fdai.core.ontology_platform.kubernetes_pod_diagnosis_queries import (
    KUBERNETES_POD_DIAGNOSIS_FUNCTION_NAME,
    KubernetesPodLogEvidenceReader,
    kubernetes_pod_diagnosis_function,
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
from fdai.core.ontology_platform.query_receipt_authority import (
    SecuredQueryReceiptAuthority,
    secured_query_scope_digest,
)
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
from fdai.core.ontology_platform.resource_configuration_queries import (
    RESOURCE_CONFIGURATION_FUNCTION_NAME,
    resource_configuration_changes_function,
)
from fdai.core.ontology_platform.resource_configuration_snapshots import (
    RESOURCE_CONFIGURATION_SNAPSHOT_FUNCTION_NAME,
    resource_configuration_snapshot_function,
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
    resource_state_inventory_function,
)
from fdai.core.ontology_platform.service_health_queries import (
    SERVICE_HEALTH_FUNCTION_NAME,
    ServiceHealthReader,
    service_health_function,
)
from fdai.core.ontology_platform.state_transitions import (
    RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME,
    StateTransitionStore,
    resource_state_transitions_function,
)
from fdai.core.ontology_platform.subscription_scope_queries import (
    SUBSCRIPTION_SCOPE_FUNCTION_NAME,
    SubscriptionScopeReader,
    subscription_scope_function,
)
from fdai.core.ontology_platform.vm_process_evidence import (
    VM_PROCESS_CPU_FUNCTION_NAME,
    VmProcessCpuReader,
    vm_process_cpu_function,
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
)
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog
from fdai.shared.contracts.models import CeilingRole, OntologyRelease
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.catalog_search import CatalogSemanticIndex
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.ontology_instance import OntologyInstanceStore
from fdai.shared.providers.read_investigation import ReadInvestigationProvider

from .semantic_query_azure_composition import compose_azure_semantic_query_runtime
from .semantic_query_health_values import (
    resource_health_state_values as _resource_health_state_values,
)

_FRAME_CAPABILITY = "semantic.query.frame"
_PLAN_CAPABILITY = "semantic.query.plan"


@dataclass(frozen=True, slots=True)
class SemanticQueryRuntimeComposition:
    """Optional runtime plus one stable reason when composition is unavailable."""

    runtime: SemanticConversationRuntime | None
    unavailable_reason: str | None
    model_auth_audiences: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (self.runtime is None) != (self.unavailable_reason is not None):
            raise ValueError("semantic runtime composition availability is inconsistent")
        if self.runtime is not None and not self.model_auth_audiences:
            raise ValueError("available semantic runtime requires model auth audiences")
        if self.runtime is None and self.model_auth_audiences:
            raise ValueError("unavailable semantic runtime cannot expose model auth audiences")


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
    subscription_scope_reader: SubscriptionScopeReader | None = None,
    service_health_reader: ServiceHealthReader | None = None,
    state_transition_reader: StateTransitionStore | None = None,
    vm_process_cpu_reader: VmProcessCpuReader | None = None,
    pod_log_evidence_reader: KubernetesPodLogEvidenceReader | None = None,
    property_values: Sequence[PropertyValueDomain] = (),
    inventory_query_language: InventoryQueryLanguageRegistry | None = None,
    purpose: str = "operations-review",
    now: Callable[[], datetime] | None = None,
    graph_live_refresh_provider: BoundedGraphLiveRefreshProvider | None = None,
    resource_freshness_seconds: int | None = None,
    decision_evidence_admission_provider: DecisionEvidenceAdmissionProvider | None = None,
    adaptive_service: AdaptiveConversationService | None = None,
    governed_document_reader: GovernedDocumentReader | None = None,
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
    receipt_authority = SecuredQueryReceiptAuthority(now=evaluation_cutoff)
    graph_refresher = SecuredGraphEvidenceQueryRefresher(
        gateway=gateway,
        live_provider=graph_live_refresh_provider,
    )
    function_registry = OntologyFunctionRegistry(release=ontology_release)
    declarations = {item.name: item for item in function_types}

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
        admission = None
        if decision_evidence_admission_provider is not None:
            receipt = result.receipt
            admission = await decision_evidence_admission_provider.admit(
                evidence_digest=receipt.projected_result_digest,
                scope_digest=secured_query_scope_digest(receipt),
                purpose_id=receipt.purpose,
                source_revision=receipt.ontology_release.digest,
            )
        receipt_authority.issue(result, admission)
        return result

    inventory_function = declarations.get("inventory.select_resources")
    if inventory_function is not None:
        function_registry.register_contextual(
            inventory_function,
            select_resources,
            authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
        )
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
    if governed_document_reader is not None:
        governed_document_declaration = declarations[GOVERNED_DOCUMENT_FUNCTION_NAME]
        function_registry.register_contextual(
            governed_document_declaration,
            governed_document_function(
                ontology_release,
                reader=governed_document_reader,
            ),
            authority=EvidenceAuthority.SERVER_GOVERNED_DOCUMENT,
        )
    contextual_declaration = declarations[CONTEXTUAL_RESOURCE_FUNCTION_NAME]
    function_registry.register_contextual(
        contextual_declaration,
        contextual_resource_function(ontology_release),
        authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
    )
    if incident_evidence_reader is not None:
        incident_declaration = declarations[INCIDENT_EVIDENCE_FUNCTION_NAME]
        function_registry.register_contextual(
            incident_declaration,
            incident_evidence_function(
                ontology_release,
                reader=incident_evidence_reader,
            ),
        )
    current_state_declaration = declarations[RESOURCE_CURRENT_STATE_FUNCTION_NAME]
    function_registry.register_contextual(
        current_state_declaration,
        semantic_resource_current_state_function(ontology_release),
        authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
    )
    ingress_declaration = declarations[RESOURCE_INGRESS_FUNCTION_NAME]
    function_registry.register_contextual(
        ingress_declaration,
        semantic_resource_ingress_function(ontology_release),
        authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
    )
    resource_state_declaration = declarations[RESOURCE_STATE_FUNCTION_NAME]
    function_registry.register_contextual(
        resource_state_declaration,
        resource_state_inventory_function(ontology_release),
        authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
    )
    if resource_event_reader is not None:
        resource_event_declaration = declarations[RESOURCE_EVENT_FUNCTION_NAME]
        function_registry.register_contextual(
            resource_event_declaration,
            resource_event_history_function(
                ontology_release,
                reader=resource_event_reader,
            ),
        )
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
            authority=EvidenceAuthority.SERVER_RESOURCE_HEALTH,
        )
    if service_health_reader is not None:
        service_health_declaration = declarations[SERVICE_HEALTH_FUNCTION_NAME]
        function_registry.register_contextual(
            service_health_declaration,
            service_health_function(ontology_release, reader=service_health_reader),
            authority=EvidenceAuthority.SERVER_SUBSCRIPTION_HEALTH,
        )
    if subscription_scope_reader is not None:
        subscription_scope_declaration = declarations[SUBSCRIPTION_SCOPE_FUNCTION_NAME]
        function_registry.register_contextual(
            subscription_scope_declaration,
            subscription_scope_function(
                ontology_release,
                reader=subscription_scope_reader,
            ),
            authority=EvidenceAuthority.SERVER_SUBSCRIPTION_SCOPE,
        )
    if state_transition_reader is not None:
        state_transition_declaration = declarations[RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME]
        function_registry.register_contextual(
            state_transition_declaration,
            resource_state_transitions_function(
                ontology_release,
                reader=state_transition_reader,
            ),
            authority=EvidenceAuthority.SERVER_OPERATIONAL_STATE_HISTORY,
        )
    if topology_reader is not None:
        function_registry.register_contextual(
            declarations[RESOURCE_CONFIGURATION_SNAPSHOT_FUNCTION_NAME],
            resource_configuration_snapshot_function(
                ontology_release,
                reader=topology_reader,
            ),
            authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
        )
        function_registry.register_contextual(
            declarations[RESOURCE_CONFIGURATION_FUNCTION_NAME],
            resource_configuration_changes_function(ontology_release),
        )
    if metric_registry is not None and metric_window_provider is not None:
        function_registry.register_contextual(
            declarations[GATEWAY_DIAGNOSTIC_FUNCTION_NAME],
            gateway_diagnostic_function(
                ontology_release,
                registry=metric_registry,
                provider=metric_window_provider,
            ),
            authority=EvidenceAuthority.SERVER_OPERATIONAL_METRICS,
        )
        resource_metric_declaration = declarations[RESOURCE_METRIC_FUNCTION_NAME]
        function_registry.register_contextual(
            resource_metric_declaration,
            resource_metric_inventory_function(
                ontology_release,
                registry=metric_registry,
                provider=metric_window_provider,
                now=evaluation_cutoff,
            ),
            authority=EvidenceAuthority.SERVER_OPERATIONAL_METRICS,
        )
        resource_metric_series_declaration = declarations[RESOURCE_METRIC_SERIES_FUNCTION_NAME]
        function_registry.register_contextual(
            resource_metric_series_declaration,
            resource_metric_series_function(
                ontology_release,
                registry=metric_registry,
                provider=metric_window_provider,
                now=evaluation_cutoff,
            ),
            authority=EvidenceAuthority.SERVER_OPERATIONAL_METRICS,
        )
    correlation_declaration = declarations[ERROR_ACTIVITY_CORRELATION_FUNCTION_NAME]
    function_registry.register_contextual(
        correlation_declaration,
        error_activity_correlation_function(ontology_release),
    )
    latency_recovery_declaration = declarations[LATENCY_RECOVERY_FUNCTION_NAME]
    function_registry.register_contextual(
        latency_recovery_declaration,
        latency_recovery_function(ontology_release),
    )
    mysql_pressure_declaration = declarations[MYSQL_PRESSURE_FUNCTION_NAME]
    function_registry.register_contextual(
        mysql_pressure_declaration,
        mysql_pressure_function(ontology_release),
    )
    mysql_demand_declaration = declarations[MYSQL_DEMAND_BUNDLE_FUNCTION_NAME]
    function_registry.register_contextual(
        mysql_demand_declaration,
        mysql_demand_bundle_function(ontology_release),
    )
    mysql_saturation_declaration = declarations[MYSQL_SATURATION_BUNDLE_FUNCTION_NAME]
    function_registry.register_contextual(
        mysql_saturation_declaration,
        mysql_saturation_bundle_function(ontology_release),
    )
    health_declaration = declarations[TARGET_HEALTH_ASSESSMENT_FUNCTION_NAME]
    function_registry.register_contextual(
        health_declaration,
        target_health_assessment_function(ontology_release),
    )
    if read_investigation_provider is not None:
        activity_declaration = declarations[RESOURCE_ACTIVITY_FUNCTION_NAME]
        function_registry.register_contextual(
            activity_declaration,
            semantic_resource_activity_function(
                ontology_release,
                provider=read_investigation_provider,
            ),
        )
    if vm_process_cpu_reader is not None:
        process_declaration = declarations[VM_PROCESS_CPU_FUNCTION_NAME]
        function_registry.register_contextual(
            process_declaration,
            vm_process_cpu_function(
                ontology_release,
                reader=vm_process_cpu_reader,
            ),
        )
    relationship_declaration = declarations[ONTOLOGY_RELATIONSHIPS_FUNCTION_NAME]
    function_registry.register_contextual(
        relationship_declaration,
        ontology_relationships_function(
            ontology_release,
            object_types=ontology_catalog.object_types,
            link_types=ontology_catalog.link_types,
        ),
        authority=EvidenceAuthority.SERVER_ONTOLOGY_MANIFEST,
    )
    network_declaration = declarations[NETWORK_PATH_FUNCTION_NAME]
    function_registry.register_contextual(
        network_declaration,
        network_path_function(
            ontology_release,
            receipt_verifier=receipt_authority,
            verification_context=receipt_authority.verification_context,
        ),
    )
    pod_declaration = declarations[POD_TELEMETRY_FUNCTION_NAME]
    function_registry.register_contextual(
        pod_declaration,
        pod_telemetry_function(
            ontology_release,
            receipt_verifier=receipt_authority,
            verification_context=receipt_authority.verification_context,
        ),
    )
    pod_recovery_declaration = declarations[KUBERNETES_POD_RECOVERY_FUNCTION_NAME]
    function_registry.register_contextual(
        pod_recovery_declaration,
        kubernetes_pod_recovery_function(
            ontology_release,
            receipt_verifier=receipt_authority,
            verification_context=receipt_authority.verification_context,
        ),
    )
    if pod_log_evidence_reader is not None:
        pod_diagnosis_declaration = declarations[KUBERNETES_POD_DIAGNOSIS_FUNCTION_NAME]
        function_registry.register_contextual(
            pod_diagnosis_declaration,
            kubernetes_pod_diagnosis_function(
                ontology_release,
                log_reader=pod_log_evidence_reader,
            ),
        )
    rollout_declaration = declarations[KUBERNETES_ROLLOUT_FUNCTION_NAME]
    function_registry.register_contextual(
        rollout_declaration,
        kubernetes_rollout_function(
            ontology_release,
            receipt_verifier=receipt_authority,
            verification_context=receipt_authority.verification_context,
        ),
    )
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
            bound_function_names=tuple(function_registry.binding_authorities),
            property_values=property_values,
        )

    function_registry.register_contextual(
        manifest_declaration,
        ontology_manifest_function(
            ontology_release,
            manifest_for_context=manifest_for_context,
        ),
        authority=EvidenceAuthority.SERVER_ONTOLOGY_MANIFEST,
    )
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
        authority=EvidenceAuthority.SERVER_ONTOLOGY_MANIFEST,
    )
    if ontology_catalog.resource_classes is not None:
        resource_class_declaration = declarations[RESOURCE_CLASS_CLOSURE_FUNCTION_NAME]
        function_registry.register_contextual(
            resource_class_declaration,
            resource_class_closure_function(
                ontology_release,
                registry=ontology_catalog.resource_classes,
            ),
        )
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
        QueryNodeKind.ONTOLOGY_INSTANCE_PATH,
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
            bound_function_names=tuple(function_registry.binding_authorities),
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
            role = CeilingRole(principal.role)
        except ValueError as exc:
            raise PermissionError("break-glass principals cannot execute semantic queries") from exc
        return OntologyQueryPlanExecutor(
            handlers={
                QueryNodeKind.OBJECT_SET: SecuredObjectSetNodeHandler(
                    gateway,
                    caller_role=role,
                    purposes=(purpose,),
                    receipt_authority=receipt_authority,
                    decision_evidence=decision_evidence_admission_provider,
                    graph_refresher=graph_refresher,
                ),
                QueryNodeKind.ONTOLOGY_INSTANCE_PATH: SecuredOntologyInstancePathNodeHandler(
                    gateway,
                    caller_role=role,
                    purposes=(purpose,),
                    principal_scope_digest=semantic_principal_scope_digest(
                        principal=principal,
                        purpose=purpose,
                    ),
                ),
                QueryNodeKind.RELATIONSHIP_TRAVERSAL: SecuredRelationshipTraversalNodeHandler(
                    gateway,
                    caller_role=role,
                    purposes=(purpose,),
                    receipt_authority=receipt_authority,
                    decision_evidence=decision_evidence_admission_provider,
                ),
                QueryNodeKind.TYPED_PATH: SecuredTypedPathNodeHandler(
                    gateway,
                    caller_role=role,
                    purposes=(purpose,),
                    receipt_authority=receipt_authority,
                    decision_evidence=decision_evidence_admission_provider,
                ),
                QueryNodeKind.FUNCTION: FunctionNodeHandler(
                    function_registry,
                    context=FunctionInvocationContext(
                        caller_agent="Bragi",
                        caller_role=role,
                        purposes=(purpose,),
                        principal_ref=principal.id,
                        principal_groups=tuple(sorted(principal.groups)),
                        principal_scope_digest=semantic_principal_scope_digest(
                            principal=principal,
                            purpose=purpose,
                        ),
                    ),
                    receipt_authority=receipt_authority,
                    allow_presentation_read_dependencies=True,
                ),
                **handlers,
            }
        )

    return SemanticConversationRuntime(
        planner=planner,
        executor_factory=executor_for,
        purpose=purpose,
        function_bindings=function_registry.binding_authorities,
        adaptive_service=adaptive_service,
    )


__all__ = [
    "SemanticQueryRuntimeComposition",
    "build_semantic_query_runtime",
    "compose_azure_semantic_query_runtime",
]
