"""Semantic and read-investigation assembly for the headless runtime."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from fdai.agents import Saga
from fdai.composition import (
    Container,
    compose_azure_semantic_query_runtime,
    compose_resource_state_shadow_hook,
)
from fdai.core.control_loop import ControlLoop
from fdai.core.ontology_platform.incident_queries import IncidentEvidenceReader
from fdai.core.ontology_platform.inventory_projection import (
    DEFAULT_OBSERVED_STATE_FRESHNESS_CEILING_SECONDS,
)
from fdai.core.operational_context import OperationalEvidenceReadService
from fdai.delivery.inventory_live_evidence import (
    InventoryGraphLiveRefreshProvider,
    InventoryLiveEvidenceWriter,
)
from fdai.delivery.operational_activity import EventBusOperationalActivityPublisher
from fdai.delivery.persistence.postgres_inventory_delta import PostgresInventoryDeltaProjector
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.runtime.bootstrap_bindings import (
    RuleGenerationRuntimeBinding,
    build_rule_generation_runtime_binding,
    semantic_query_providers,
)
from fdai.runtime.bootstrap_lifecycle import (
    build_catalog_semantic_runtime_binding,
    build_semantic_turn_binding,
    catalog_semantic_readiness_registration,
    semantic_turn_readiness_registration,
)
from fdai.runtime.configuration import (
    _direct_model_endpoint_resolver,
    _resolve_catalog_root,
)
from fdai.runtime.providers import (
    _build_read_investigation_provider,
    _build_resource_event_history_reader,
    _build_resource_health_collection_reader,
    _build_service_health_reader,
    _build_vm_process_cpu_reader,
)
from fdai.runtime.read_investigation_runtime import (
    ReadInvestigationRuntimeBinding,
    build_read_investigation_runtime_binding,
)
from fdai.runtime.rule_generation_documents import (
    RuleGenerationDocumentsUnavailableError,
    RuleGenerationReconciliation,
    build_rule_generation_reconciliation,
)
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger("fdai.startup")


def _semantic_resource_freshness_seconds(environment: Mapping[str, str]) -> int:
    raw = environment.get("FDAI_SEMANTIC_RESOURCE_FRESHNESS_SECONDS", "").strip()
    if not raw:
        return DEFAULT_OBSERVED_STATE_FRESHNESS_CEILING_SECONDS
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("FDAI_SEMANTIC_RESOURCE_FRESHNESS_SECONDS MUST be an integer") from exc
    if not 1 <= value <= 86_400:
        raise RuntimeError("FDAI_SEMANTIC_RESOURCE_FRESHNESS_SECONDS MUST be in [1, 86400]")
    return value


def _graph_live_refresh_provider(
    *,
    environment: Mapping[str, str],
    read_provider: Any,
) -> InventoryGraphLiveRefreshProvider | None:
    dsn = (
        environment.get("FDAI_INVENTORY_DSN", "").strip()
        or environment.get("FDAI_STATE_STORE_DSN", "").strip()
    )
    scope_ref = environment.get("AZURE_SUBSCRIPTION_ID", "").strip()
    if read_provider is None or not dsn or not scope_ref:
        return None
    config = PostgresInventorySnapshotStoreConfig(dsn=dsn)
    return InventoryGraphLiveRefreshProvider(
        provider=read_provider,
        writer=InventoryLiveEvidenceWriter(
            ingress=PostgresInventoryDeltaProjector(
                config=config,
                clock=lambda: datetime.now(tz=UTC),
            )
        ),
        scope_ref=scope_ref,
    )


@dataclass(frozen=True, slots=True)
class SemanticRuntime:
    """Semantic bindings retained by readiness, tasks, and Pantheon assembly."""

    semantic_turn_binding: Any
    read_investigation_hook: Any
    read_investigation_binding: ReadInvestigationRuntimeBinding | None
    operational_evidence_read_service: OperationalEvidenceReadService | None
    rule_generation_binding: RuleGenerationRuntimeBinding
    rule_generation_reconciliation: RuleGenerationReconciliation | None
    readiness_specs: tuple[Any, ...]
    readiness_probes: tuple[Any, ...]


async def build_semantic_runtime(
    *,
    container: Container,
    control_loop: ControlLoop,
    state_store: StateStore,
    event_bus: EventBus,
    operational_event_bus: EventBus,
    runtime_saga: Saga,
    identity: WorkloadIdentity | None,
    http_client: httpx.AsyncClient | None,
    stage_topic: str,
    environment: Mapping[str, str],
) -> SemanticRuntime:
    """Bind semantic retrieval and investigation paths from one runtime snapshot."""

    catalog_root = _resolve_catalog_root()
    llm_bindings = container.require_llm_bindings()
    catalog_binding = await build_catalog_semantic_runtime_binding(
        config=environment,
        embedder=llm_bindings.embedding_model,
        rules=control_loop.rules,
        ontology_release=control_loop.ontology_release,
    )
    query_catalog_index = catalog_binding.index if catalog_binding.available else None
    query_catalog_digest = catalog_binding.catalog_digest if catalog_binding.available else None
    rule_generation_binding = build_rule_generation_runtime_binding(
        state_store=state_store,
        event_bus=event_bus,
        catalog_index=catalog_binding.index,
        environment=environment,
    )
    reconciliation: RuleGenerationReconciliation | None = None
    if catalog_binding.index is not None and control_loop.ontology_release is not None:
        try:
            reconciliation = await build_rule_generation_reconciliation(
                catalog_root=catalog_root,
                rules=control_loop.rules,
                action_types=control_loop.action_types,
                ontology_release=control_loop.ontology_release,
                embedder=llm_bindings.embedding_model,
                index=catalog_binding.index,
                store=state_store,
                request_generation=not catalog_binding.available,
                requested_at=datetime.now(UTC),
            )
        except RuleGenerationDocumentsUnavailableError as exc:
            _LOGGER.warning(
                "rule_generation_reconciliation_unavailable",
                extra={"reason": str(exc)},
            )

    topology_reader, metric_registry, metric_window_provider = semantic_query_providers(
        state_store_dsn=environment.get("FDAI_STATE_STORE_DSN"),
        subscription_id=environment.get("AZURE_SUBSCRIPTION_ID"),
        metric_provider=container.metric_provider,
        metric_registry=control_loop.metric_semantics,
    )
    incident_evidence_reader = (
        state_store if isinstance(state_store, IncidentEvidenceReader) else None
    )
    read_investigation_provider = _build_read_investigation_provider(
        identity=identity,
        http_client=http_client,
        environment=environment,
    )
    read_investigation_binding = build_read_investigation_runtime_binding(
        environment=environment,
        provider=read_investigation_provider,
        state_store=state_store,
        saga_audit_chain=runtime_saga.audit_chain,
    )
    operational_evidence_read_service = (
        OperationalEvidenceReadService(
            source=container.operational_evidence_source,
            clock=lambda: datetime.now(tz=UTC),
        )
        if container.operational_evidence_source is not None
        else None
    )
    resource_health_reader = _build_resource_health_collection_reader(
        identity=identity,
        http_client=http_client,
    )
    resource_event_reader = _build_resource_event_history_reader(
        identity=identity,
        http_client=http_client,
        environment=environment,
    )
    service_health_reader = _build_service_health_reader(
        identity=identity,
        http_client=http_client,
    )
    vm_process_cpu_reader = _build_vm_process_cpu_reader(
        identity=identity,
        http_client=http_client,
    )
    endpoint = environment.get("FDAI_LLM_ENDPOINT", "").strip() or None
    semantic_composition = compose_azure_semantic_query_runtime(
        container=container,
        ontology_release=control_loop.ontology_release,
        ontology_store=control_loop.ontology_instance_store,
        identity=identity,
        http_client=http_client,
        endpoint=endpoint,
        endpoint_resolver=(
            _direct_model_endpoint_resolver(endpoint) if endpoint is not None else None
        ),
        catalog_root=catalog_root,
        owner_loop=asyncio.get_running_loop(),
        purpose=environment.get("FDAI_SEMANTIC_TURN_PURPOSE", "operations-review").strip(),
        catalog_index=query_catalog_index,
        catalog_digest=query_catalog_digest,
        topology_reader=topology_reader,
        metric_registry=metric_registry,
        metric_window_provider=metric_window_provider,
        incident_evidence_reader=incident_evidence_reader,
        read_investigation_provider=read_investigation_provider,
        resource_health_reader=resource_health_reader,
        resource_event_reader=resource_event_reader,
        service_health_reader=service_health_reader,
        vm_process_cpu_reader=vm_process_cpu_reader,
        graph_live_refresh_provider=_graph_live_refresh_provider(
            environment=environment,
            read_provider=read_investigation_provider,
        ),
        resource_freshness_seconds=_semantic_resource_freshness_seconds(environment),
    )
    semantic_turn_binding = build_semantic_turn_binding(
        state_store=state_store,
        config=environment,
        runtime=semantic_composition.runtime,
        unavailable_reason=semantic_composition.unavailable_reason,
    )
    read_investigation_hook = compose_resource_state_shadow_hook(
        provider=read_investigation_provider,
        state_store=state_store,
        ontology_release=control_loop.ontology_release,
        ontology_store=control_loop.ontology_instance_store,
        schema_registry=container.schema_registry,
        catalog_root=catalog_root,
        activity_publisher=EventBusOperationalActivityPublisher(
            event_bus=operational_event_bus,
            topic=stage_topic,
        ),
    )
    if semantic_turn_binding is not None and not semantic_turn_binding.available:
        _LOGGER.warning(
            "semantic_turn_runtime_unavailable",
            extra={"reason": semantic_turn_binding.unavailable_reason},
        )

    semantic_specs, semantic_probes = semantic_turn_readiness_registration(semantic_turn_binding)
    catalog_specs, catalog_probes = catalog_semantic_readiness_registration(catalog_binding)
    return SemanticRuntime(
        semantic_turn_binding=semantic_turn_binding,
        read_investigation_hook=read_investigation_hook,
        read_investigation_binding=read_investigation_binding,
        operational_evidence_read_service=operational_evidence_read_service,
        rule_generation_binding=rule_generation_binding,
        rule_generation_reconciliation=reconciliation,
        readiness_specs=(*semantic_specs, *catalog_specs),
        readiness_probes=(*semantic_probes, *catalog_probes),
    )


__all__ = ["SemanticRuntime", "build_semantic_runtime"]
