"""Bind historical and direct metric sources to authenticated query scope."""

from collections.abc import Callable, Mapping
from datetime import datetime

from fdai_service_contracts.ontology_query import QueryNodeKind

from fdai.core.ontology_platform.functions import (
    ContextualOntologyFunction,
    FunctionInvocationContext,
)
from fdai.core.ontology_platform.graph_query_refresh import SecuredGraphEvidenceQueryRefresher
from fdai.core.ontology_platform.metric_semantics import (
    MetricSemanticRegistry,
    MetricWindowProvider,
)
from fdai.core.ontology_platform.models import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
)
from fdai.core.ontology_platform.query_execution import QueryNodeHandler
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.core.ontology_platform.query_metric_handlers import MetricSeriesNodeHandler
from fdai.core.ontology_platform.query_receipt_authority import (
    SecuredQueryReceiptAuthority,
    secured_query_scope_digest,
)
from fdai.core.ontology_platform.query_topology_handlers import TopologyAtNodeHandler
from fdai.core.ontology_platform.topology_history import TopologyHistoryReader
from fdai.shared.contracts.models import OntologyObjectType
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider


def secured_resource_selector(
    gateway: SecuredObjectSetQueryGateway,
    refresher: SecuredGraphEvidenceQueryRefresher,
    authority: SecuredQueryReceiptAuthority,
    admission_provider: DecisionEvidenceAdmissionProvider | None,
) -> ContextualOntologyFunction:
    """Bind the FunctionType wrapper to the common secured ObjectSet boundary."""

    async def select(arguments: Mapping[str, object], context: FunctionInvocationContext) -> object:
        definition = ObjectSetDefinition.model_validate(arguments["object_set"])
        request = ProjectionRequest(
            caller_role=context.caller_role,
            declared_purposes=frozenset(context.purposes),
            principal_scope_digest=context.principal_scope_digest,
        )
        result = await gateway.materialize(definition, projection_request=request)
        result = await refresher.refresh(
            definition=definition, projection_request=request, secured=result
        )
        admission = None
        if admission_provider is not None:
            receipt = result.receipt
            admission = await admission_provider.admit(
                evidence_digest=receipt.projected_result_digest,
                scope_digest=secured_query_scope_digest(receipt),
                purpose_id=receipt.purpose,
                source_revision=receipt.ontology_release.digest,
            )
        authority.issue(result, admission)
        return result

    return select


def scoped_source_handlers(
    *,
    gateway: SecuredObjectSetQueryGateway,
    projection_request: ProjectionRequest,
    purpose: str,
    release_digest: str,
    object_types: Mapping[str, OntologyObjectType],
    now: Callable[[], datetime],
    topology_reader: TopologyHistoryReader | None,
    metric_registry: MetricSemanticRegistry | None,
    metric_provider: MetricWindowProvider | None,
) -> dict[QueryNodeKind, QueryNodeHandler]:
    """Authorize provider reads through the same secured graph as ordinary queries."""
    handlers: dict[QueryNodeKind, QueryNodeHandler] = {}
    if topology_reader is not None:
        handlers[QueryNodeKind.TOPOLOGY_AT] = TopologyAtNodeHandler(
            topology_reader,
            expected_release_digest=release_digest,
            object_types=object_types,
            projection_request=projection_request,
            now=now,
        )

    async def authorize_resource(resource_id: str) -> None:
        result = await gateway.materialize(
            ObjectSetDefinition(
                selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
                object_ids=(resource_id,),
                as_of=now(),
                purpose=purpose,
                limit=1,
                include_relationships=False,
            ),
            projection_request=projection_request,
        )
        if not result.receipt.complete or tuple(
            record.id for record in result.materialization.graph.objects
        ) != (resource_id,):
            raise PermissionError("metric target is absent from the authorized Resource scope")

    if metric_registry is not None and metric_provider is not None:
        handlers[QueryNodeKind.METRIC_SERIES] = MetricSeriesNodeHandler(
            registry=metric_registry,
            provider=metric_provider,
            authorize_resource=authorize_resource,
        )
    return handlers
