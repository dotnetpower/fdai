"""Route-family assembly for the independent Operator service."""

from __future__ import annotations

import httpx
from fdai_service_contracts import OperatorReadModel

from fdai_operator_service.adapters import (
    OperatorSemanticKafkaBus,
    StartupOwnedLocalAzureNarratorAdapters,
)
from fdai_operator_service.auth import OperatorAuthenticator
from fdai_operator_service.context_selection import ContextSelectionRegistry
from fdai_operator_service.conversation_assurance_reader import (
    ConversationAssuranceReader,
    ConversationAssuranceReaderConfig,
)
from fdai_operator_service.environment import OperatorEnvironment
from fdai_operator_service.families.conversation import ConversationFamilyDependencies
from fdai_operator_service.families.conversation.document_export import ConversationDocumentExporter
from fdai_operator_service.families.conversation.semantic_turn_runtime import (
    SemanticTurnBridge,
    SemanticTurnConversationAdapters,
    T1ModelHealthReader,
)
from fdai_operator_service.families.cost_governance import (
    CostGovernanceFamilyDependencies,
    decode_cost_pseudonym_key,
)
from fdai_operator_service.families.operations import PanelRoute
from fdai_operator_service.families.operations.contracts import ProjectionReader
from fdai_operator_service.family_adapters import (
    AksCommerceFamilyDependencies,
    PostgresConversationAdapters,
    PostgresOperationsAdapters,
    PostgresWorkflowAdapters,
    StateStoreAksCommerceProjectionReader,
    UnavailableAksCommerceProjectionReader,
    UnavailableConversationAdapters,
    UnavailableOperationsAdapters,
    UnavailableWorkflowAdapters,
    build_postgres_document_context_resolver,
)
from fdai_operator_service.family_authorization import OperatorFamilyAuthorizer
from fdai_operator_service.iam_composition import (
    build_postgres_iam_bindings,
    build_unavailable_iam_bindings,
)
from fdai_operator_service.model_lifecycle_composition import OperatorResolvedModelsRevisionOwner
from fdai_operator_service.postgres_cost_governance import (
    PostgresCostGovernanceConfig,
    PostgresCostGovernanceReader,
    UnavailableCostGovernanceReader,
)
from fdai_operator_service.postgres_family_store import PostgresFamilyStore
from fdai_operator_service.postgres_read_investigation_replay import (
    PostgresReadInvestigationReplayConfig,
    PostgresReadInvestigationReplayStore,
)
from fdai_operator_service.reporting import optional_pdf_report_encoder
from fdai_operator_service.reporting.chaos_results_projection import (
    PostgresChaosResultReader,
    PostgresChaosResultReaderConfig,
)
from fdai_operator_service.reporting.incident_rca_projection import (
    IncidentRcaReportingProjectionReader,
)
from fdai_operator_service.routes import OperatorRouteFamilies
from fdai_operator_service.runtime_projection_reader import (
    RuntimeProjectionReader,
    RuntimeProjectionReaderConfig,
)

WEBHOOK_SIGNING_SECRET_ENV = "FDAI_OPERATOR_WEBHOOK_SECRET"  # noqa: S105
COST_PSEUDONYM_KEY_ENV = "FDAI_COST_PSEUDONYM_KEY"  # noqa: S105
REFERENCE_PANEL_ROUTES = (
    PanelRoute("/kpi/autonomy", "autonomy", "autonomy"),
    PanelRoute("/capabilities", "capabilities", "capabilities"),
    PanelRoute("/configuration-baselines", "configuration-baselines", "configuration-baselines"),
    PanelRoute("/conversation-delivery", "conversation-delivery", "conversation-delivery"),
    PanelRoute("/forecast-learning", "forecast-learning", "forecast-learning"),
    PanelRoute("/onboarding", "onboarding", "onboarding"),
    PanelRoute("/operator-memory", "operator-memory", "operator-memory"),
    PanelRoute("/skills", "skills", "skills"),
)


