"""Composition-owned current-evidence bindings for semantic readiness."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime

from fdai_service_contracts.ontology_query import EvidenceAuthority
from fdai_service_contracts.semantic_turn import SemanticDocumentContext

from fdai.core.conversation.adaptive_service import AdaptiveConversationService
from fdai.core.conversation.semantic_current_evidence import (
    SemanticCurrentEvidenceObservation,
    SemanticCurrentEvidenceProbe,
)
from fdai.core.conversation.semantic_manifest import semantic_principal_scope_digest
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_runtime import SemanticConversationRuntime
from fdai.core.conversation.session import Principal
from fdai.core.ontology_platform import (
    FunctionInvocationContext,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    OntologyFunctionRegistry,
    OntologyQueryPlanExecutor,
)
from fdai.core.ontology_platform.graph_query_refresh import (
    SecuredGraphEvidenceQueryRefresher,
)
from fdai.core.ontology_platform.query_gateway import (
    SecuredObjectSetQueryGateway,
    SecuredObjectSetQueryResult,
)
from fdai.core.ontology_platform.resource_health_queries import (
    RESOURCE_HEALTH_FUNCTION_NAME,
    ResourceHealthCollectionReader,
    resource_health_inventory_function,
)
from fdai.core.ontology_platform.resource_state_queries import (
    RESOURCE_STATE_FUNCTION_NAME,
    RESOURCE_STATE_QUERY_CONCEPTS,
    resource_state_inventory_function,
)
from fdai.core.ontology_platform.service_health_queries import (
    SERVICE_HEALTH_EVENT_TYPES,
    SERVICE_HEALTH_FUNCTION_NAME,
    ServiceHealthReader,
    service_health_function,
)
from fdai.rule_catalog.schema.inventory_query_language import (
    InventoryQueryLanguageRegistry,
)
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyFunctionType,
    OntologyRelease,
)
from fdai.shared.ontology.acl import ProjectionRequest

from .semantic_query_health_values import resource_health_state_values

_CURRENT_EVIDENCE_FUNCTIONS = frozenset(
    {
        RESOURCE_HEALTH_FUNCTION_NAME,
        RESOURCE_STATE_FUNCTION_NAME,
        SERVICE_HEALTH_FUNCTION_NAME,
    }
)


class SemanticQueryConversationRuntime(SemanticConversationRuntime):
    """Semantic runtime carrying its composition-owned current-evidence probe."""

    def __init__(
        self,
        *,
        planner: SemanticPlanningService,
        contextual_executor_factory: Callable[
            [Principal, SemanticDocumentContext | None], OntologyQueryPlanExecutor
        ],
        purpose: str,
        function_bindings: Mapping[str, EvidenceAuthority],
        current_evidence_probe: SemanticCurrentEvidenceProbe | None,
        adaptive_service: AdaptiveConversationService | None,
    ) -> None:
        super().__init__(
            planner=planner,
            contextual_executor_factory=contextual_executor_factory,
            purpose=purpose,
            function_bindings=function_bindings,
            adaptive_service=adaptive_service,
        )
        self._current_evidence_probe = current_evidence_probe

    @property
    def current_evidence_probe(self) -> SemanticCurrentEvidenceProbe | None:
        """Return the principal-scoped readiness probe bound with this runtime."""

        return self._current_evidence_probe


def bind_semantic_current_evidence(
    *,
    registry: OntologyFunctionRegistry,
    declarations: Mapping[str, OntologyFunctionType],
    ontology_release: OntologyRelease,
    gateway: SecuredObjectSetQueryGateway,
    graph_refresher: SecuredGraphEvidenceQueryRefresher,
    resource_health_reader: ResourceHealthCollectionReader | None,
    service_health_reader: ServiceHealthReader | None,
    inventory_query_language: InventoryQueryLanguageRegistry | None,
    purpose: str,
    now: Callable[[], datetime],
    resource_freshness_seconds: int | None,
) -> SemanticCurrentEvidenceProbe | None:
    """Register current reads and return their exact-registry readiness probe."""

    state_declaration = declarations[RESOURCE_STATE_FUNCTION_NAME]
    registry.register_contextual(
        state_declaration,
        resource_state_inventory_function(ontology_release),
        authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
    )
    health_concepts: tuple[str, ...] = ()
    if resource_health_reader is not None and inventory_query_language is not None:
        health_values = resource_health_state_values(inventory_query_language)
        health_concepts = tuple(sorted(health_values))
        registry.register_contextual(
            declarations[RESOURCE_HEALTH_FUNCTION_NAME],
            resource_health_inventory_function(
                ontology_release,
                reader=resource_health_reader,
                health_state_values=health_values,
            ),
            authority=EvidenceAuthority.SERVER_RESOURCE_HEALTH,
        )
    if service_health_reader is not None:
        registry.register_contextual(
            declarations[SERVICE_HEALTH_FUNCTION_NAME],
            service_health_function(ontology_release, reader=service_health_reader),
            authority=EvidenceAuthority.SERVER_SUBSCRIPTION_HEALTH,
        )
    if purpose != "operations-review":
        return None
    return _SemanticCurrentEvidenceProbe(
        gateway=gateway,
        graph_refresher=graph_refresher,
        registry=registry,
        purpose=purpose,
        now=now,
        resource_freshness_seconds=resource_freshness_seconds,
        resource_health_concepts=health_concepts,
    )


class _SemanticCurrentEvidenceProbe:
    """Run current read functions through the exact composed registry and scope."""

    def __init__(
        self,
        *,
        gateway: SecuredObjectSetQueryGateway,
        graph_refresher: SecuredGraphEvidenceQueryRefresher,
        registry: OntologyFunctionRegistry,
        purpose: str,
        now: Callable[[], datetime],
        resource_freshness_seconds: int | None,
        resource_health_concepts: tuple[str, ...],
    ) -> None:
        self._gateway = gateway
        self._graph_refresher = graph_refresher
        self._registry = registry
        self._purpose = purpose
        self._now = now
        self._resource_freshness_seconds = resource_freshness_seconds
        self._resource_health_concepts = resource_health_concepts

    async def observe(
        self,
        *,
        function_name: str,
        principal: Principal,
    ) -> SemanticCurrentEvidenceObservation:
        if function_name not in _CURRENT_EVIDENCE_FUNCTIONS:
            raise ValueError("semantic current-evidence function is unsupported")
        if function_name not in self._registry.binding_authorities:
            raise RuntimeError("semantic current-evidence function is not bound")
        role = CeilingRole(principal.role)
        principal_scope_digest = semantic_principal_scope_digest(
            principal=principal,
            purpose=self._purpose,
        )
        context = FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=role,
            purposes=(self._purpose,),
            principal_ref=principal.id,
            principal_groups=tuple(sorted(principal.groups)),
            principal_scope_digest=principal_scope_digest,
        )
        arguments = await self._arguments(
            function_name,
            role=role,
            principal_scope_digest=principal_scope_digest,
        )
        result, receipt = await self._registry.invoke_with_receipt(
            function_name,
            arguments,
            context=context,
        )
        if not isinstance(result, Mapping):
            raise TypeError("semantic current-evidence result MUST be an object")
        complete = result.get("complete")
        if type(complete) is not bool:
            raise TypeError("semantic current-evidence result lacks completeness")
        return SemanticCurrentEvidenceObservation(
            function_name=function_name,
            complete=complete,
            authority=receipt.authority,
            principal_scope_digest=receipt.principal_scope_digest or "",
        )

    async def _arguments(
        self,
        function_name: str,
        *,
        role: CeilingRole,
        principal_scope_digest: str,
    ) -> Mapping[str, object]:
        if function_name == SERVICE_HEALTH_FUNCTION_NAME:
            return {"event_types": sorted(SERVICE_HEALTH_EVENT_TYPES)}
        secured = await self._secured_resource_scope(
            role=role,
            principal_scope_digest=principal_scope_digest,
        )
        if secured.receipt.principal_scope_digest != principal_scope_digest:
            raise PermissionError("semantic current-evidence Resource scope does not match")
        if (
            function_name == RESOURCE_HEALTH_FUNCTION_NAME
            and not secured.materialization.graph.objects
        ):
            raise RuntimeError("Resource Health readiness scope is empty")
        if function_name == RESOURCE_STATE_FUNCTION_NAME:
            return {
                "query_result": secured.model_dump(mode="json"),
                "state_concepts": list(RESOURCE_STATE_QUERY_CONCEPTS),
            }
        return {
            "query_result": secured.model_dump(mode="json"),
            "health_concepts": list(self._resource_health_concepts),
            "state_concepts": [],
        }

    async def _secured_resource_scope(
        self,
        *,
        role: CeilingRole,
        principal_scope_digest: str,
    ) -> SecuredObjectSetQueryResult:
        request = ProjectionRequest(
            caller_role=role,
            declared_purposes=frozenset({self._purpose}),
            principal_scope_digest=principal_scope_digest,
        )
        definition = ObjectSetDefinition(
            selector=ObjectSelector(
                kind=ObjectSelectorKind.OBJECT_TYPE,
                name="Resource",
            ),
            as_of=self._now(),
            purpose=self._purpose,
            limit=1000,
            freshness_seconds=self._resource_freshness_seconds,
            include_relationships=False,
        )
        secured = await self._gateway.materialize(
            definition,
            projection_request=request,
        )
        return await self._graph_refresher.refresh(
            definition=definition,
            projection_request=request,
            secured=secured,
        )


__all__ = [
    "SemanticQueryConversationRuntime",
    "bind_semantic_current_evidence",
]
