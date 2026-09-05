"""Azure-specific semantic query runtime composition."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import yaml

from fdai.core.ontology_platform import (
    MetricSemanticRegistry,
    MetricWindowProvider,
    TopologyHistoryReader,
)
from fdai.core.ontology_platform.graph_query_refresh import BoundedGraphLiveRefreshProvider
from fdai.core.ontology_platform.incident_queries import IncidentEvidenceReader
from fdai.core.ontology_platform.kubernetes_pod_diagnosis_queries import (
    KubernetesPodLogEvidenceReader,
)
from fdai.core.ontology_platform.property_values import PropertyValueDomain
from fdai.core.ontology_platform.resource_event_queries import ResourceEventCollectionReader
from fdai.core.ontology_platform.resource_health_queries import ResourceHealthCollectionReader
from fdai.core.ontology_platform.service_health_queries import ServiceHealthReader
from fdai.core.ontology_platform.state_transitions import StateTransitionStore
from fdai.core.ontology_platform.subscription_scope_queries import SubscriptionScopeReader
from fdai.core.ontology_platform.vm_process_evidence import VmProcessCpuReader
from fdai.core.prompts.registry import FileSystemPromptRegistry
from fdai.delivery.azure.llm.semantic_planning import (
    AzureOpenAISemanticPlanningModel,
    AzureOpenAISemanticPlanningModelConfig,
)
from fdai.rule_catalog.schema.inventory_query_language import (
    InventoryQueryLanguageRegistry,
    load_inventory_query_language_from_mapping,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.shared.config.models import LlmMode
from fdai.shared.contracts.models import OntologyRelease
from fdai.shared.providers.catalog_search import CatalogSemanticIndex
from fdai.shared.providers.ontology_instance import OntologyInstanceStore
from fdai.shared.providers.read_investigation import ReadInvestigationProvider
from fdai.shared.providers.workload_identity import WorkloadIdentity

from ._helpers import Container
from .resolved_models_revision import resolved_models_for_binding
from .semantic_query_model_targets import t1_model_targets, t2_model_targets
from .semantic_query_value_domains import resource_type_value_domains

if TYPE_CHECKING:
    from .wire_semantic_query import SemanticQueryRuntimeComposition

_FRAME_CAPABILITY = "semantic.query.frame"
_PLAN_CAPABILITY = "semantic.query.plan"


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
    topology_reader: TopologyHistoryReader | None = None,
    metric_registry: MetricSemanticRegistry | None = None,
    metric_window_provider: MetricWindowProvider | None = None,
    incident_evidence_reader: IncidentEvidenceReader | None = None,
    read_investigation_provider: ReadInvestigationProvider | None = None,
    resource_health_reader: ResourceHealthCollectionReader | None = None,
    resource_event_reader: ResourceEventCollectionReader | None = None,
    subscription_scope_reader: SubscriptionScopeReader | None = None,
    service_health_reader: ServiceHealthReader | None = None,
    state_transition_reader: StateTransitionStore | None = None,
    vm_process_cpu_reader: VmProcessCpuReader | None = None,
    pod_log_evidence_reader: KubernetesPodLogEvidenceReader | None = None,
    graph_live_refresh_provider: BoundedGraphLiveRefreshProvider | None = None,
    resource_freshness_seconds: int | None = None,
) -> SemanticQueryRuntimeComposition:
    """Compose Azure semantic querying over optional exact Rule retrieval."""

    from .wire_semantic_query import (
        SemanticQueryRuntimeComposition,
        build_semantic_query_runtime,
    )

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
        resolved = resolved_models_for_binding(container)
        t1_candidates = t1_model_targets(
            resolved,
            endpoint=endpoint,
            endpoint_resolver=endpoint_resolver,
            held_capabilities=container.held_model_capabilities,
        )
        if not t1_candidates:
            return _unavailable("semantic_t1_model_candidates_unavailable")
        t2_candidates = t2_model_targets(
            resolved,
            endpoint=endpoint,
            endpoint_resolver=endpoint_resolver,
            held_capabilities=container.held_model_capabilities,
        )
        prompts = FileSystemPromptRegistry(catalog_root)
        frame_system_prompt = prompts.get_base(_FRAME_CAPABILITY).body
        plan_system_prompt = prompts.get_base(_PLAN_CAPABILITY).body
        t1_model = AzureOpenAISemanticPlanningModel(
            identity=identity,
            http_client=http_client,
            config=AzureOpenAISemanticPlanningModelConfig(
                candidates=t1_candidates,
                frame_system_prompt=frame_system_prompt,
                plan_system_prompt=plan_system_prompt,
            ),
            owner_loop=owner_loop,
        )
        t2_model = (
            AzureOpenAISemanticPlanningModel(
                identity=identity,
                http_client=http_client,
                config=AzureOpenAISemanticPlanningModelConfig(
                    candidates=t2_candidates,
                    frame_system_prompt=frame_system_prompt,
                    plan_system_prompt=plan_system_prompt,
                ),
                owner_loop=owner_loop,
            )
            if t2_candidates
            else None
        )
        catalog = load_ontology_catalog(
            catalog_root,
            schema_registry=container.schema_registry,
            probes_root=(catalog_root / "probes" if (catalog_root / "probes").is_dir() else None),
        )
        runtime = build_semantic_query_runtime(
            model=t1_model,
            escalation_model=t2_model,
            semantic_judgment=(
                container.llm_bindings.conversation_semantic_judgment_factory(owner_loop)
                if container.llm_bindings is not None
                and container.llm_bindings.conversation_semantic_judgment_factory is not None
                else None
            ),
            ontology_release=ontology_release,
            ontology_catalog=catalog,
            ontology_store=ontology_store,
            catalog_index=catalog_index,
            catalog_digest=catalog_digest,
            topology_reader=topology_reader,
            metric_registry=metric_registry,
            metric_window_provider=metric_window_provider,
            incident_evidence_reader=incident_evidence_reader,
            read_investigation_provider=read_investigation_provider,
            resource_health_reader=resource_health_reader,
            resource_event_reader=resource_event_reader,
            subscription_scope_reader=subscription_scope_reader,
            service_health_reader=service_health_reader,
            state_transition_reader=state_transition_reader,
            vm_process_cpu_reader=vm_process_cpu_reader,
            pod_log_evidence_reader=pod_log_evidence_reader,
            graph_live_refresh_provider=graph_live_refresh_provider,
            resource_freshness_seconds=resource_freshness_seconds,
            property_values=_resource_type_property_values(catalog_root),
            inventory_query_language=_inventory_query_language(catalog_root),
            purpose=purpose,
        )
    except (OSError, LookupError, TypeError, ValueError):
        return _unavailable("semantic_composition_invalid")
    return SemanticQueryRuntimeComposition(
        runtime=runtime,
        unavailable_reason=None,
        model_auth_audiences=tuple(
            dict.fromkeys(target.auth_audience for target in (*t1_candidates, *t2_candidates))
        ),
    )


def _resource_type_property_values(catalog_root: Path) -> tuple[PropertyValueDomain, ...]:
    vocabulary = catalog_root / "vocabulary" / "resource-types.yaml"
    registry = load_resource_type_registry_from_mapping(
        yaml.safe_load(vocabulary.read_text(encoding="utf-8"))
    )
    return resource_type_value_domains(registry)


def _inventory_query_language(catalog_root: Path) -> InventoryQueryLanguageRegistry:
    vocabulary = catalog_root / "vocabulary" / "inventory-query-language.yaml"
    return load_inventory_query_language_from_mapping(
        yaml.safe_load(vocabulary.read_text(encoding="utf-8"))
    )


def _unavailable(reason: str) -> SemanticQueryRuntimeComposition:
    from .wire_semantic_query import SemanticQueryRuntimeComposition

    return SemanticQueryRuntimeComposition(runtime=None, unavailable_reason=reason)
