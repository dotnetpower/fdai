"""Production Azure reader and read-investigation wiring."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from fdai.delivery.event_bus_multiplex import MultiplexedEventBus
from fdai.delivery.operator_api.production import env_contract as _env
from fdai.delivery.operator_api.production.config import (
    ProdOperatorApiConfigError,
    _parse_positive_int,
)
from fdai.delivery.operator_api.production.configuration_drift import (
    build_production_configuration_drift_context,
    build_production_configuration_review,
)
from fdai.delivery.operator_api.routes.background_runtime import (
    build_background_task_runtime,
)
from fdai.delivery.persistence import (
    PostgresReadInvestigationRunStore,
    PostgresReadInvestigationRunStoreConfig,
)

_AsyncCallback = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ProductionReadInvestigationWiring:
    """Optional production readers, routes, delegates, and lifecycle callbacks."""

    background_runtime: Any
    read_investigations: Any
    chat_agent_delegate: Any
    inventory_activity_provider: Any
    subscription_health_provider: Any
    configuration_drift_context: Any
    configuration_review: Any
    schema_verification_callbacks: tuple[_AsyncCallback, ...]
    reader_startup_callbacks: tuple[_AsyncCallback, ...]
    delegate_startup_callbacks: tuple[_AsyncCallback, ...]
    shutdown_callbacks: tuple[_AsyncCallback, ...]


def build_production_read_investigation(
    *,
    env: Mapping[str, str],
    repo_root: Path,
    read_model: Any,
    state_store: Any,
    conversation_history_store: Any,
    background_outbound_delivery: Any,
    principal_binding_store: Any,
    event_bus: Any,
    shutdown_callbacks: tuple[_AsyncCallback, ...],
) -> ProductionReadInvestigationWiring:
    """Build the optional Azure reader and read-investigation runtime."""
    background_executor = None
    read_investigation_service = None
    subscription_health_provider = None
    read_latency_store = None
    read_investigation_run_store = None
    read_investigation_ledger_config = None
    inventory_activity_provider = None
    reader_startup_callbacks: tuple[_AsyncCallback, ...] = ()
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
            lease_seconds=_parse_positive_int(
                env,
                _env.READ_INVESTIGATION_LEASE_SECONDS_ENV,
                30,
            ),
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

        load_bound_investigation_intents(repo_root)
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
    if event_bus is not None:
        from fdai.delivery.agent_introspection_bus import (
            AGENT_INTROSPECTION_TOPICS,
            EventBusAgentIntrospectionClient,
        )

        remote_agent_delegate = EventBusAgentIntrospectionClient(
            event_bus=MultiplexedEventBus(
                bus=event_bus,
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

    return ProductionReadInvestigationWiring(
        background_runtime=background_runtime,
        read_investigations=read_investigation_routes,
        chat_agent_delegate=remote_agent_delegate or read_investigation_chat_delegate,
        inventory_activity_provider=inventory_activity_provider,
        subscription_health_provider=subscription_health_provider,
        configuration_drift_context=configuration_drift_context,
        configuration_review=configuration_review,
        schema_verification_callbacks=(
            (read_investigation_run_store.verify_schema,)
            if read_investigation_run_store is not None
            else ()
        ),
        reader_startup_callbacks=reader_startup_callbacks,
        delegate_startup_callbacks=(
            (remote_agent_delegate.start,) if remote_agent_delegate is not None else ()
        ),
        shutdown_callbacks=shutdown_callbacks,
    )


__all__ = [
    "ProductionReadInvestigationWiring",
    "build_production_read_investigation",
]
