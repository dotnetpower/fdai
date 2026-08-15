"""Production composition for principal-scoped semantic ontology queries."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fdai_service_contracts.ontology_query import QueryNodeKind, content_digest

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
from fdai.core.ontology_platform.incident_queries import (
    INCIDENT_EVIDENCE_FUNCTION_NAME,
    IncidentEvidenceReader,
    incident_evidence_function,
)
from fdai.core.ontology_platform.manifest_queries import (
    ONTOLOGY_MANIFEST_FUNCTION_NAME,
    ontology_manifest_function,
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
from fdai.core.ontology_platform.query_execution import QueryNodeHandler
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.core.ontology_platform.query_receipt_authority import SecuredQueryReceiptAuthority
from fdai.core.ontology_platform.relationship_queries import (
    ONTOLOGY_RELATIONSHIPS_FUNCTION_NAME,
    ontology_relationships_function,
)
from fdai.core.prompts.registry import FileSystemPromptRegistry
from fdai.delivery.azure.llm.semantic_planning import (
    AzureOpenAISemanticPlanningModel,
    AzureOpenAISemanticPlanningModelConfig,
)
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog, load_ontology_catalog
from fdai.shared.config.models import LlmMode
from fdai.shared.contracts.models import CeilingRole, OntologyRelease
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.catalog_search import CatalogSemanticIndex
from fdai.shared.providers.ontology_instance import OntologyInstanceStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

from ._helpers import Container, _load_resolved_models
from .semantic_query_model_targets import t1_model_targets, t2_model_targets

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
    ontology_release: OntologyRelease,
    ontology_catalog: OntologyCatalog,
    ontology_store: OntologyInstanceStore,
    catalog_index: CatalogSemanticIndex | None = None,
    catalog_digest: str | None = None,
    topology_reader: TopologyHistoryReader | None = None,
    metric_registry: MetricSemanticRegistry | None = None,
    metric_window_provider: MetricWindowProvider | None = None,
    incident_evidence_reader: IncidentEvidenceReader | None = None,
    purpose: str = "operations-review",
    now: Callable[[], datetime] | None = None,
) -> SemanticConversationRuntime:
    """Build a read-only runtime over one exact catalog release and instance store."""

    if not purpose:
        raise ValueError("semantic query purpose MUST be non-empty")
    if (catalog_index is None) != (catalog_digest is None):
        raise ValueError("catalog semantic index and digest MUST be supplied together")
    if (metric_registry is None) != (metric_window_provider is None):
        raise ValueError("metric semantic registry and window provider MUST be supplied together")
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
        )

    function_registry.register_contextual(
        manifest_declaration,
        ontology_manifest_function(
            ontology_release,
            manifest_for_context=manifest_for_context,
        ),
    )
    bound_function_names.add(manifest_declaration.name)
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
                QueryNodeKind.EVIDENCE_JOIN: EvidenceJoinNodeHandler(),
            }
        )
        extension_schemas.update(METRIC_ARGUMENT_SCHEMAS)
    available_kinds = (QueryNodeKind.OBJECT_SET, QueryNodeKind.FUNCTION, *handlers)
    planner = SemanticPlanningService(
        model=model,
        escalation_model=escalation_model,
        manifests=CatalogQueryManifestProvider(
            release=ontology_release,
            object_types=ontology_catalog.object_types,
            link_types=ontology_catalog.link_types,
            interfaces=ontology_catalog.interface_types,
            action_types=ontology_catalog.action_types,
            functions=function_types,
            bound_function_names=tuple(sorted(bound_function_names)),
        ),
        verifier=OntologyQueryPlanVerifier(
            available_kinds=available_kinds,
            extension_argument_schemas=extension_schemas,
        ),
        descriptor_selector=CompleteManifestSelector(),
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
            ontology_release=ontology_release,
            ontology_catalog=catalog,
            ontology_store=ontology_store,
            catalog_index=catalog_index,
            catalog_digest=catalog_digest,
            topology_reader=topology_reader,
            metric_registry=metric_registry,
            metric_window_provider=metric_window_provider,
            incident_evidence_reader=incident_evidence_reader,
            purpose=purpose,
        )
    except (OSError, LookupError, TypeError, ValueError):
        return _unavailable("semantic_composition_invalid")
    return SemanticQueryRuntimeComposition(runtime=runtime, unavailable_reason=None)


def _unavailable(reason: str) -> SemanticQueryRuntimeComposition:
    return SemanticQueryRuntimeComposition(runtime=None, unavailable_reason=reason)


__all__ = [
    "SemanticQueryRuntimeComposition",
    "build_semantic_query_runtime",
    "compose_azure_semantic_query_runtime",
]