def _build_route_families(
    *,
    environment: OperatorEnvironment,
    model_revision_owner: OperatorResolvedModelsRevisionOwner | None,
    authenticator: OperatorAuthenticator,
    store: PostgresFamilyStore | None,
    semantic_bridge: SemanticTurnBridge | None,
    semantic_bus: OperatorSemanticKafkaBus | None,
    read_model: OperatorReadModel | None,
    webhook_enabled: bool,
    context_selection_registry: ContextSelectionRegistry,
    teams_http_client: httpx.AsyncClient | None = None,
) -> tuple[
    OperatorRouteFamilies,
    StartupOwnedLocalAzureNarratorAdapters | None,
]:
    authorizer = OperatorFamilyAuthorizer(authenticator)
    report_pdf_encoder = optional_pdf_report_encoder()
    role_group_ids = {role.value: group_id for role, group_id in environment.group_ids.items()}
    if store is None:
        unavailable_conversation = UnavailableConversationAdapters()
        unavailable_workflow = UnavailableWorkflowAdapters()
        unavailable_operations = UnavailableOperationsAdapters()
        unavailable_cost = UnavailableCostGovernanceReader()
        routes = OperatorRouteFamilies(
            conversation=ConversationFamilyDependencies(
                authorizer=authorizer,
                projections=unavailable_conversation,
                outbox=unavailable_conversation,
                streams=unavailable_conversation,
            ),
            iam=build_unavailable_iam_bindings(
                authorizer=authorizer,
                role_group_ids=role_group_ids,
            ),
            workflow_authorize=authorizer.workflow,
            workflow_read_store=unavailable_workflow,
            workflow_proposal_writer=unavailable_workflow,
            operations_projection_reader=unavailable_operations,
            operations_proposal_writer=unavailable_operations,
            operations_replay_reader=unavailable_operations,
            operations_webhook_verifier=unavailable_operations,
            report_pdf_encoder=report_pdf_encoder,
            operation_panels=REFERENCE_PANEL_ROUTES,
            aks_commerce=AksCommerceFamilyDependencies(
                authenticator=authenticator,
                projections=UnavailableAksCommerceProjectionReader(),
            ),
            cost_governance=CostGovernanceFamilyDependencies(
                authenticator=authenticator,
                access=unavailable_cost,
                activation=unavailable_cost,
                projections=unavailable_cost,
            ),
        )
        return routes, None

    database_url = environment.database_url
    if database_url is None:  # pragma: no cover - store construction requires the same URL
        raise RuntimeError("validated Operator database URL is missing")
    postgres_adapters = PostgresConversationAdapters(store)
    postgres_conversation = ConversationAssuranceReader(
        ConversationAssuranceReaderConfig(
            dsn=database_url,
            statement_timeout_ms=environment.database_statement_timeout_ms,
            connect_timeout_s=environment.database_connect_timeout_s,
        ),
        fallback=postgres_adapters,
    )
    local_narrator = None
    if environment.local_azure_narrator:
        if model_revision_owner is None:
            raise RuntimeError("local Azure narrator requires a resolved-model revision owner")
        local_narrator = StartupOwnedLocalAzureNarratorAdapters(
            revision_owner=model_revision_owner,
            fallback_projections=postgres_conversation,
            fallback_streams=postgres_conversation,
        )
    conversation = local_narrator or postgres_conversation
    semantic_adapters = (
        SemanticTurnConversationAdapters(
            bridge=semantic_bridge,
            fallback_projections=conversation,
            fallback_outbox=postgres_conversation,
            fallback_streams=postgres_conversation,
            document_exporter=ConversationDocumentExporter(
                store=store,
                pdf_encoder=report_pdf_encoder,
            ),
            t1_model_health_reader=T1ModelHealthReader(store),
        )
        if semantic_bridge is not None
        else None
    )
    postgres_workflow = PostgresWorkflowAdapters(store)
    postgres_operations = PostgresOperationsAdapters(
        store,
        webhook_secret=environment.values.get(WEBHOOK_SIGNING_SECRET_ENV, "").strip() or None,
        read_investigation_replay=PostgresReadInvestigationReplayStore(
            config=PostgresReadInvestigationReplayConfig(dsn=database_url)
        ),
        context_selection_registry=context_selection_registry,
    )
    cost_reader = PostgresCostGovernanceReader(
        PostgresCostGovernanceConfig(
            dsn=database_url,
            statement_timeout_ms=environment.database_statement_timeout_ms,
            connect_timeout_s=environment.database_connect_timeout_s,
        )
    )
    operations_reader: ProjectionReader = (
        IncidentRcaReportingProjectionReader(
            postgres_operations,
            read_model,
            PostgresChaosResultReader(
                PostgresChaosResultReaderConfig(
                    dsn=database_url,
                    statement_timeout_ms=environment.database_statement_timeout_ms,
                    connect_timeout_s=environment.database_connect_timeout_s,
                )
            ),
        )
        if read_model is not None
        else postgres_operations
    )
    operations_reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig(
            dsn=database_url,
            statement_timeout_ms=environment.database_statement_timeout_ms,
            connect_timeout_s=environment.database_connect_timeout_s,
        ),
        fallback=operations_reader,
    )
    routes = OperatorRouteFamilies(
        conversation=ConversationFamilyDependencies(
            authorizer=authorizer,
            projections=semantic_adapters or conversation,
            outbox=semantic_adapters or postgres_conversation,
            streams=semantic_adapters or conversation,
            document_context_resolver=build_postgres_document_context_resolver(
                dsn=database_url,
                statement_timeout_ms=environment.database_statement_timeout_ms,
                connect_timeout_s=environment.database_connect_timeout_s,
            ),
        ),
        iam=build_postgres_iam_bindings(
            environment=environment,
            authenticator=authenticator,
            authorizer=authorizer,
            store=store,
            semantic_bus=semantic_bus,
            teams_http_client=teams_http_client,
            role_group_ids=role_group_ids,
            model_revision_owner=model_revision_owner,
        ),
        workflow_authorize=authorizer.workflow,
        workflow_read_store=postgres_workflow,
        workflow_proposal_writer=postgres_workflow,
        operations_projection_reader=operations_reader,
        operations_proposal_writer=postgres_operations,
        operations_replay_reader=postgres_operations,
        operations_webhook_verifier=(
            postgres_operations if webhook_enabled else UnavailableOperationsAdapters()
        ),
        report_pdf_encoder=report_pdf_encoder,
        operation_panels=REFERENCE_PANEL_ROUTES,
        aks_commerce=AksCommerceFamilyDependencies(
            authenticator=authenticator,
            projections=StateStoreAksCommerceProjectionReader(store),
        ),
        cost_governance=CostGovernanceFamilyDependencies(
            authenticator=authenticator,
            access=cost_reader,
            activation=cost_reader,
            activation_writer=cost_reader,
            projections=cost_reader,
            analytics=cost_reader,
            disclosure_audit=cost_reader,
            pseudonym_key=decode_cost_pseudonym_key(environment.values.get(COST_PSEUDONYM_KEY_ENV)),
            authenticated_review_access=(
                environment.values.get(
                    "FDAI_COST_GOVERNANCE_AUTHENTICATED_REVIEW_ACCESS",
                    "",
                )
                .strip()
                .casefold()
                in {"1", "true", "yes", "on"}
            ),
        ),
    )
    return routes, local_narrator


__all__ = [
    "COST_PSEUDONYM_KEY_ENV",
    "REFERENCE_PANEL_ROUTES",
    "WEBHOOK_SIGNING_SECRET_ENV",
    "_build_route_families",
]
