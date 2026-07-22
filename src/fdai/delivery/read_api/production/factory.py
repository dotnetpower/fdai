"""Production ASGI app factory for the console read API.

The upstream dev factory lives at
``src/fdai/delivery/read_api/dev/local.py`` and boots
:class:`~fdai.delivery.read_api.auth.UnsafeClaimsExtractor` +
:class:`~fdai.delivery.read_api.read_model.InMemoryConsoleReadModel`. That
harness is never a production surface (its build-time tripwire refuses to
boot outside ``FDAI_READ_API_DEV_MODE=1``).

This module is the counterpart: the fork's composition root serves it
with any ASGI server (``uvicorn fdai.delivery.read_api.prod:app``).
It composes the real production wiring from environment only:

- :class:`~fdai.delivery.read_api.entra_verifier.EntraJwtVerifier` for
  bearer-token validation (JWKS + audience + issuer + expiry);
- :class:`~fdai.core.rbac.resolver.GroupMapping` +
  :class:`~fdai.core.rbac.resolver.RoleResolver` for the ``roles`` claim
  or ``groups`` fallback;
- :class:`~fdai.delivery.read_api.postgres_read_model.PostgresConsoleReadModel`
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
  :class:`~fdai.delivery.read_api.entra_verifier.EntraJwtVerifier`.
- ``FDAI_RBAC_{READERS,CONTRIBUTORS,APPROVERS,OWNERS,BREAK_GLASS}_GROUP_ID``.

Optional (respect defaults):

- ``FDAI_ENTRA_ISSUER`` / ``FDAI_ENTRA_JWKS_URI`` - override tenant defaults.
- ``FDAI_READ_API_CORS_ALLOW_ORIGINS`` - comma-separated origin list.
  MUST NOT contain ``*`` outside dev; ``build_app`` fails fast if it does.
- ``FDAI_READ_API_STATEMENT_TIMEOUT_MS`` (default ``20000``).
- ``FDAI_READ_API_CONNECT_TIMEOUT_S`` (default ``10``).
- ``LLM_RESOLVED_MODELS_PATH`` - enables the Command Deck narrator from the
    resolver output using the Container App's managed identity.
- ``FDAI_INCIDENT_SLA_POLICY_JSON`` - enables the periodic incident SLA
    monitor. The JSON object defines positive integer ``acknowledge_seconds``
    and ``resolve_seconds`` values for every key from ``sev1`` through ``sev5``.
- ``FDAI_INCIDENT_SLA_INTERVAL_SECONDS`` (default ``60`` when the SLA policy
    is present) - positive scan interval. Ignored without the policy.
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
from fdai.core.rbac.access_request import AccessRequestService
from fdai.core.rbac.kill_switch_command import KillSwitchCommandService
from fdai.core.stewardship import load_stewardship_from_yaml
from fdai.delivery.event_bus_multiplex import MultiplexedEventBus
from fdai.delivery.persistence import (
    PostgresModelHealthTransitionSink,
    PostgresModelHealthTransitionSinkConfig,
    PostgresReadInvestigationRunStore,
    PostgresReadInvestigationRunStoreConfig,
)
from fdai.delivery.persistence.postgres_conversation_delivery import (
    PostgresConversationDeliveryStore,
    PostgresConversationDeliveryStoreConfig,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventoryGraphProvider,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_principal_binding import (
    PostgresPrincipalConversationBindingStore,
    PostgresPrincipalConversationBindingStoreConfig,
)
from fdai.delivery.persistence.postgres_scheduler_store import (
    PostgresScheduleStore,
    PostgresScheduleStoreConfig,
)
from fdai.delivery.persistence.postgres_task_worker import (
    PostgresTaskWorkerStore,
    PostgresTaskWorkerStoreConfig,
)
from fdai.delivery.persistence.postgres_vm_task import (
    PostgresPythonTaskArtifactStore,
    PostgresVmTaskConfig,
    PostgresVmTaskTargetResolver,
)
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.production import env_contract as _env
from fdai.delivery.read_api.production.config import (
    ProdReadApiConfigError,
    _check_required_env,
    _parse_cors_origins,
    _parse_positive_int,
    build_prod_read_model,
)
from fdai.delivery.read_api.production.data_sources import build_production_data_sources
from fdai.delivery.read_api.production.identity import build_production_identity
from fdai.delivery.read_api.production.onboarding import build_production_onboarding
from fdai.delivery.read_api.production.panels import build_production_panels
from fdai.delivery.read_api.production.persistence import build_production_persistence
from fdai.delivery.read_api.production.runtime_wiring import build_production_runtime
from fdai.delivery.read_api.production.scope import build_production_scope_source
from fdai.delivery.read_api.production.skill_sources import build_production_skill_sources
from fdai.delivery.read_api.production.skills import build_production_skill_runtime
from fdai.delivery.read_api.production.user_context import build_production_user_context
from fdai.delivery.read_api.production.views import _build_dynamic_views
from fdai.delivery.read_api.routes.arb_status import ArchitectureReviewStatusPanel
from fdai.delivery.read_api.routes.background_runtime import build_background_task_runtime
from fdai.delivery.read_api.routes.busy_input_runtime import build_postgres_busy_input_runtime
from fdai.delivery.read_api.routes.chat import backend_from_env
from fdai.delivery.read_api.routes.chat_web_search import chat_web_search_from_env
from fdai.delivery.read_api.routes.post_turn_event_bus import EventBusPostTurnReviewIntake
from fdai.delivery.read_api.routes.post_turn_review import PostTurnReviewQueue
from fdai.delivery.read_api.routes.python_tasks import (
    PythonTaskRoutesConfig,
    PythonTaskRunSubmitter,
)
from fdai.delivery.stewardship import (
    HumanIdentityLivenessDirectory,
    StewardshipHealthMonitor,
)
from fdai.shared.providers.local import EnvSecretProvider

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[5]

# psycopg 3 (the driver this repo ships) accepts either the bare
# ``postgresql://`` scheme or the SQLAlchemy-style ``postgresql+psycopg://``
# alias. Any other ``+<driver>`` suffix (e.g. ``+asyncpg``, ``+psycopg2``)
# is a caller mistake - the connection would fail with a cryptic driver
# error deep inside psycopg. Reject explicitly at boot with a clear
# ProdReadApiConfigError instead.
_RBAC_ENV: Final[Mapping[str, str]] = {
    "readers": "FDAI_RBAC_READERS_GROUP_ID",
    "contributors": "FDAI_RBAC_CONTRIBUTORS_GROUP_ID",
    "approvers": "FDAI_RBAC_APPROVERS_GROUP_ID",
    "owners": "FDAI_RBAC_OWNERS_GROUP_ID",
    "break_glass": "FDAI_RBAC_BREAK_GLASS_GROUP_ID",
}


def build_prod_app(environ: Mapping[str, str] | None = None) -> Starlette:
    """Assemble the production ASGI app from environment only.

    - Refuses to boot when any required env var is missing
      (:class:`ProdReadApiConfigError`).
    - Wires the production :class:`EntraJwtVerifier` (JWKS + ``aud`` +
      ``iss`` + ``exp``) - never the dev-mode
      :class:`~fdai.delivery.read_api.auth.UnsafeClaimsExtractor`.
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
    identity = build_production_identity(env)
    authenticator = identity.authenticator
    group_mapping = identity.group_mapping
    iam_directory = identity.iam_directory
    iam_provider = identity.iam_provider
    shutdown_callbacks = identity.shutdown_callbacks
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
            raise ProdReadApiConfigError(
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
    from fdai.delivery.vm_task import PlanningVmTaskRunner

    vm_task_store_config = PostgresVmTaskConfig(
        dsn=read_model._config.dsn,
        statement_timeout_ms=read_model._config.statement_timeout_ms,
        connect_timeout_s=read_model._config.connect_timeout_s,
    )
    task_author = None
    author_endpoint = env.get(_env.PYTHON_TASK_AUTHOR_ENDPOINT_ENV, "").strip()
    author_deployment = env.get(_env.PYTHON_TASK_AUTHOR_DEPLOYMENT_ENV, "").strip()
    if bool(author_endpoint) != bool(author_deployment):
        raise ProdReadApiConfigError(
            f"{_env.PYTHON_TASK_AUTHOR_ENDPOINT_ENV} and "
            f"{_env.PYTHON_TASK_AUTHOR_DEPLOYMENT_ENV} MUST be configured together"
        )
    if author_endpoint:
        from fdai.delivery.azure.llm.python_task_author import (
            AzureOpenAIPythonTaskAuthor,
            AzureOpenAIPythonTaskAuthorConfig,
        )
        from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity

        author_http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=60.0, write=15.0, pool=5.0)
        )
        task_author = AzureOpenAIPythonTaskAuthor(
            identity=ManagedIdentityWorkloadIdentity(http_client=author_http),
            http_client=author_http,
            config=AzureOpenAIPythonTaskAuthorConfig(
                endpoint=author_endpoint,
                deployment=author_deployment,
            ),
        )

        async def _close_task_author_http() -> None:
            await author_http.aclose()

        shutdown_callbacks = (*shutdown_callbacks, _close_task_author_http)
    python_tasks = PythonTaskRoutesConfig(
        artifacts=PostgresPythonTaskArtifactStore(config=vm_task_store_config),
        targets=PostgresVmTaskTargetResolver(config=vm_task_store_config),
        runner=PlanningVmTaskRunner(),
        submitter=(
            PythonTaskRunSubmitter(event_bus=runtime.event_bus, topic=runtime.event_topic)
            if runtime.event_bus is not None and runtime.event_topic
            else None
        ),
        schedule_store=PostgresScheduleStore(
            config=PostgresScheduleStoreConfig(
                dsn=read_model._config.dsn,
                statement_timeout_ms=read_model._config.statement_timeout_ms,
                connect_timeout_s=read_model._config.connect_timeout_s,
            )
        ),
        workflows=workflows,
        author=task_author,
    )
    onboarding = build_production_onboarding(
        env=env,
        shutdown_callbacks=shutdown_callbacks,
    )
    shutdown_callbacks = onboarding.shutdown_callbacks
    scope_source = build_production_scope_source(env)
    chat = None
    chat_web_search = None
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
        from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
        from fdai.delivery.persistence import PostgresMeteringStore, PostgresMeteringStoreConfig

        chat_http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=90.0, write=15.0, pool=5.0)
        )
        chat_identity = (
            ManagedIdentityWorkloadIdentity(http_client=chat_http) if resolved_models_path else None
        )
        chat = backend_from_env(
            dict(env),
            identity=chat_identity,
            http_client=chat_http,
            metering_sink=PostgresMeteringStore(
                config=PostgresMeteringStoreConfig(
                    dsn=read_model._config.dsn,
                    statement_timeout_ms=read_model._config.statement_timeout_ms,
                    connect_timeout_s=read_model._config.connect_timeout_s,
                )
            ),
        )
        chat_web_search = chat_web_search_from_env(
            env,
            identity=chat_identity,
            http_client=chat_http,
        )

        async def _close_chat_http() -> None:
            await chat_http.aclose()

        shutdown_callbacks = (*shutdown_callbacks, _close_chat_http)
    model_settings = None
    if resolved_models_path:
        from fdai.delivery.read_api.routes.model_settings import ModelSettingsService

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
    reader_scope_ref = None
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
            AzureReadRestConfig,
            AzureReadScopeBinding,
            AzureRestReadInvestigationAdapter,
            AzureRestReadTransport,
        )
        from fdai.delivery.azure.subscription_health import (
            AzureSubscriptionHealthConfig,
            AzureSubscriptionHealthProvider,
        )
        from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
        from fdai.delivery.persistence import StateStoreReadLatencyProfileStore
        from fdai.delivery.read_api.routes.background_executor import (
            ReadInvestigationBackgroundTaskExecutor,
            ServerOwnedReadInvestigationRequestFactory,
        )
        from fdai.delivery.read_api.routes.read_investigations import (
            ReadInvestigationRunLedgerConfig,
        )

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
                    ("Microsoft.Network/networkSecurityGroups", "network.nsg"),
                    ("Microsoft.Network/virtualNetworks", "network.vnet"),
                ),
            ),
            identity=reader_identity,
            http_client=reader_http,
        )
        read_latency_store = StateStoreReadLatencyProfileStore(store=state_store)
        read_investigation_service = ReadInvestigationService(
            AzureRestReadInvestigationAdapter(reader_transport),
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
            await reader_http.aclose()

        shutdown_callbacks = (*shutdown_callbacks, _close_reader_http)
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
        from fdai.delivery.read_api.routes.read_investigation_responder import (
            HeimdallReadInvestigationChatDelegate,
            HeimdallReadInvestigationResponder,
        )
        from fdai.delivery.read_api.routes.read_investigations import (
            IdempotentReadInvestigationExecutor,
            ReadInvestigationRoutesConfig,
        )

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
                policy=read_investigation_routes.execution_policy,
            )
        )
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
        raise ProdReadApiConfigError(
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
    config = ReadApiConfig(
        dev_mode=False,
        cors_allow_origins=cors_origins,
        ontology_object_types=object_types,
        ontology_link_types=link_types,
        ontology_action_types=action_types,
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
        subscription_health_provider=subscription_health_provider,
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
        python_tasks=python_tasks,
        chat=chat,
        chat_agent_delegate=read_investigation_chat_delegate,
        skill_disclosure=skill_runtime.disclosure,
        skill_sources=skill_sources.routes,
        busy_input_runtime=busy_input_runtime,
        conversation_delivery_store=conversation_delivery_store,
        chat_web_search=chat_web_search,
        chat_probe_interval_seconds=_parse_positive_int(
            env,
            "FDAI_NARRATOR_PROBE_INTERVAL_SECONDS",
            300,
        ),
        conversation_history_store=conversation_history_store,
        conversation_search=user_context.conversation_search,
        conversation_policy_store=conversation_policy_store,
        user_context_ontology_projector=user_context_ontology_projector,
        post_turn_review_submitter=post_turn_review_queue,
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
            *runtime.startup_callbacks,
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

        uvicorn fdai.delivery.read_api.prod:app --factory --host 0.0.0.0 --port 8000
    """
    return build_prod_app()


__all__ = [
    "ProdReadApiConfigError",
    "app",
    "build_prod_app",
    "build_prod_read_model",
]
