"""Azure-backed local entrypoint for the console Operator API.

The interactive factory requires the current Azure CLI identity and never
seeds runtime evidence. Repository catalogs remain available as reference
data; Azure runtime panels stay empty or unavailable until their authoritative
Azure data-plane adapters are configured.

**Never wire this in production.** The env-var tripwire in
:func:`fdai.delivery.operator_api.main.build_app` refuses to build a
dev-mode app unless ``FDAI_OPERATOR_API_DEV_MODE=1`` is set - this
module also asserts that at build time so a stray production revision
that boots it fails fast.

Usage (uvicorn's ``--factory`` flag calls :func:`app` at server start,
so importing this module during unrelated tooling - pytest collection,
mypy, IDE indexing - has no side effect)::

    FDAI_OPERATOR_API_LOCAL_AZURE_CLI=1 \
        uv run uvicorn 'fdai.delivery.operator_api.dev.local:app' \
            --factory --port 8000

Synthetic composition is available only through the explicit
``test_fixtures=True`` argument used by pytest integration tests.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import httpx
from starlette.applications import Starlette

# Dev harness: make our own INFO logs visible so live-stream open/close
# events show up alongside uvicorn's access log.
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")

from fdai.agents import OWNED_OBJECT_TOPICS  # noqa: E402
from fdai.core.audit.what_if_replay import WhatIfEvaluator  # noqa: E402
from fdai.core.conversation_assurance import (  # noqa: E402
    HoldingOntologyAdequacyInvestigator,
    InMemoryConversationAssuranceLedger,
)
from fdai.core.metering import (  # noqa: E402
    InMemoryMeteringSink,
)
from fdai.core.onboarding import EmptyResourceProbe  # noqa: E402
from fdai.core.rbac.resolver import RoleResolver  # noqa: E402
from fdai.delivery.auth import (  # noqa: E402  # noqa: E402
    EntraJwtVerifier,
    UnsafeClaimsExtractor,
    build_authenticator,
)
from fdai.delivery.event_bus_multiplex import MultiplexedEventBus  # noqa: E402
from fdai.delivery.operator_api.app.authoritative_proxy import (  # noqa: E402
    AUTHORITATIVE_OPERATOR_API_ENV,
    authoritative_read_proxy_from_env,
)
from fdai.delivery.operator_api.application.conversation.capabilities.knowledge_context import (  # noqa: E402
    KnowledgeContextChatTools,
)
from fdai.delivery.operator_api.dev.app_config import (  # noqa: E402
    LocalAppConfigDependencies,
    build_local_operator_api_config,
)
from fdai.delivery.operator_api.dev.azure_cli_identity import (  # noqa: E402
    resolve_azure_cli_identity,
)
from fdai.delivery.operator_api.dev.command_transport import (  # noqa: E402
    build_local_command_transport,
)
from fdai.delivery.operator_api.dev.config import (  # noqa: E402
    cors_origins_from_env as _cors_origins_from_env,
)
from fdai.delivery.operator_api.dev.config import (  # noqa: E402
    entra_application_id_from_env,
    local_entra_verifier_environment,
)
from fdai.delivery.operator_api.dev.config import (  # noqa: E402
    group_mapping_from_env as _group_mapping_from_env,
)
from fdai.delivery.operator_api.dev.data_sources import build_local_data_sources  # noqa: E402
from fdai.delivery.operator_api.dev.fixtures.dynamic_views import (  # noqa: E402
    _build_scope_view,
    _DemoTighterTagsEvaluator,
)
from fdai.delivery.operator_api.dev.fixtures.seed_data import (  # noqa: E402
    _seed,
    _synthetic_llm_invocations,
)
from fdai.delivery.operator_api.dev.helpers import (  # noqa: E402
    build_agent_streams as _build_agent_streams,
)
from fdai.delivery.operator_api.dev.helpers import (  # noqa: E402
    build_chat_backend as _build_chat_backend,
)
from fdai.delivery.operator_api.dev.helpers import (  # noqa: E402
    build_chat_web_search as _build_chat_web_search,
)
from fdai.delivery.operator_api.dev.helpers import (  # noqa: E402
    build_inventory_graph_provider as _build_inventory_graph_provider,
)
from fdai.delivery.operator_api.dev.helpers import (  # noqa: E402
    build_kubernetes_workload_provider as _build_kubernetes_workload_provider,
)
from fdai.delivery.operator_api.dev.helpers import (  # noqa: E402
    build_live_stream_config as _build_live_stream_config,
)
from fdai.delivery.operator_api.dev.helpers import (  # noqa: E402
    build_stewardship_map as _build_stewardship_map,
)
from fdai.delivery.operator_api.dev.helpers import (  # noqa: E402
    chat_probe_interval_seconds as _chat_probe_interval_seconds,
)
from fdai.delivery.operator_api.dev.iam_directory import (  # noqa: E402
    build_local_iam_directory,
)
from fdai.delivery.operator_api.dev.incident_store import (  # noqa: E402
    ProjectingIncidentStateStore,
)
from fdai.delivery.operator_api.dev.model_wiring import build_local_model_wiring  # noqa: E402
from fdai.delivery.operator_api.dev.read_investigation import (  # noqa: E402
    build_local_read_investigation,
)
from fdai.delivery.operator_api.dev.runtime_wiring import (  # noqa: E402
    build_interactive_pantheon_wiring,
    build_local_runtime_wiring,
)
from fdai.delivery.operator_api.dev.view_wiring import build_local_view_wiring  # noqa: E402
from fdai.delivery.operator_api.main import build_app  # noqa: E402
from fdai.delivery.operator_api.postgres_read_model import PostgresConsoleReadModel  # noqa: E402
from fdai.delivery.operator_api.production.config import build_prod_read_model  # noqa: E402
from fdai.delivery.operator_api.production.knowledge_context import (  # noqa: E402
    build_production_knowledge_context,
)
from fdai.delivery.operator_api.production.panels import build_production_panels  # noqa: E402
from fdai.delivery.operator_api.production.persistence import (  # noqa: E402
    build_production_persistence,
)
from fdai.delivery.operator_api.production.scope import build_production_scope_source  # noqa: E402
from fdai.delivery.operator_api.production.user_context import (  # noqa: E402
    build_production_user_context,
)
from fdai.delivery.operator_api.production.views import _build_dynamic_views  # noqa: E402
from fdai.delivery.operator_api.read_model import (  # noqa: E402
    ConsoleReadModel,
    InMemoryConsoleReadModel,
)
from fdai.delivery.operator_api.routes.chat_agent_delegate import (  # noqa: E402
    PantheonChatDelegate,
)
from fdai.delivery.operator_api.routes.conversation_assurance_intake import (  # noqa: E402
    ConversationAssurancePostTurnSubmitter,
)
from fdai.delivery.operator_api.routes.demo_inventory_graph import (  # noqa: E402
    demo_inventory_graph_provider,
)
from fdai.delivery.operator_api.routes.panels import ReadPanel  # noqa: E402
from fdai.delivery.operator_api.routes.post_turn_event_bus import (  # noqa: E402
    EventBusPostTurnReviewIntake,
)
from fdai.delivery.operator_api.routes.post_turn_review import PostTurnReviewQueue  # noqa: E402
from fdai.delivery.operator_api.routes.rule_fire_trace_reader import (  # noqa: E402
    ConsoleReadModelTraceReader,
)
from fdai.delivery.operator_api.routes.skill_runtime import (  # noqa: E402
    empty_runtime_skill_disclosure,
)
from fdai.delivery.operator_api.streaming.agent_activity_stream import (  # noqa: E402
    SseAgentActivityPublisher,
    runtime_agent_state_snapshot,
)
from fdai.delivery.operator_api.streaming.pantheon_activity_observer import (  # noqa: E402
    PantheonActivityObserver,
)
from fdai.delivery.persistence import (  # noqa: E402
    PostgresConversationAssuranceLedger,
    PostgresConversationAssuranceLedgerConfig,
    PostgresMeteringStore,
    PostgresMeteringStoreConfig,
    StateStoreOntologyAdequacyReviewSink,
)
from fdai.delivery.persistence.postgres_conversation_assurance_runtime import (  # noqa: E402
    PostgresConversationPolicyRuntime,
    PostgresConversationPolicyRuntimeConfig,
)
from fdai.delivery.persistence.postgres_conversation_delivery import (  # noqa: E402
    PostgresConversationDeliveryStore,
    PostgresConversationDeliveryStoreConfig,
)
from fdai.delivery.persistence.postgres_read_investigation_run import (  # noqa: E402
    PostgresReadInvestigationRunStore,
    PostgresReadInvestigationRunStoreConfig,
)
from fdai.runtime.conversation_assurance import (  # noqa: E402
    build_conversation_assurance_coordinator,
)
from fdai.shared.config.runtime_flags import pantheon_start_enabled  # noqa: E402

_DEV_ENV = "FDAI_OPERATOR_API_DEV_MODE"
_LOCAL_ENTRA_ENV = "FDAI_OPERATOR_API_LOCAL_ENTRA"
_EMBED_PANTHEON_ENV = "FDAI_OPERATOR_API_EMBED_PANTHEON"
_LOCAL_AZURE_CLI_ENV = "FDAI_OPERATOR_API_LOCAL_AZURE_CLI"
_LOCAL_ACTION_TOPIC = "aw.events"
# local.py lives at src/fdai/delivery/operator_api/dev/local.py, so the repo root
# is six levels up (parents[5]): dev -> operator_api -> delivery -> fdai -> src ->
# repo root. This was parents[4] before the module moved into dev/ (bc11c981);
# an index off by one made _REPO_ROOT resolve to src/ and every catalog-backed
# route (ontology, rules, promotion-gates, workflows) 404 with empty catalogs.
_REPO_ROOT = Path(__file__).resolve().parents[5]
_LifecycleCallback = Callable[[], Awaitable[None]]

# One seed audit row: (agent, tier, action_kind, outcome, finished_hhmmss,
# correlation, summary, detail, work_ms, inputs, outputs).


def _inventory_lifecycle_callbacks(
    provider: Any,
) -> tuple[tuple[_LifecycleCallback, ...], tuple[_LifecycleCallback, ...]]:
    warmup = getattr(provider, "start_warmup", None)
    close = getattr(provider, "close", None)
    startup = (cast(_LifecycleCallback, warmup),) if callable(warmup) else ()
    shutdown = (cast(_LifecycleCallback, close),) if callable(close) else ()
    return startup, shutdown


def _build_local_metering(
    *,
    read_model: ConsoleReadModel,
    local_database_configured: bool,
    test_fixtures: bool,
) -> Any:
    if local_database_configured and not test_fixtures:
        postgres_read_model = cast(PostgresConsoleReadModel, read_model)
        return PostgresMeteringStore(
            config=PostgresMeteringStoreConfig(
                dsn=postgres_read_model._config.dsn,
                statement_timeout_ms=postgres_read_model._config.statement_timeout_ms,
                connect_timeout_s=postgres_read_model._config.connect_timeout_s,
            )
        )
    return InMemoryMeteringSink(
        initial=_synthetic_llm_invocations() if test_fixtures else (),
    )


def build_local_app(
    *,
    identity_resolver: Callable[[], Any] = resolve_azure_cli_identity,
    test_fixtures: bool = False,
) -> Starlette:
    """Factory. uvicorn invokes this once at server start with ``--factory``."""
    dev_mode = os.environ.get(_DEV_ENV) == "1"
    local_entra = os.environ.get(_LOCAL_ENTRA_ENV) == "1"
    local_azure_cli = os.environ.get(_LOCAL_AZURE_CLI_ENV) == "1"
    if test_fixtures and "PYTEST_CURRENT_TEST" not in os.environ:
        raise RuntimeError("synthetic local fixtures are pytest-only")
    if not test_fixtures and (dev_mode or not (local_entra or local_azure_cli)):
        raise RuntimeError(
            "interactive local Operator API requires FDAI_OPERATOR_API_LOCAL_ENTRA=1 or "
            "FDAI_OPERATOR_API_LOCAL_AZURE_CLI=1; dev-mode and synthetic fallback are test-only"
        )
    if not test_fixtures and os.environ.get("FDAI_LOCAL_SCENARIO_REPLAY", "").strip() == "1":
        raise RuntimeError("interactive local scenario replay is not supported; use Azure evidence")
    if local_azure_cli and (dev_mode or local_entra):
        raise RuntimeError(
            f"{_LOCAL_AZURE_CLI_ENV} MUST NOT be combined with {_DEV_ENV} or {_LOCAL_ENTRA_ENV}"
        )
    if not dev_mode and not local_entra and not local_azure_cli:
        raise RuntimeError(
            f"fdai.delivery.operator_api.dev.local requires {_DEV_ENV}=1 (auth bypassed) "
            f"or {_LOCAL_ENTRA_ENV}=1 (real Entra sign-in with Azure-backed providers) or "
            f"{_LOCAL_AZURE_CLI_ENV}=1 (current az login user); this module is a "
            "local dev entrypoint and MUST NOT boot in production."
        )
    local_database_configured = bool(os.environ.get("FDAI_DATABASE_URL", "").strip())
    authoritative_proxy_configured = bool(
        os.environ.get(AUTHORITATIVE_OPERATOR_API_ENV, "").strip()
    )
    if local_database_configured and authoritative_proxy_configured:
        raise RuntimeError(
            "FDAI_DATABASE_URL and FDAI_AUTHORITATIVE_OPERATOR_API_BASE_URL "
            "MUST NOT be configured together"
        )
    local_cli_identity = identity_resolver() if local_azure_cli else None
    authoritative_read_proxy = (
        None if test_fixtures else authoritative_read_proxy_from_env(os.environ)
    )
    read_model: ConsoleReadModel
    if local_database_configured and not test_fixtures:
        read_model = build_prod_read_model(os.environ)
    else:
        in_memory_read_model = InMemoryConsoleReadModel()
        read_model = in_memory_read_model
        if test_fixtures:
            _seed(in_memory_read_model)
    group_mapping = _group_mapping_from_env()
    resolver = RoleResolver(group_mapping=group_mapping)
    # dev_mode (auth off) wins when both flags are set. Otherwise this is the
    # local real-login harness: verify genuine Entra access tokens against the
    # tenant JWKS (FDAI_ENTRA_TENANT_ID + FDAI_API_AUDIENCE required) while the
    # console still renders the in-memory seed above - so an engineer can drive
    # the full MSAL sign-in + App-Role gate locally without a live audit store.
    if dev_mode or local_azure_cli:
        authenticator = build_authenticator(
            verifier=UnsafeClaimsExtractor(),
            resolver=resolver,
        )
    else:
        authenticator = build_authenticator(
            verifier=EntraJwtVerifier.from_env(local_entra_verifier_environment()),
            resolver=resolver,
        )

    iam = build_local_iam_directory(
        group_mapping,
        use_graph=local_entra or local_azure_cli,
        application_id=entra_application_id_from_env(),
    )

    enforce_workflows = frozenset(
        item.strip()
        for item in os.environ.get("FDAI_WORKFLOW_ENFORCE_ALLOWLIST", "").split(",")
        if item.strip()
    )
    views = build_local_view_wiring(
        repo_root=_REPO_ROOT,
        read_model=read_model,
        include_test_fixtures=test_fixtures,
        promoted_workflows=enforce_workflows,
    )
    catalog = views.catalog
    ontology_object_types = catalog.object_types
    ontology_link_types = catalog.link_types
    action_types = catalog.action_types
    best_practice_controls = catalog.best_practices
    rule_catalog_rules = catalog.rules
    rule_catalog_collected = catalog.collected_rules
    policies_root = catalog.policies_root
    remediation_root = catalog.remediation_root
    rule_catalog_findings_provider = catalog.findings_provider
    rule_catalog_findings_summary_provider = catalog.findings_summary_provider
    built_in_workflows = catalog.workflows
    workflow_authoring = catalog.workflow_authoring

    trace_reader = ConsoleReadModelTraceReader(read_model)
    what_if_evaluators: dict[str, WhatIfEvaluator] = {
        "tighter-tags": _DemoTighterTagsEvaluator(),
    }

    reporting = views.reporting if test_fixtures else None
    process_views = views.process_views
    workflow_execution = views.workflow_execution
    scope_source = _build_scope_view() if test_fixtures else None
    conversation_delivery_store = None
    persistence = None
    postgres_read_model: PostgresConsoleReadModel | None = None
    durable_panels: tuple[ReadPanel, ...] = ()
    if local_database_configured and not test_fixtures:
        postgres_read_model = cast(PostgresConsoleReadModel, read_model)
        persistence = build_production_persistence(postgres_read_model)
        (
            reporting,
            process_views,
            _production_object_types,
            _production_link_types,
            _production_action_types,
            _production_workflows,
            _production_workflow_authoring,
            workflow_execution,
        ) = _build_dynamic_views(
            dsn=postgres_read_model._config.dsn,
            statement_timeout_ms=postgres_read_model._config.statement_timeout_ms,
            connect_timeout_s=postgres_read_model._config.connect_timeout_s,
            read_model=postgres_read_model,
            group_mapping=group_mapping,
        )
        production_user_context = build_production_user_context(
            read_model=postgres_read_model,
            object_types=ontology_object_types,
            link_types=ontology_link_types,
            action_types=action_types,
            workflows=built_in_workflows,
            promoted_workflows=enforce_workflows,
        )
        conversation_history_store = production_user_context.conversation_history_store
        conversation_policy_store = production_user_context.conversation_policy_store
        user_context_ontology_projector = production_user_context.ontology_projector
        user_context = production_user_context.routes
        workflow_definitions = production_user_context.workflow_definitions
        user_context_startup_callbacks = production_user_context.startup_callbacks
        durable_panels = cast(
            tuple[ReadPanel, ...],
            build_production_panels(
                read_model=postgres_read_model,
                onboarding_probe=EmptyResourceProbe(),
                onboarding_configured=False,
                state_store=persistence.state_store,
                action_types=tuple(action_types),
                active_rule_count=len(rule_catalog_rules),
            ),
        )
        conversation_delivery_store = PostgresConversationDeliveryStore(
            config=PostgresConversationDeliveryStoreConfig(
                dsn=postgres_read_model._config.dsn,
                statement_timeout_ms=postgres_read_model._config.statement_timeout_ms,
                connect_timeout_s=postgres_read_model._config.connect_timeout_s,
            )
        )
        scope_source = build_production_scope_source(os.environ)
    else:
        user_context_group = views.user_context
        conversation_history_store = user_context_group.conversation_history_store
        conversation_policy_store = user_context_group.conversation_policy_store
        user_context_ontology_projector = user_context_group.ontology_projector
        user_context = user_context_group.routes
        workflow_definitions = user_context_group.workflow_definitions
        user_context_startup_callbacks = (user_context_group.seed_callback,)

    assurance_ledger = (
        PostgresConversationAssuranceLedger(
            config=PostgresConversationAssuranceLedgerConfig(
                dsn=cast(PostgresConsoleReadModel, read_model)._config.dsn,
                statement_timeout_ms=cast(
                    PostgresConsoleReadModel, read_model
                )._config.statement_timeout_ms,
                connect_timeout_s=cast(
                    PostgresConsoleReadModel, read_model
                )._config.connect_timeout_s,
            )
        )
        if local_database_configured and not test_fixtures
        else InMemoryConversationAssuranceLedger()
    )
    assurance_policy_runtime = (
        PostgresConversationPolicyRuntime(
            config=PostgresConversationPolicyRuntimeConfig(
                dsn=cast(PostgresConsoleReadModel, read_model)._config.dsn,
                statement_timeout_ms=cast(
                    PostgresConsoleReadModel, read_model
                )._config.statement_timeout_ms,
                connect_timeout_s=cast(
                    PostgresConsoleReadModel, read_model
                )._config.connect_timeout_s,
            )
        )
        if local_database_configured and not test_fixtures
        else None
    )

    local_read_investigation = (
        build_local_read_investigation(
            state_store=persistence.state_store,
            run_store=PostgresReadInvestigationRunStore(
                config=PostgresReadInvestigationRunStoreConfig(
                    dsn=cast(PostgresConsoleReadModel, read_model)._config.dsn,
                    statement_timeout_ms=cast(
                        PostgresConsoleReadModel, read_model
                    )._config.statement_timeout_ms,
                    connect_timeout_s=cast(
                        PostgresConsoleReadModel, read_model
                    )._config.connect_timeout_s,
                )
            ),
            environ=os.environ,
        )
        if persistence is not None and not test_fixtures
        else None
    )

    command_transport = (
        None
        if test_fixtures or not pantheon_start_enabled(os.environ)
        else build_local_command_transport(
            read_model=read_model,
            action_types=tuple(action_types),
            state_store=(
                persistence.state_store
                if persistence is not None
                else ProjectingIncidentStateStore(
                    read_model=cast(InMemoryConsoleReadModel, read_model)
                )
            ),
        )
    )
    remote_agent_delegate = None
    if enforce_workflows and command_transport is not None and command_transport.kind != "azure":
        raise RuntimeError("FDAI_WORKFLOW_ENFORCE_ALLOWLIST requires local Azure event transport")
    if enforce_workflows and persistence is None and not test_fixtures:
        raise RuntimeError("FDAI_WORKFLOW_ENFORCE_ALLOWLIST requires a durable local database")
    if workflow_execution is not None and command_transport is not None:
        workflow_execution = replace(
            workflow_execution,
            orchestrator=workflow_execution.orchestrator.with_action_dispatcher(
                command_transport.action_dispatcher
            ),
            enforce_workflows=enforce_workflows,
        )
    elif enforce_workflows and not test_fixtures:
        raise RuntimeError("FDAI_WORKFLOW_ENFORCE_ALLOWLIST requires local Azure event transport")

    live_stream_config = command_transport.live_stream if command_transport is not None else None
    agent_activity_config = (
        command_transport.agent_activity if command_transport is not None else None
    )
    from fdai.delivery.runtime_settings import RuntimeSettingsService

    startup_runtime_values = RuntimeSettingsService(
        store=None,
        env=os.environ,
    ).environment_values()
    runtime = None
    post_turn_review_queue = None
    embed_pantheon = os.environ.get(_EMBED_PANTHEON_ENV, "").strip().casefold() not in {
        "0",
        "false",
        "no",
        "off",
    }
    if command_transport is not None and command_transport.kind == "azure" and not embed_pantheon:
        from fdai.delivery.agent_introspection_bus import (
            AGENT_INTROSPECTION_TOPICS,
            EventBusAgentIntrospectionClient,
        )

        remote_agent_delegate = EventBusAgentIntrospectionClient(
            event_bus=MultiplexedEventBus(
                bus=command_transport.event_bus,
                logical_topics=AGENT_INTROSPECTION_TOPICS,
                physical_topic=os.environ.get(
                    "FDAI_PANTHEON_OBJECT_TOPIC",
                    "aw.pantheon.objects",
                ).strip(),
            ),
            instance_id=f"operator-api-{uuid.uuid4().hex[:16]}",
            fallback_delegate=(
                local_read_investigation.chat_delegate
                if local_read_investigation is not None
                else None
            ),
        )
    if test_fixtures:
        live_stream_config, agent_activity_config = _build_agent_streams()
        local_operator_oid = (
            local_cli_identity.principal.oid if local_cli_identity is not None else "dev-anon"
        )
        fixture_runtime = build_local_runtime_wiring(
            read_model=read_model,
            action_types=tuple(action_types),
            workflows=tuple(built_in_workflows),
            live_stream_config=live_stream_config,
            local_operator_oid=local_operator_oid,
            action_topic=_LOCAL_ACTION_TOPIC,
            repo_root=_REPO_ROOT,
            runtime_values=startup_runtime_values,
        )
        runtime = fixture_runtime
        agent_activity_config = replace(
            agent_activity_config,
            snapshot_factory=lambda: runtime_agent_state_snapshot(
                fixture_runtime.pantheon_runtime.health()
            ),
        )
    elif command_transport is not None and embed_pantheon:
        pantheon_event_bus = (
            MultiplexedEventBus(
                bus=command_transport.event_bus,
                logical_topics=OWNED_OBJECT_TOPICS,
                physical_topic=os.environ.get(
                    "FDAI_PANTHEON_OBJECT_TOPIC", "aw.pantheon.objects"
                ).strip(),
            )
            if command_transport.kind == "azure"
            else command_transport.event_bus
        )
        handler_observer = (
            PantheonActivityObserver(
                publisher=SseAgentActivityPublisher(
                    sink=agent_activity_config.sink,
                    channel=agent_activity_config.channel,
                )
            )
            if command_transport.kind == "local"
            and agent_activity_config is not None
            and agent_activity_config.sink is not None
            else None
        )
        interactive_runtime = build_interactive_pantheon_wiring(
            event_bus=pantheon_event_bus,
            event_topic=command_transport.event_topic,
            read_model=read_model,
            action_types=tuple(action_types),
            handler_observer=handler_observer,
            runtime_values=startup_runtime_values,
        )
        runtime = interactive_runtime
        post_turn_review_queue = PostTurnReviewQueue(
            preferences=user_context.preferences,
            intake=EventBusPostTurnReviewIntake(bus=pantheon_event_bus),
        )
        if agent_activity_config is not None:
            agent_activity_config = replace(
                agent_activity_config,
                snapshot_factory=lambda: runtime_agent_state_snapshot(
                    interactive_runtime.pantheon_runtime.health()
                ),
            )
    metering = _build_local_metering(
        read_model=read_model,
        local_database_configured=local_database_configured,
        test_fixtures=test_fixtures,
    )
    models = build_local_model_wiring(_REPO_ROOT, metering_sink=metering)
    assurance_submitter = ConversationAssurancePostTurnSubmitter(
        coordinator=build_conversation_assurance_coordinator(
            ledger=assurance_ledger,
            budget=None,
            evaluators=(),
        ),
        delegate=post_turn_review_queue,
        adequacy_investigator=(
            HoldingOntologyAdequacyInvestigator() if persistence is not None else None
        ),
        adequacy_sink=(
            StateStoreOntologyAdequacyReviewSink(persistence.state_store)
            if persistence is not None
            else None
        ),
    )
    log_query_provider = None
    log_query_shutdown_callbacks: tuple[Callable[[], Any], ...] = ()
    monitor_workspace_id = os.environ.get("FDAI_MONITOR_WORKSPACE_ID", "").strip()
    if monitor_workspace_id:
        from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
        from fdai.delivery.azure.log_query import (
            AzureLogAnalyticsQueryConfig,
            AzureLogAnalyticsQueryProvider,
        )

        log_query_http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=35.0, write=10.0, pool=5.0)
        )
        log_query_provider = AzureLogAnalyticsQueryProvider(
            config=AzureLogAnalyticsQueryConfig(workspace_id=monitor_workspace_id),
            identity=AsyncAzureCliWorkloadIdentity(),
            http_client=log_query_http,
        )

        async def close_log_query_http() -> None:
            await log_query_http.aclose()

        log_query_shutdown_callbacks = (close_log_query_http,)
    skill_disclosure = empty_runtime_skill_disclosure()
    knowledge_context = (
        build_production_knowledge_context(
            dsn=cast(PostgresConsoleReadModel, read_model)._config.dsn,
            statement_timeout_ms=cast(
                PostgresConsoleReadModel, read_model
            )._config.statement_timeout_ms,
            connect_timeout_s=cast(PostgresConsoleReadModel, read_model)._config.connect_timeout_s,
            skill_disclosure=skill_disclosure,
            user_memories=user_context.memories,
        )
        if local_database_configured and not test_fixtures
        else KnowledgeContextChatTools(
            skill_disclosure=skill_disclosure,
            user_memories=user_context.memories,
        )
    )
    from fdai.delivery.operator_api.dev.configuration_drift import (
        build_local_configuration_drift_context,
    )

    configuration_drift_context = build_local_configuration_drift_context(
        environ=os.environ,
        repo_root=_REPO_ROOT,
    )
    inventory_graph_provider = (
        demo_inventory_graph_provider if test_fixtures else _build_inventory_graph_provider()
    )
    local_config = build_local_operator_api_config(
        LocalAppConfigDependencies(
            repo_root=_REPO_ROOT,
            environ=os.environ,
            dev_mode=dev_mode,
            test_fixtures=test_fixtures,
            local_database_configured=local_database_configured,
            local_cli_identity=local_cli_identity,
            read_model=read_model,
            postgres_read_model=postgres_read_model,
            persistence=persistence,
            authoritative_read_proxy=authoritative_read_proxy,
            live_stream_config=live_stream_config,
            agent_activity_config=agent_activity_config,
            conversation_history_store=conversation_history_store,
            assurance_ledger=assurance_ledger,
            assurance_policy_runtime=assurance_policy_runtime,
            user_context=user_context,
            conversation_policy_store=conversation_policy_store,
            user_context_ontology_projector=user_context_ontology_projector,
            assurance_submitter=assurance_submitter,
            workflow_definitions=workflow_definitions,
            models=models,
            workflow_authoring=workflow_authoring,
            workflow_execution=workflow_execution,
            inventory_graph_provider=inventory_graph_provider,
            inventory_activity_provider=(
                local_read_investigation.inventory_activity_provider
                if local_read_investigation is not None
                else None
            ),
            kubernetes_workload_provider=_build_kubernetes_workload_provider(),
            local_read_investigation=local_read_investigation,
            log_query_provider=log_query_provider,
            best_practice_controls=tuple(best_practice_controls),
            rule_catalog_rules=tuple(rule_catalog_rules),
            rule_catalog_collected=tuple(rule_catalog_collected),
            policies_root=policies_root,
            remediation_root=remediation_root,
            rule_catalog_findings_provider=rule_catalog_findings_provider,
            rule_catalog_findings_summary_provider=rule_catalog_findings_summary_provider,
            scope_source=scope_source,
            durable_panels=durable_panels,
            conversation_delivery_store=conversation_delivery_store,
            trace_reader=trace_reader,
            what_if_evaluators=what_if_evaluators,
            metering=metering,
            skill_disclosure=skill_disclosure,
            knowledge_context=knowledge_context,
            configuration_drift_context=configuration_drift_context,
            remote_agent_delegate=remote_agent_delegate,
            runtime=runtime,
            command_transport=command_transport,
            iam=iam,
            reporting=reporting,
            process_views=process_views,
            user_context_startup_callbacks=user_context_startup_callbacks,
            post_turn_review_queue=post_turn_review_queue,
            log_query_shutdown_callbacks=log_query_shutdown_callbacks,
            ontology_object_types=tuple(ontology_object_types),
            ontology_link_types=tuple(ontology_link_types),
            action_types=tuple(action_types),
            data_source_builder=build_local_data_sources,
            inventory_lifecycle_builder=_inventory_lifecycle_callbacks,
            cors_allow_origins=_cors_origins_from_env(),
            stewardship_map=_build_stewardship_map(),
            chat_probe_interval_seconds=_chat_probe_interval_seconds(),
        )
    )
    application = build_app(
        authenticator=authenticator,
        read_model=read_model,
        config=local_config,
    )
    application.state.pantheon_runtime = runtime.pantheon_runtime if runtime is not None else None
    application.state.chat_agent_delegate = (
        remote_agent_delegate
        if remote_agent_delegate is not None
        else local_read_investigation.chat_delegate
        if local_read_investigation is not None
        else PantheonChatDelegate(runtime.pantheon_runtime)
        if test_fixtures and runtime is not None
        else None
    )
    application.state.local_operator_runtime = (
        runtime.operator_runtime if runtime is not None else None
    )
    application.state.skill_disclosure = skill_disclosure
    return application


__all__ = [
    "_build_agent_streams",
    "_build_chat_backend",
    "_build_chat_web_search",
    "_build_inventory_graph_provider",
    "_inventory_lifecycle_callbacks",
    "_build_live_stream_config",
    "_build_stewardship_map",
    "_chat_probe_interval_seconds",
    "_cors_origins_from_env",
    "_group_mapping_from_env",
    "build_local_app",
]
