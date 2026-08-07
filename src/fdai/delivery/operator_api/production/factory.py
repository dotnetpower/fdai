"""Production ASGI app factory for the console Operator API.

The upstream dev factory lives at
``src/fdai/delivery/operator_api/dev/local.py`` and boots
:class:`~fdai.delivery.auth.UnsafeClaimsExtractor` +
:class:`~fdai.delivery.operator_api.read_model.InMemoryConsoleReadModel`. That
harness is never a production surface (its build-time tripwire refuses to
boot outside ``FDAI_OPERATOR_API_DEV_MODE=1``).

This module is the counterpart: the fork's composition root serves it
with any ASGI server (``uvicorn fdai.delivery.operator_api.prod:app``).
It composes the real production wiring from environment only:

- :class:`~fdai.delivery.auth.EntraJwtVerifier` for
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
    :class:`~fdai.delivery.auth.EntraJwtVerifier`.
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
from fdai.core.metering.budget import InMemoryBudgetLedger, ModelBudget
from fdai.core.stewardship import load_stewardship_from_yaml
from fdai.delivery.event_bus_multiplex import MultiplexedEventBus
from fdai.delivery.operator_api.application.conversation.capabilities.inventory import (
    EmbeddingInventorySemanticResolver,
    inventory_query_function_type,
)
from fdai.delivery.operator_api.main import build_app
from fdai.delivery.operator_api.production import env_contract as _env
from fdai.delivery.operator_api.production.catalog_search import (
    ProductionCatalogSearch,
    build_production_catalog_search,
    catalog_query_function_type,
)
from fdai.delivery.operator_api.production.config import (
    ProdOperatorApiConfigError,
    _check_required_env,
    _parse_cors_origins,
    _parse_positive_int,
    build_prod_read_model,
)
from fdai.delivery.operator_api.production.identity import build_production_identity
from fdai.delivery.operator_api.production.knowledge_context import (
    build_production_knowledge_context,
)
from fdai.delivery.operator_api.production.onboarding import build_production_onboarding
from fdai.delivery.operator_api.production.operator_config import (
    ProductionOperatorConfigInputs,
    build_production_operator_config,
)
from fdai.delivery.operator_api.production.persistence import build_production_persistence
from fdai.delivery.operator_api.production.python_tasks import build_production_python_tasks
from fdai.delivery.operator_api.production.read_investigation import (
    build_production_read_investigation,
)
from fdai.delivery.operator_api.production.runtime_wiring import build_production_runtime
from fdai.delivery.operator_api.production.scope import build_production_scope_source
from fdai.delivery.operator_api.production.skill_sources import build_production_skill_sources
from fdai.delivery.operator_api.production.skills import build_production_skill_runtime
from fdai.delivery.operator_api.production.user_context import build_production_user_context
from fdai.delivery.operator_api.production.views import _build_dynamic_views
from fdai.delivery.operator_api.routes.busy_input_runtime import build_postgres_busy_input_runtime
from fdai.delivery.operator_api.routes.chat import backend_from_env
from fdai.delivery.operator_api.routes.chat_web_search import chat_web_search_from_env
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
from fdai.delivery.persistence.postgres_principal_binding import (
    PostgresPrincipalConversationBindingStore,
    PostgresPrincipalConversationBindingStoreConfig,
)
from fdai.delivery.stewardship import (
    HumanIdentityLivenessDirectory,
    StewardshipHealthMonitor,
)
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
    :class:`~fdai.delivery.auth.UnsafeClaimsExtractor`.
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
    from fdai.delivery.kubernetes.ontology_functions import diagnostic_function_types

    ontology_function_types = (
        inventory_query_function_type(),
        catalog_query_function_type(),
        *diagnostic_function_types(),
    )
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
    user_context = user_context_group.routes
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
    read_investigation = build_production_read_investigation(
        env=env,
        repo_root=_REPO_ROOT,
        read_model=read_model,
        state_store=state_store,
        conversation_history_store=conversation_history_store,
        background_outbound_delivery=background_outbound_delivery,
        principal_binding_store=principal_binding_store,
        event_bus=runtime.event_bus,
        shutdown_callbacks=shutdown_callbacks,
    )
    shutdown_callbacks = read_investigation.shutdown_callbacks
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
    config = build_production_operator_config(
        ProductionOperatorConfigInputs(
            env=env,
            repo_root=_REPO_ROOT,
            read_model=read_model,
            state_store=state_store,
            cors_origins=cors_origins,
            object_types=object_types,
            link_types=link_types,
            action_types=action_types,
            ontology_function_types=ontology_function_types,
            ontology_release=ontology_release,
            inventory_semantic_resolver=inventory_semantic_resolver,
            catalog_semantic_index=catalog_semantic_index,
            scope_source=scope_source,
            log_query_provider=log_query_provider,
            reporting=reporting,
            process_views=process_views,
            workflow_authoring=workflow_authoring,
            workflow_execution=workflow_execution,
            stewardship_map=stewardship_map,
            stewardship_startup_callbacks=stewardship_startup_callbacks,
            user_context_group=user_context_group,
            model_settings=model_settings,
            runtime_settings=runtime_settings,
            python_tasks=python_tasks,
            chat=chat,
            metering_sink=metering_sink,
            skill_runtime=skill_runtime,
            skill_sources=skill_sources,
            knowledge_context=knowledge_context,
            read_investigation=read_investigation,
            busy_input_runtime=busy_input_runtime,
            conversation_delivery_store=conversation_delivery_store,
            chat_web_search=chat_web_search,
            assurance_ledger=assurance_ledger,
            assurance_policy_runtime=assurance_policy_runtime,
            assurance_submitter=assurance_submitter,
            runtime=runtime,
            onboarding=onboarding,
            identity=identity,
            shutdown_callbacks=shutdown_callbacks,
        )
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
