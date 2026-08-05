"""Production ASGI app factory for the console Operator API.

The upstream dev factory lives at
``src/fdai/delivery/operator_api/dev/local.py`` and boots
:class:`~fdai.delivery.operator_api.auth.UnsafeClaimsExtractor` +
:class:`~fdai.delivery.operator_api.read_model.InMemoryConsoleReadModel`. That
harness is never a production surface (its build-time tripwire refuses to
boot outside ``FDAI_OPERATOR_API_DEV_MODE=1``).

This module is the counterpart: the fork's composition root serves it
with any ASGI server (``uvicorn fdai.delivery.operator_api.prod:app``).
It composes the real production wiring from environment only:

- :class:`~fdai.delivery.operator_api.entra_verifier.EntraJwtVerifier` for
  bearer-token validation (JWKS + audience + issuer + expiry);
- :class:`~fdai.core.rbac.resolver.GroupMapping` +
  :class:`~fdai.core.rbac.resolver.RoleResolver` for the ``roles`` claim
  or ``groups`` fallback;
- :class:`~fdai.delivery.operator_api.postgres_read_model.PostgresConsoleReadModel`
  for audit / KPI / HIL queue projection on the persisted state.

Nothing customer-specific is baked in. Every value arrives via env vars
that a fork's IaC populates from the Managed Identity's federated
credentials + Key Vault references (see
``docs/roadmap/deployment/deploy-and-onboard.md``).

Env contract
------------

Required (fail-fast startup):

- ``FDAI_DATABASE_URL`` - psycopg 3 URL,
  ``postgresql+psycopg://user:password@host:5432/db``.
- ``FDAI_ENTRA_TENANT_ID`` / ``FDAI_API_AUDIENCE`` - from
  :class:`~fdai.delivery.operator_api.entra_verifier.EntraJwtVerifier`.
- ``FDAI_RBAC_{READERS,CONTRIBUTORS,APPROVERS,OWNERS,BREAK_GLASS}_GROUP_ID``.

Optional (respect defaults):

- ``FDAI_ENTRA_ISSUER`` / ``FDAI_ENTRA_JWKS_URI`` - override tenant defaults.
- ``FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS`` - comma-separated origin list.
  MUST NOT contain ``*`` outside dev; ``build_app`` fails fast if it does.
- ``FDAI_OPERATOR_API_STATEMENT_TIMEOUT_MS`` (default ``20000``).
- ``FDAI_OPERATOR_API_CONNECT_TIMEOUT_S`` (default ``10``).
- ``LLM_RESOLVED_MODELS_PATH`` - enables the Command Deck narrator from the
    resolver output using the Container App's managed identity.
- ``FDAI_INCIDENT_SLA_POLICY_JSON`` - enables the periodic incident SLA
    monitor. The JSON object defines positive integer ``acknowledge_seconds``
    and ``resolve_seconds`` values for every key from ``sev1`` through ``sev5``.
- ``FDAI_INCIDENT_SLA_INTERVAL_SECONDS`` (default ``60`` when the SLA policy
    is present) - positive scan interval. Ignored without the policy.
- ``FDAI_CONFIGURATION_BASELINE_JSON``, ``FDAI_CONFIGURATION_BASELINE_DOCX``,
  and ``FDAI_CONFIGURATION_BASELINE_RESOURCE_GROUP`` - all-or-none absolute
  mounted baseline binding. It requires the complete Azure reader binding and
  the resource group must already be in ``FDAI_AZURE_READER_RESOURCE_GROUPS``.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Final

import httpx
from starlette.applications import Starlette

from fdai.agents import OWNED_OBJECT_TOPICS
from fdai.core.conversation.outbound_delivery import (
    DurableOutboundDeliveryConfig,
    DurableOutboundDeliveryCoordinator,
)
from fdai.core.conversation_assurance import (
    ConversationAssuranceEvaluator,
    ConversationAssuranceLifecycleCoordinator,
    HoldingOntologyAdequacyInvestigator,
    PromotionConfig,
)
from fdai.core.execution_authorization import AccessGrantRequestService
from fdai.core.human_assignment import AssignmentCaseService, HandoverGoalService
from fdai.core.metering.budget import InMemoryBudgetLedger, ModelBudget
from fdai.core.rbac.access_request import AccessRequestService
from fdai.core.rbac.kill_switch_command import KillSwitchCommandService
from fdai.core.stewardship import load_stewardship_from_yaml
from fdai.delivery.catalog_search import (
    load_shipped_catalog_search_sources,
)
from fdai.delivery.configuration_review_store import (
    StateStoreConfigurationReviewCampaignStore,
)
from fdai.delivery.event_bus_multiplex import MultiplexedEventBus
from fdai.delivery.handover_events import EventBusHandoverAvailabilityPublisher
from fdai.delivery.ingestion_gateway.chat_evidence import UploaderDocumentEvidenceResolver
from fdai.delivery.operator_api.app.catalog_reference import (
    load_best_practice_reference,
    load_mcsb_reference,
)
from fdai.delivery.operator_api.main import OperatorApiConfig, build_app
from fdai.delivery.operator_api.production import env_contract as _env
from fdai.delivery.operator_api.production.catalog_search import (
    ProductionCatalogSearch,
    build_production_catalog_search,
)
from fdai.delivery.operator_api.production.config import (
    ProdOperatorApiConfigError,
    _check_required_env,
    _parse_cors_origins,
    _parse_positive_int,
    build_prod_read_model,
)
from fdai.delivery.operator_api.production.configuration_drift import (
    build_production_configuration_drift_context,
    build_production_configuration_review,
)
from fdai.delivery.operator_api.production.data_sources import build_production_data_sources
from fdai.delivery.operator_api.production.identity import build_production_identity
from fdai.delivery.operator_api.production.knowledge_context import (
    build_production_knowledge_context,
)
from fdai.delivery.operator_api.production.onboarding import build_production_onboarding
from fdai.delivery.operator_api.production.panels import build_production_panels
from fdai.delivery.operator_api.production.persistence import build_production_persistence
from fdai.delivery.operator_api.production.python_tasks import build_production_python_tasks
from fdai.delivery.operator_api.production.runtime_wiring import build_production_runtime
from fdai.delivery.operator_api.production.scope import build_production_scope_source
from fdai.delivery.operator_api.production.skill_sources import build_production_skill_sources
from fdai.delivery.operator_api.production.skills import build_production_skill_runtime
from fdai.delivery.operator_api.production.user_context import build_production_user_context
from fdai.delivery.operator_api.production.views import _build_dynamic_views
from fdai.delivery.operator_api.routes.arb_status import ArchitectureReviewStatusPanel
from fdai.delivery.operator_api.routes.background_runtime import build_background_task_runtime
from fdai.delivery.operator_api.routes.busy_input_runtime import build_postgres_busy_input_runtime
from fdai.delivery.operator_api.routes.chat import backend_from_env
from fdai.delivery.operator_api.routes.chat_inventory_ontology import (
    inventory_query_function_type,
)
from fdai.delivery.operator_api.routes.chat_inventory_semantic_retrieval import (
    EmbeddingInventorySemanticResolver,
)
from fdai.delivery.operator_api.routes.chat_web_search import chat_web_search_from_env
from fdai.delivery.operator_api.routes.configuration_baselines import (
    ConfigurationBaselinesPanel,
)
from fdai.delivery.operator_api.routes.conversation_assurance_intake import (
    ConversationAssurancePostTurnSubmitter,
)
from fdai.delivery.operator_api.routes.post_turn_event_bus import EventBusPostTurnReviewIntake
from fdai.delivery.operator_api.routes.post_turn_review import PostTurnReviewQueue
from fdai.delivery.persistence import (
    PostgresConversationAssuranceLedger,
    PostgresConversationAssuranceLedgerConfig,
    PostgresConversationPolicyCandidateStore,
    PostgresConversationPolicyCandidateStoreConfig,
    PostgresModelHealthTransitionSink,
    PostgresModelHealthTransitionSinkConfig,
    PostgresReadInvestigationRunStore,
    PostgresReadInvestigationRunStoreConfig,
    StateStoreOntologyAdequacyReviewSink,
)
from fdai.delivery.persistence.postgres_conversation_assurance_runtime import (
    PostgresConversationPolicyRuntime,
    PostgresConversationPolicyRuntimeConfig,
)
from fdai.delivery.persistence.postgres_conversation_delivery import (
    PostgresConversationDeliveryStore,
    PostgresConversationDeliveryStoreConfig,
)
from fdai.delivery.persistence.postgres_document_ingestion import (
    PostgresDocumentMetadataStore,
    PostgresDocumentMetadataStoreConfig,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventoryGraphProvider,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_principal_binding import (
    PostgresPrincipalConversationBindingStore,
    PostgresPrincipalConversationBindingStoreConfig,
)
from fdai.delivery.persistence.postgres_task_worker import (
    PostgresTaskWorkerStore,
    PostgresTaskWorkerStoreConfig,
)
from fdai.delivery.stewardship import (
    HumanIdentityLivenessDirectory,
    StewardshipHealthMonitor,
)
from fdai.rule_catalog.schema.catalog_search import build_catalog_search_documents
from fdai.runtime.conversation_assurance import (
    build_azure_conversation_assurance_evaluators,
    build_conversation_assurance_coordinator,
    build_conversation_assurance_reviewer,
)
from fdai.runtime.conversation_assurance_lifecycle import (
    BLIND_CONVERSATION_SCENARIOS,
    BilingualBlindPolicyTrialMeasurer,
    DeterministicNarratorPolicyProposer,
    pricing_narrator_cost_estimator,
)
from fdai.shared.contracts.models import OntologyDeclarationKind
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.catalog_search import CatalogSemanticIndex
from fdai.shared.providers.local import EnvSecretProvider

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[5]

# psycopg 3 (the driver this repo ships) accepts either the bare
# ``postgresql://`` scheme or the SQLAlchemy-style ``postgresql+psycopg://``
# alias. Any other ``+<driver>`` suffix (e.g. ``+asyncpg``, ``+psycopg2``)
# is a caller mistake - the connection would fail with a cryptic driver
# error deep inside psycopg. Reject explicitly at boot with a clear
# ProdOperatorApiConfigError instead.
_RBAC_ENV: Final[Mapping[str, str]] = {
    "readers": "FDAI_RBAC_READERS_GROUP_ID",
    "contributors": "FDAI_RBAC_CONTRIBUTORS_GROUP_ID",
    "approvers": "FDAI_RBAC_APPROVERS_GROUP_ID",
    "owners": "FDAI_RBAC_OWNERS_GROUP_ID",
    "break_glass": "FDAI_RBAC_BREAK_GLASS_GROUP_ID",
}


def build_prod_app(
    environ: Mapping[str, str] | None = None,
    *,
    catalog_semantic_index: CatalogSemanticIndex | None = None,
) -> Starlette:
    """Assemble the production ASGI app from environment and explicit providers.

    - Refuses to boot when any required env var is missing
      (:class:`ProdOperatorApiConfigError`).
    - Wires the production :class:`EntraJwtVerifier` (JWKS + ``aud`` +
      ``iss`` + ``exp``) - never the dev-mode
      :class:`~fdai.delivery.operator_api.auth.UnsafeClaimsExtractor`.
    - Binds :class:`PostgresConsoleReadModel` on the persisted schema.
    - ``dev_mode`` stays ``False``; ``build_app`` enforces the extra
      staging/prod guards.

    All required env vars are validated up-front so a cold-boot with an
    entirely unpopulated env produces ONE error listing every missing
    slot, instead of eight sequential boot failures.
    """
    env = environ if environ is not None else os.environ
    _check_required_env(
        env,
        (
            _env.DATABASE_URL_ENV,
            _env.TENANT_ENV,
            _env.AUDIENCE_ENV,
            *_RBAC_ENV.values(),
        ),
    )
    read_model = build_prod_read_model(env)
    persistence = build_production_persistence(read_model)
    state_store_config = persistence.state_store_config
    state_store = persistence.state_store
    from fdai.delivery.runtime_settings import RuntimeSettingsService

    runtime_settings = RuntimeSettingsService(store=state_store, env=env, durable=True)
    identity = build_production_identity(env)
    authenticator = identity.authenticator
    group_mapping = identity.group_mapping
    iam_directory = identity.iam_directory
    iam_provider = identity.iam_provider
    shutdown_callbacks = identity.shutdown_callbacks
    catalog_search = (
        ProductionCatalogSearch(index=catalog_semantic_index)
        if catalog_semantic_index is not None
        else build_production_catalog_search(env=env, dsn=read_model._config.dsn)
    )
    catalog_semantic_index = catalog_search.index
    shutdown_callbacks = (*shutdown_callbacks, *catalog_search.shutdown_callbacks)
    cors_origins = _parse_cors_origins(env.get(_env.CORS_ORIGINS_ENV))
    (
        reporting,
        process_views,
        object_types,
        link_types,
        action_types,
        workflows,
        workflow_authoring,
        workflow_execution,
    ) = _build_dynamic_views(
        dsn=read_model._config.dsn,
        statement_timeout_ms=read_model._config.statement_timeout_ms,
        connect_timeout_s=read_model._config.connect_timeout_s,
        read_model=read_model,
        group_mapping=group_mapping,
    )
    ontology_function_types = (inventory_query_function_type(),)
    ontology_release = build_ontology_release(
        object_types=object_types,
        link_types=link_types,
        action_types=action_types,
        function_types=ontology_function_types,
    )
    inventory_semantic_resolver = (
        EmbeddingInventorySemanticResolver(
            embedder=catalog_search.inventory_embedder,
            target_ref=ontology_release.type_ref(
                OntologyDeclarationKind.FUNCTION,
                "inventory.select_resources",
            ),
        )
        if catalog_search.inventory_embedder is not None
        else None
    )
    enforce_workflows = frozenset(
        item.strip()
        for item in env.get(_env.WORKFLOW_ENFORCE_ALLOWLIST_ENV, "").split(",")
        if item.strip()
    )
    user_context_group = build_production_user_context(
        read_model=read_model,
        object_types=object_types,
        link_types=link_types,
        action_types=action_types,
        workflows=workflows,
        promoted_workflows=enforce_workflows,
    )
    conversation_history_store = user_context_group.conversation_history_store
    conversation_policy_store = user_context_group.conversation_policy_store
    user_context_ontology_projector = user_context_group.ontology_projector
    user_context = user_context_group.routes
    workflow_definitions = user_context_group.workflow_definitions
    skill_runtime = build_production_skill_runtime(
        env=env,
        dsn=read_model._config.dsn,
        statement_timeout_ms=read_model._config.statement_timeout_ms,
        connect_timeout_s=read_model._config.connect_timeout_s,
    )
    skill_sources = build_production_skill_sources(
        env=env,
        dsn=read_model._config.dsn,
        statement_timeout_ms=read_model._config.statement_timeout_ms,
        connect_timeout_s=read_model._config.connect_timeout_s,
        secrets=EnvSecretProvider(env=env, prefix=""),
        refresh_runtime=skill_runtime.startup,
    )
    knowledge_context = build_production_knowledge_context(
        dsn=read_model._config.dsn,
        statement_timeout_ms=read_model._config.statement_timeout_ms,
        connect_timeout_s=read_model._config.connect_timeout_s,
        skill_disclosure=skill_runtime.disclosure,
        skill_sources=skill_sources.routes,
        user_memories=user_context.memories,
    )
    runtime = build_production_runtime(
        env=env,
        repo_root=_REPO_ROOT,
        read_model=read_model,
        state_store=state_store,
        state_store_config=state_store_config,
        startup_callbacks=(
            *user_context_group.startup_callbacks,
            skill_runtime.startup,
            skill_sources.startup,
        ),
        shutdown_callbacks=(*shutdown_callbacks, skill_sources.shutdown),
    )
    shutdown_callbacks = runtime.shutdown_callbacks
    post_turn_review_queue = (
        PostTurnReviewQueue(
            preferences=user_context.preferences,
            intake=EventBusPostTurnReviewIntake(
                bus=MultiplexedEventBus(
                    bus=runtime.event_bus,
                    logical_topics=OWNED_OBJECT_TOPICS,
                    physical_topic=env.get(
                        "FDAI_PANTHEON_OBJECT_TOPIC", "aw.pantheon.objects"
                    ).strip(),
                )
            ),
        )
        if runtime.event_bus is not None
        else None
    )
    if post_turn_review_queue is not None:
        shutdown_callbacks = (*shutdown_callbacks, post_turn_review_queue.close)
    if enforce_workflows:
        if runtime.event_bus is None or not runtime.event_topic:
            raise ProdOperatorApiConfigError(
                f"{_env.WORKFLOW_ENFORCE_ALLOWLIST_ENV} requires configured event transport"
            )
        from fdai.delivery.workflow_action_dispatcher import EventBusWorkflowActionDispatcher

        workflow_execution = replace(
            workflow_execution,
            orchestrator=workflow_execution.orchestrator.with_action_dispatcher(
                EventBusWorkflowActionDispatcher(
                    event_bus=runtime.event_bus,
                    topic=runtime.event_topic,
                )
            ),
            enforce_workflows=enforce_workflows,
        )
    python_task_services = build_production_python_tasks(
        env=env,
        dsn=read_model._config.dsn,
        statement_timeout_ms=read_model._config.statement_timeout_ms,
        connect_timeout_s=read_model._config.connect_timeout_s,
        event_bus=runtime.event_bus,
        event_topic=runtime.event_topic,
        workflows=workflows,
        shutdown_callbacks=shutdown_callbacks,
    )
    python_tasks = python_task_services.routes
    shutdown_callbacks = python_task_services.shutdown_callbacks
    onboarding = build_production_onboarding(
        env=env,
        shutdown_callbacks=shutdown_callbacks,
    )
    shutdown_callbacks = onboarding.shutdown_callbacks
    scope_source = build_production_scope_source(env)
    assurance_ledger = PostgresConversationAssuranceLedger(
        config=PostgresConversationAssuranceLedgerConfig(
            dsn=read_model._config.dsn,
            statement_timeout_ms=read_model._config.statement_timeout_ms,
            connect_timeout_s=read_model._config.connect_timeout_s,
        )
    )
    assurance_policy_runtime = PostgresConversationPolicyRuntime(
        config=PostgresConversationPolicyRuntimeConfig(
            dsn=read_model._config.dsn,
            statement_timeout_ms=read_model._config.statement_timeout_ms,
            connect_timeout_s=read_model._config.connect_timeout_s,
        )
    )
    assurance_evaluators: tuple[ConversationAssuranceEvaluator, ...] = ()
    chat = None
    chat_web_search = None
    metering_sink = None
    resolved_models_path = env.get(_env.RESOLVED_MODELS_ENV, "").strip()
    narrator_api_key_configured = all(
        env.get(name, "").strip()
        for name in (
            "FDAI_NARRATOR_BASE_URL",
            "FDAI_NARRATOR_API_KEY",
            "FDAI_NARRATOR_MODEL",
        )
    )
    web_search_raw = env.get("FDAI_WEB_SEARCH_ENABLED", "").strip().casefold()
    web_search_configured = web_search_raw not in {"", "0", "false", "no", "off"}
    if resolved_models_path or narrator_api_key_configured or web_search_configured:
        from fdai.composition import load_pricing_table
        from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
        from fdai.delivery.persistence import PostgresMeteringStore, PostgresMeteringStoreConfig

        chat_http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=90.0, write=15.0, pool=5.0)
        )
        chat_identity = (
            ManagedIdentityWorkloadIdentity(http_client=chat_http) if resolved_models_path else None
        )
        pricing_table = load_pricing_table(_REPO_ROOT / "rule-catalog" / "llm-pricing.yaml")
        metering_sink = PostgresMeteringStore(
            config=PostgresMeteringStoreConfig(
                dsn=read_model._config.dsn,
                statement_timeout_ms=read_model._config.statement_timeout_ms,
                connect_timeout_s=read_model._config.connect_timeout_s,
            )
        )
        chat = backend_from_env(
            dict(env),
            identity=chat_identity,
            http_client=chat_http,
            metering_sink=metering_sink,
            pricing=pricing_table,
        )
        chat_web_search = chat_web_search_from_env(
            env,
            identity=chat_identity,
            http_client=chat_http,
        )
        if resolved_models_path and chat_identity is not None:
            assurance_evaluators = build_azure_conversation_assurance_evaluators(
                repo_root=_REPO_ROOT,
                resolved_models_path=resolved_models_path,
                identity=chat_identity,
                http_client=chat_http,
                pricing=pricing_table,
                metering_sink=metering_sink,
            )

        async def _close_chat_http() -> None:
            await chat_http.aclose()

        shutdown_callbacks = (*shutdown_callbacks, _close_chat_http)
    assurance_budget = InMemoryBudgetLedger(
        ModelBudget(
            max_calls_per_correlation=3,
            max_cost_microusd_per_correlation=50_000,
        )
    )
    assurance_coordinator = build_conversation_assurance_coordinator(
        ledger=assurance_ledger,
        budget=assurance_budget,
        evaluators=assurance_evaluators,
    )
    assurance_reviewer = build_conversation_assurance_reviewer(
        budget=assurance_budget,
        evaluators=assurance_evaluators,
    )
    assurance_lifecycle = (
        ConversationAssuranceLifecycleCoordinator(
            store=PostgresConversationPolicyCandidateStore(
                config=PostgresConversationPolicyCandidateStoreConfig(
                    dsn=read_model._config.dsn,
                    statement_timeout_ms=read_model._config.statement_timeout_ms,
                    connect_timeout_s=read_model._config.connect_timeout_s,
                )
            ),
            proposer=DeterministicNarratorPolicyProposer(
                runtime=assurance_policy_runtime,
            ),
            measurer=BilingualBlindPolicyTrialMeasurer(
                backend=chat,
                reviewer=assurance_reviewer,
                cost_estimator=pricing_narrator_cost_estimator(pricing_table),
            ),
            publisher=assurance_policy_runtime,
            promotion_config=PromotionConfig(
                min_samples=len(BLIND_CONVERSATION_SCENARIOS),
                min_score_delta_lcb95=0.01,
            ),
        )
        if chat is not None and assurance_reviewer is not None
        else None
    )
    assurance_submitter = ConversationAssurancePostTurnSubmitter(
        coordinator=assurance_coordinator,
        delegate=post_turn_review_queue,
        ledger=assurance_ledger if assurance_lifecycle is not None else None,
        lifecycle=assurance_lifecycle,
        adequacy_investigator=HoldingOntologyAdequacyInvestigator(),
        adequacy_sink=StateStoreOntologyAdequacyReviewSink(state_store),
    )
    shutdown_callbacks = (*shutdown_callbacks, assurance_submitter.close)
    model_settings = None
    if resolved_models_path:
        from fdai.delivery.operator_api.routes.model_settings import ModelSettingsService

        resolved_models_file = Path(resolved_models_path)
        registry_file = resolved_models_file.parent / "rule-catalog" / "llm-registry.yaml"
        model_settings = ModelSettingsService(
            resolved_models_path=resolved_models_file,
            registry_path=registry_file if registry_file.is_file() else None,
            store=state_store,
            backend=chat,
            web_search_resolver=chat_web_search,
            model_routing_status=PostgresModelHealthTransitionSink(
                config=PostgresModelHealthTransitionSinkConfig(
                    dsn=read_model._config.dsn,
                    statement_timeout_ms=read_model._config.statement_timeout_ms,
                    connect_timeout_s=read_model._config.connect_timeout_s,
                )
            ),
        )
    log_query_provider = None
    monitor_workspace_id = env.get("FDAI_MONITOR_WORKSPACE_ID", "").strip()
    if chat is not None and monitor_workspace_id:
        from fdai.delivery.azure.log_query import (
            AzureLogAnalyticsQueryConfig,
            AzureLogAnalyticsQueryProvider,
        )
        from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity

        log_query_http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=35.0, write=10.0, pool=5.0)
        )
        log_query_provider = AzureLogAnalyticsQueryProvider(
            config=AzureLogAnalyticsQueryConfig(workspace_id=monitor_workspace_id),
            identity=ManagedIdentityWorkloadIdentity.from_env(
                http_client=log_query_http,
                env=env,
            ),
            http_client=log_query_http,
        )

        async def _close_log_query_http() -> None:
            await log_query_http.aclose()

        shutdown_callbacks = (*shutdown_callbacks, _close_log_query_http)
    conversation_delivery_store = PostgresConversationDeliveryStore(
        config=PostgresConversationDeliveryStoreConfig(
            dsn=read_model._config.dsn,
            statement_timeout_ms=read_model._config.statement_timeout_ms,
            connect_timeout_s=read_model._config.connect_timeout_s,
        )
    )
    principal_binding_store = PostgresPrincipalConversationBindingStore(
        config=PostgresPrincipalConversationBindingStoreConfig(
            dsn=read_model._config.dsn,
            statement_timeout_ms=read_model._config.statement_timeout_ms,
            connect_timeout_s=read_model._config.connect_timeout_s,
        )
    )
    background_outbound_delivery = DurableOutboundDeliveryCoordinator(
        store=conversation_delivery_store,
        channels={},
        config=DurableOutboundDeliveryConfig(
            worker_id=env.get("HOSTNAME", "fdai-background-delivery").strip()
            or "fdai-background-delivery"
        ),
    )
    background_executor = None
    read_investigation_service = None
    subscription_health_provider = None
    read_latency_store = None
    read_investigation_run_store = None
    read_investigation_ledger_config = None
    inventory_activity_provider = None
    reader_startup_callbacks: tuple[Callable[[], Awaitable[None]], ...] = ()
    reader_scope_ref = None
    reader_identity = None
    reader_http = None
    reader_subscription = env.get("FDAI_AZURE_READER_SUBSCRIPTION_ID", "").strip()
    reader_client_id = env.get("FDAI_AZURE_READER_CLIENT_ID", "").strip()
    reader_resource_groups = tuple(
        dict.fromkeys(
            value.strip()
            for value in env.get("FDAI_AZURE_READER_RESOURCE_GROUPS", "").split(",")
            if value.strip()
        )
    )
    if reader_subscription and reader_client_id and reader_resource_groups:
        from fdai.core.read_investigation import ReadInvestigationService
        from fdai.delivery.azure.read_investigation import (
            AzureReadInvestigationProvider,
            AzureReadRestConfig,
            AzureReadScopeBinding,
            AzureRestReadTransport,
            build_azure_mcp_read_wiring,
        )
        from fdai.delivery.azure.subscription_health import (
            AzureSubscriptionHealthConfig,
            AzureSubscriptionHealthProvider,
        )
        from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
        from fdai.delivery.operator_api.routes.background_executor import (
            ReadInvestigationBackgroundTaskExecutor,
            ServerOwnedReadInvestigationRequestFactory,
        )
        from fdai.delivery.operator_api.routes.read_investigations import (
            ReadInvestigationRunLedgerConfig,
        )
        from fdai.delivery.persistence import StateStoreReadLatencyProfileStore

        read_investigation_run_store = PostgresReadInvestigationRunStore(
            config=PostgresReadInvestigationRunStoreConfig(
                dsn=read_model._config.dsn,
                statement_timeout_ms=read_model._config.statement_timeout_ms,
                connect_timeout_s=read_model._config.connect_timeout_s,
            )
        )
        read_investigation_ledger_config = ReadInvestigationRunLedgerConfig(
            lease_seconds=_parse_positive_int(env, _env.READ_INVESTIGATION_LEASE_SECONDS_ENV, 30),
            retention_seconds=_parse_positive_int(
                env,
                _env.READ_INVESTIGATION_RETENTION_SECONDS_ENV,
                3_600,
            ),
            retry_after_seconds=_parse_positive_int(
                env,
                _env.READ_INVESTIGATION_RETRY_AFTER_SECONDS_ENV,
                3,
            ),
            reconcile_limit=_parse_positive_int(
                env,
                _env.READ_INVESTIGATION_RECONCILE_LIMIT_ENV,
                25,
            ),
            purge_limit=_parse_positive_int(
                env,
                _env.READ_INVESTIGATION_PURGE_LIMIT_ENV,
                25,
            ),
        )

        reader_scope_ref = "azure-reader-default"
        reader_http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=35.0, write=10.0, pool=5.0)
        )
        reader_identity = ManagedIdentityWorkloadIdentity.from_env(
            http_client=reader_http,
            env=env,
            client_id_env="FDAI_AZURE_READER_CLIENT_ID",
        )
        reader_transport = AzureRestReadTransport(
            config=AzureReadRestConfig(
                scopes=(
                    AzureReadScopeBinding(
                        scope_ref=reader_scope_ref,
                        subscription_id=reader_subscription,
                        resource_groups=reader_resource_groups,
                        workspace_id=env.get("FDAI_MONITOR_WORKSPACE_ID", "").strip() or None,
                    ),
                ),
                resource_type_map=(
                    ("Microsoft.Compute/virtualMachines", "compute.vm"),
                    ("Microsoft.DBforPostgreSQL/flexibleServers", "postgresql-server"),
                    ("Microsoft.Network/networkSecurityGroups", "network.nsg"),
                    ("Microsoft.Network/virtualNetworks", "network.vnet"),
                ),
            ),
            identity=reader_identity,
            http_client=reader_http,
        )

        async def _inventory_activity_provider(
            lookback_seconds: int,
            max_events: int,
        ) -> Mapping[str, object]:
            return await reader_transport.query_scope_activity(
                reader_scope_ref,
                lookback_seconds=lookback_seconds,
                max_events=max_events,
            )

        inventory_activity_provider = _inventory_activity_provider
        mcp_wiring = build_azure_mcp_read_wiring(
            fallback=reader_transport,
            environment=env,
            reader_client_id=reader_client_id,
            subscription_id=reader_subscription,
        )
        reader_startup_callbacks = (mcp_wiring.start,)
        read_latency_store = StateStoreReadLatencyProfileStore(store=state_store)
        read_investigation_service = ReadInvestigationService(
            AzureReadInvestigationProvider(mcp_wiring.transport),
            latency_store=read_latency_store,
        )
        subscription_health_provider = AzureSubscriptionHealthProvider(
            config=AzureSubscriptionHealthConfig(
                subscription_id=reader_subscription,
                resource_groups=reader_resource_groups,
            ),
            identity=reader_identity,
            http_client=reader_http,
        )
        background_executor = ReadInvestigationBackgroundTaskExecutor(
            service=read_investigation_service,
            request_factory=ServerOwnedReadInvestigationRequestFactory(scope_ref=reader_scope_ref),
        )

        async def _close_reader_http() -> None:
            await mcp_wiring.close()
            await reader_http.aclose()

        shutdown_callbacks = (*shutdown_callbacks, _close_reader_http)
    configuration_drift_requested = any(
        env.get(name, "").strip()
        for name in (
            _env.CONFIGURATION_BASELINE_JSON_ENV,
            _env.CONFIGURATION_BASELINE_DOCX_ENV,
            _env.CONFIGURATION_BASELINE_RESOURCE_GROUP_ENV,
        )
    )
    if configuration_drift_requested and (reader_identity is None or reader_http is None):
        raise ProdOperatorApiConfigError(
            "production configuration baseline requires the complete Azure reader binding"
        )
    try:
        configuration_drift_context = (
            None
            if reader_identity is None or reader_http is None
            else build_production_configuration_drift_context(
                environ=env,
                subscription_id=reader_subscription,
                allowed_resource_groups=reader_resource_groups,
                identity=reader_identity,
                http_client=reader_http,
            )
        )
    except (OSError, ValueError) as exc:
        raise ProdOperatorApiConfigError(str(exc)) from exc
    configuration_review = (
        None
        if configuration_drift_context is None
        else build_production_configuration_review(
            context=configuration_drift_context,
            state_store=state_store,
            dsn=read_model._config.dsn,
            statement_timeout_ms=read_model._config.statement_timeout_ms,
            connect_timeout_s=read_model._config.connect_timeout_s,
        )
    )
    background_runtime = build_background_task_runtime(
        executor=background_executor,
        state_store=state_store,
        conversation_history=conversation_history_store,
        dsn=read_model._config.dsn,
        statement_timeout_ms=read_model._config.statement_timeout_ms,
        connect_timeout_s=read_model._config.connect_timeout_s,
        env=env,
        outbound_delivery=background_outbound_delivery,
        binding_store=principal_binding_store,
    )
    if background_runtime is not None:
        shutdown_callbacks = (*shutdown_callbacks, background_runtime.coordinator.shutdown)
    read_investigation_routes = None
    read_investigation_chat_delegate = None
    if (
        background_runtime is not None
        and read_investigation_service is not None
        and read_latency_store is not None
        and read_investigation_run_store is not None
        and read_investigation_ledger_config is not None
        and reader_scope_ref is not None
    ):
        from fdai.core.read_investigation import interactive_investigation_policy
        from fdai.delivery.operator_api.routes.read_investigation_catalog import (
            load_bound_investigation_intents,
        )
        from fdai.delivery.operator_api.routes.read_investigation_responder import (
            HeimdallReadInvestigationChatDelegate,
            HeimdallReadInvestigationResponder,
        )
        from fdai.delivery.operator_api.routes.read_investigations import (
            IdempotentReadInvestigationExecutor,
            ReadInvestigationRoutesConfig,
        )

        load_bound_investigation_intents(_REPO_ROOT)
        read_investigation_routes = ReadInvestigationRoutesConfig(
            service=read_investigation_service,
            run_store=read_investigation_run_store,
            latency_store=read_latency_store,
            background=background_runtime.routes,
            scope_ref=reader_scope_ref,
            run_ledger=read_investigation_ledger_config,
        )
        read_investigation_chat_delegate = HeimdallReadInvestigationChatDelegate(
            responder=HeimdallReadInvestigationResponder(
                executor=IdempotentReadInvestigationExecutor(read_investigation_routes),
                latency_store=read_latency_store,
                scope_ref=reader_scope_ref,
                scope_activity_provider=inventory_activity_provider,
                policy=interactive_investigation_policy(),
            )
        )
    remote_agent_delegate = None
    if runtime.event_bus is not None:
        from fdai.delivery.agent_introspection_bus import (
            AGENT_INTROSPECTION_TOPICS,
            EventBusAgentIntrospectionClient,
        )

        remote_agent_delegate = EventBusAgentIntrospectionClient(
            event_bus=MultiplexedEventBus(
                bus=runtime.event_bus,
                logical_topics=AGENT_INTROSPECTION_TOPICS,
                physical_topic=env.get(
                    "FDAI_PANTHEON_OBJECT_TOPIC",
                    "aw.pantheon.objects",
                ).strip(),
            ),
            instance_id=f"operator-api-{uuid.uuid4().hex[:16]}",
            fallback_delegate=read_investigation_chat_delegate,
        )
        shutdown_callbacks = (remote_agent_delegate.stop, *shutdown_callbacks)
    busy_input_runtime = (
        build_postgres_busy_input_runtime(
            dsn=read_model._config.dsn,
            statement_timeout_ms=read_model._config.statement_timeout_ms,
            connect_timeout_s=read_model._config.connect_timeout_s,
        )
        if chat is not None
        else None
    )
    stewardship_map = load_stewardship_from_yaml(
        _REPO_ROOT / "config" / "agent-stewardship.yaml",
        environ=env,
    )
    require_stewardship_bindings = env.get(
        "FDAI_STEWARDSHIP_REQUIRE_BINDINGS", ""
    ).strip().casefold() in {"1", "true", "yes", "on"}
    stewardship_startup_callbacks: tuple[Callable[[], Awaitable[None]], ...] = ()
    if require_stewardship_bindings and iam_directory is None:
        raise ProdOperatorApiConfigError(
            "FDAI_STEWARDSHIP_REQUIRE_BINDINGS requires "
            "FDAI_IAM_DIRECTORY_PROVIDER=entra for scheduled liveness checks"
        )
    if iam_directory is not None:
        stewardship_health = StewardshipHealthMonitor(
            stewardship_map=stewardship_map,
            directory=HumanIdentityLivenessDirectory(iam_directory),
            state_store=state_store,
            interval_seconds=_parse_positive_int(
                env,
                _env.STEWARDSHIP_AUDIT_INTERVAL_ENV,
                3600,
            ),
        )
        stewardship_startup_callbacks = (stewardship_health.start,)
        shutdown_callbacks = (stewardship_health.stop, *shutdown_callbacks)
    catalog_search_sources = load_shipped_catalog_search_sources(repo_root=_REPO_ROOT)
    catalog_search_documents = build_catalog_search_documents(
        rules=catalog_search_sources.rules,
        action_types=catalog_search_sources.action_types,
        policy_semantics=catalog_search_sources.policy_semantics,
    )

    async def _seed_catalog_semantic_index() -> None:
        if catalog_semantic_index is not None:
            await catalog_semantic_index.synchronize(catalog_search_documents)

    config = OperatorApiConfig(
        dev_mode=False,
        cors_allow_origins=cors_origins,
        ontology_object_types=object_types,
        ontology_link_types=link_types,
        ontology_action_types=action_types,
        ontology_function_types=ontology_function_types,
        operating_model_status_reader=state_store,
        inventory_graph_provider=PostgresInventoryGraphProvider(
            config=PostgresInventorySnapshotStoreConfig(
                dsn=read_model._config.dsn,
                freshness_budget_seconds=_parse_positive_int(
                    env, _env.INVENTORY_FRESHNESS_ENV, 86_400
                ),
                statement_timeout_ms=read_model._config.statement_timeout_ms,
                connect_timeout_s=read_model._config.connect_timeout_s,
            )
        ),
        inventory_semantic_resolver=inventory_semantic_resolver,
        inventory_activity_provider=inventory_activity_provider,
        subscription_health_provider=subscription_health_provider,
        detection_readiness_reader=state_store,
        execution_access_grants=AccessGrantRequestService(store=state_store),
        t2_recovery_reader=state_store,
        best_practice_controls=load_best_practice_reference(_REPO_ROOT),
        mcsb_catalogs=load_mcsb_reference(_REPO_ROOT),
        rule_catalog_rules=catalog_search_sources.rules,
        rule_catalog_policies_root=_REPO_ROOT / "policies",
        rule_catalog_remediation_root=_REPO_ROOT / "rule-catalog" / "remediation",
        rule_catalog_semantic_index=catalog_semantic_index,
        scope_source=scope_source,
        log_query_provider=log_query_provider,
        reporting=reporting,
        process_views=process_views,
        workflow_authoring=workflow_authoring,
        workflow_execution=workflow_execution,
        workflow_definitions=workflow_definitions,
        stewardship_map=stewardship_map,
        stewardship_health_reader=state_store,
        user_context=user_context,
        model_settings=model_settings,
        runtime_settings=runtime_settings,
        python_tasks=python_tasks,
        chat=chat,
        llm_usage_reader=metering_sink,
        chat_document_evidence=UploaderDocumentEvidenceResolver(
            metadata=PostgresDocumentMetadataStore(
                config=PostgresDocumentMetadataStoreConfig(
                    dsn=read_model._config.dsn,
                    statement_timeout_ms=read_model._config.statement_timeout_ms,
                    connect_timeout_s=read_model._config.connect_timeout_s,
                )
            )
        ),
        chat_agent_delegate=remote_agent_delegate or read_investigation_chat_delegate,
        skill_disclosure=skill_runtime.disclosure,
        skill_sources=skill_sources.routes,
        knowledge_context=knowledge_context,
        configuration_drift_context=configuration_drift_context,
        configuration_review_runtime=(
            configuration_review.runtime if configuration_review is not None else None
        ),
        automation_blueprint_review=(
            configuration_review.blueprints if configuration_review is not None else None
        ),
        busy_input_runtime=busy_input_runtime,
        conversation_delivery_store=conversation_delivery_store,
        chat_web_search=chat_web_search,
        chat_probe_interval_seconds=_parse_positive_int(
            env,
            "FDAI_NARRATOR_PROBE_INTERVAL_SECONDS",
            300,
        ),
        conversation_history_store=conversation_history_store,
        conversation_assurance_ledger=assurance_ledger,
        conversation_assurance_runtime=assurance_policy_runtime,
        conversation_search=user_context.conversation_search,
        conversation_policy_store=conversation_policy_store,
        user_context_ontology_projector=user_context_ontology_projector,
        post_turn_review_submitter=assurance_submitter,
        task_worker_store=PostgresTaskWorkerStore(
            config=PostgresTaskWorkerStoreConfig(
                dsn=read_model._config.dsn,
                statement_timeout_ms=read_model._config.statement_timeout_ms,
                connect_timeout_s=read_model._config.connect_timeout_s,
            )
        ),
        background_tasks=(background_runtime.routes if background_runtime is not None else None),
        read_investigations=read_investigation_routes,
        extra_panels=(
            *build_production_panels(
                read_model=read_model,
                onboarding_probe=onboarding.probe,
                onboarding_configured=onboarding.configured,
                state_store=state_store,
                action_types=action_types,
                active_rule_count=sum(
                    1 for _ in (_REPO_ROOT / "rule-catalog" / "catalog").glob("*.yaml")
                ),
            ),
            *(
                (
                    ConfigurationBaselinesPanel(
                        configuration_drift_context,
                        review_store=StateStoreConfigurationReviewCampaignStore(state_store),
                    ),
                )
                if configuration_drift_context is not None
                else ()
            ),
            skill_runtime.panel,
            ArchitectureReviewStatusPanel(
                manifest_path=_REPO_ROOT / "config" / "architecture-review.yaml",
                repo_root=_REPO_ROOT,
                engine=process_views.engine,
            ),
        ),
        hil_callback=runtime.hil_callback,
        hil_registry=runtime.hil_registry,
        hil_decision_publisher=runtime.hil_decision_publisher,
        console_action=runtime.console_action,
        kill_switch_command=KillSwitchCommandService(store=state_store),
        iam_access=AccessRequestService(store=state_store),
        iam_directory=iam_directory,
        iam_identity_provider=iam_provider or "entra",
        iam_role_group_ids={
            "Reader": group_mapping.reader_group_id,
            "Contributor": group_mapping.contributor_group_id,
            "Approver": group_mapping.approver_group_id,
            "Owner": group_mapping.owner_group_id,
            "BreakGlass": group_mapping.break_glass_group_id,
        },
        human_assignments=AssignmentCaseService(store=state_store),
        handover_goals=HandoverGoalService(
            store=state_store,
            assignments=AssignmentCaseService(store=state_store),
        ),
        handover_availability_publisher=(
            EventBusHandoverAvailabilityPublisher(
                event_bus=runtime.event_bus,
                topic=runtime.event_topic,
            )
            if runtime.event_bus is not None and runtime.event_topic
            else None
        ),
        live_stream=runtime.live_stream,
        agent_activity=runtime.agent_activity,
        data_sources=build_production_data_sources(
            scope_configured=scope_source is not None,
            onboarding_configured=onboarding.configured,
            model_settings_configured=model_settings is not None,
            streams_configured=runtime.live_stream is not None,
        ),
        startup_callbacks=(
            read_model.verify_connection,
            *(
                (read_investigation_run_store.verify_schema,)
                if read_investigation_run_store is not None
                else ()
            ),
            *reader_startup_callbacks,
            _seed_catalog_semantic_index,
            *runtime.startup_callbacks,
            *((remote_agent_delegate.start,) if remote_agent_delegate is not None else ()),
            *stewardship_startup_callbacks,
        ),
        shutdown_callbacks=shutdown_callbacks,
    )
    application = build_app(authenticator=authenticator, read_model=read_model, config=config)
    application.state.skill_disclosure = skill_runtime.disclosure
    return application


def app() -> Starlette:
    """Factory form for ``uvicorn ... --factory``.

    Usage::

        uvicorn fdai.delivery.operator_api.prod:app --factory --host 0.0.0.0 --port 8000
    """
    return build_prod_app()


__all__ = [
    "ProdOperatorApiConfigError",
    "app",
    "build_prod_app",
    "build_prod_read_model",
]
