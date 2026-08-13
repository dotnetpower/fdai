"""Production composition for principal-scoped semantic ontology queries."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fdai_service_contracts.ontology_query import QueryNodeKind

from fdai.core.conversation.semantic_manifest import CatalogQueryManifestProvider
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_models import (
    CompleteManifestSelector,
    SemanticPlanningModel,
)
from fdai.core.conversation.semantic_runtime import SemanticConversationRuntime
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import (
    AggregateNodeHandler,
    FunctionInvocationContext,
    FunctionNodeHandler,
    ObjectSetDefinition,
    ObjectSetService,
    OntologyFunctionRegistry,
    OntologyQueryPlanExecutor,
    OntologyQueryPlanVerifier,
    OrderNodeHandler,
    ProjectNodeHandler,
    SecuredObjectSetNodeHandler,
    SetOperationNodeHandler,
    compile_interfaces,
)
from fdai.core.ontology_platform.catalog_queries import (
    CATALOG_SEARCH_RULES_FUNCTION_NAME,
    catalog_search_rules_function,
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
from fdai.core.prompts.registry import FileSystemPromptRegistry
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.delivery.azure.llm.semantic_planning import (
    AzureOpenAISemanticPlanningModel,
    AzureOpenAISemanticPlanningModelConfig,
)
from fdai.rule_catalog.schema.llm_resolver import CapabilityStatus, ResolvedModels
from fdai.rule_catalog.schema.model_endpoint import ModelAuthKind
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog, load_ontology_catalog
from fdai.shared.config.models import LlmMode
from fdai.shared.contracts.models import CeilingRole, OntologyRelease
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.catalog_search import CatalogSemanticIndex
from fdai.shared.providers.ontology_instance import OntologyInstanceStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

from ._helpers import Container, _load_resolved_models

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
    ontology_release: OntologyRelease,
    ontology_catalog: OntologyCatalog,
    ontology_store: OntologyInstanceStore,
    catalog_index: CatalogSemanticIndex | None = None,
    catalog_digest: str | None = None,
    purpose: str = "operations-review",
    now: Callable[[], datetime] | None = None,
) -> SemanticConversationRuntime:
    """Build a read-only runtime over one exact catalog release and instance store."""

    if not purpose:
        raise ValueError("semantic query purpose MUST be non-empty")
    if (catalog_index is None) != (catalog_digest is None):
        raise ValueError("catalog semantic index and digest MUST be supplied together")
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
    handlers: dict[QueryNodeKind, QueryNodeHandler] = {
        QueryNodeKind.UNION: SetOperationNodeHandler("union"),
        QueryNodeKind.INTERSECTION: SetOperationNodeHandler("intersection"),
        QueryNodeKind.SUBTRACTION: SetOperationNodeHandler("subtraction"),
        QueryNodeKind.ORDER: OrderNodeHandler(),
        QueryNodeKind.PROJECT: ProjectNodeHandler(),
        QueryNodeKind.AGGREGATE: AggregateNodeHandler(),
    }
    available_kinds = (QueryNodeKind.OBJECT_SET, QueryNodeKind.FUNCTION, *handlers)
    planner = SemanticPlanningService(
        model=model,
        manifests=CatalogQueryManifestProvider(
            release=ontology_release,
            object_types=ontology_catalog.object_types,
            link_types=ontology_catalog.link_types,
            interfaces=ontology_catalog.interface_types,
            action_types=ontology_catalog.action_types,
            functions=function_types,
            bound_function_names=tuple(sorted(bound_function_names)),
        ),
        verifier=OntologyQueryPlanVerifier(available_kinds=available_kinds),
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
        candidates = _model_targets(
            resolved,
            endpoint=endpoint,
            endpoint_resolver=endpoint_resolver,
        )
        if not candidates:
            return _unavailable("semantic_model_candidates_unavailable")
        prompts = FileSystemPromptRegistry(catalog_root)
        model = AzureOpenAISemanticPlanningModel(
            identity=identity,
            http_client=http_client,
            config=AzureOpenAISemanticPlanningModelConfig(
                candidates=candidates,
                frame_system_prompt=prompts.get_base(_FRAME_CAPABILITY).body,
                plan_system_prompt=prompts.get_base(_PLAN_CAPABILITY).body,
            ),
            owner_loop=owner_loop,
        )
        catalog = load_ontology_catalog(
            catalog_root,
            schema_registry=container.schema_registry,
            probes_root=(catalog_root / "probes" if (catalog_root / "probes").is_dir() else None),
        )
        runtime = build_semantic_query_runtime(
            model=model,
            ontology_release=ontology_release,
            ontology_catalog=catalog,
            ontology_store=ontology_store,
            catalog_index=catalog_index,
            catalog_digest=catalog_digest,
            purpose=purpose,
        )
    except (OSError, LookupError, TypeError, ValueError):
        return _unavailable("semantic_composition_invalid")
    return SemanticQueryRuntimeComposition(runtime=runtime, unavailable_reason=None)


def _model_targets(
    resolved: ResolvedModels,
    *,
    endpoint: str | None,
    endpoint_resolver: Callable[[str], str] | None,
) -> tuple[ModelRequestTarget, ...]:
    targets: list[ModelRequestTarget] = [
        ModelRequestTarget(
            endpoint=candidate.endpoint,
            deployment=candidate.deployment,
            api_version=candidate.api_version,
            api_style=candidate.api_style,
            auth_audience=candidate.auth_audience,
        )
        for candidate in resolved.reasoner_primary_candidates
    ]
    if not targets:
        primary = _target_for_capability(
            resolved,
            "t2.reasoner.primary",
            endpoint=endpoint,
            endpoint_resolver=endpoint_resolver,
        )
        if primary is not None:
            targets.append(primary)
    secondary = _target_for_capability(
        resolved,
        "t2.reasoner.secondary",
        endpoint=endpoint,
        endpoint_resolver=endpoint_resolver,
    )
    if secondary is not None:
        targets.append(secondary)
    unique: dict[tuple[str, str, str | None], ModelRequestTarget] = {}
    for target in targets:
        unique.setdefault((target.endpoint, target.deployment, target.api_version), target)
    return tuple(unique.values())


def _target_for_capability(
    resolved: ResolvedModels,
    capability_id: str,
    *,
    endpoint: str | None,
    endpoint_resolver: Callable[[str], str] | None,
) -> ModelRequestTarget | None:
    binding = next(
        (item for item in resolved.endpoint_bindings if item.capability == capability_id),
        None,
    )
    if binding is not None:
        if (
            binding.auth_kind is not ModelAuthKind.ENTRA
            or binding.auth_audience is None
            or endpoint_resolver is None
        ):
            return None
        return ModelRequestTarget(
            endpoint=endpoint_resolver(binding.endpoint_ref),
            deployment=binding.deployment,
            api_style=binding.api_style,
            api_version=binding.api_version or "2024-06-01",
            auth_audience=binding.auth_audience,
            route_kind=binding.route_kind,
            binding_id=binding.binding_id,
        )
    capability = next(
        (
            item
            for item in resolved.capabilities
            if item.name == capability_id
            and item.status in {CapabilityStatus.RESOLVED, CapabilityStatus.CAPACITY_REDUCED}
        ),
        None,
    )
    if capability is None or endpoint is None:
        return None
    return ModelRequestTarget(
        endpoint=endpoint,
        deployment=capability.name,
        api_version="2024-06-01",
    )


def _unavailable(reason: str) -> SemanticQueryRuntimeComposition:
    return SemanticQueryRuntimeComposition(runtime=None, unavailable_reason=reason)


__all__ = [
    "SemanticQueryRuntimeComposition",
    "build_semantic_query_runtime",
    "compose_azure_semantic_query_runtime",
]
