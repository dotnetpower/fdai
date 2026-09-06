"""Azure fork-wire overrides and full-container composition binding."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from ..shared.config.models import LlmMode
from ..shared.providers.workload_identity import WorkloadIdentity

if TYPE_CHECKING:
    from ..core.metering.pricing import PricingTable
    from ..core.metering.sink import MeteringSink
    from ..core.operator_memory import OperatorMemoryStore
    from ..delivery.azure.metric_logs import MetricKqlTemplate

from ._helpers import Container
from .wire_azure_observability import attach_azure_observability
from .wire_azure_prompts import compose_azure_prompt_bundle
from .wire_distiller import bind_azure_ontology_distiller_from_catalog as _bind_distiller
from .wire_llm import bind_azure_llm_bindings

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AzureWireOverrides:
    """Declarative fork overrides for :func:`wire_azure_container`.

    A fork's composition root constructs one with its concrete adapters and
    passes it to :func:`wire_azure_container`.

    Fields
    ------
    ``endpoint`` - the Azure OpenAI endpoint, e.g.
    ``https://oai-fork-krc.openai.azure.com``.

    ``catalog_root`` - path to the ``rule-catalog/`` tree the prompt
    registry + tool registry read from. Upstream ships one; a fork MAY
    point at a fork-owned tree that layers on top.

    ``operator_memory_store`` - the :class:`OperatorMemoryStore` the
    composer uses to inject operator-memory blocks. Upstream ships
    :class:`~fdai.core.operator_memory.InMemoryOperatorMemoryStore`;
    a deployment composition typically supplies
    :class:`~fdai.delivery.persistence.PostgresOperatorMemoryStore`
    or a fork-owned adapter.

    ``tool_providers`` - a mapping from ``ToolProvider`` id to the
    concrete provider a fork wires. Empty by default; every shipped
    tool is in ``shadow`` mode upstream so an empty mapping is fine
    for pipeline-parity tests. A fork populates this to light up
    function calling.

    ``scope_resolver`` - callable that turns a candidate's
    ``target_resource_ref`` into an
    :class:`~fdai.core.operator_memory.OperatorScope`. Fork-
    first because ARM-id parsing is CSP-specific; :class:`None` upstream
    means operator-memory entries never enter the composer output.

    ``model_endpoint_resolver`` - callable that resolves a verified abstract
    endpoint reference from ``resolved-models.json`` to its runtime URL. The
    binding still owns the deployment name and API style; an unknown reference
    fails closed before a model request.

    ``monitor_workspace_id`` - Log Analytics workspace GUID
    (``customerId``, NOT the ARM resource id). When supplied,
    :func:`wire_azure_container` auto-binds
    :class:`~fdai.delivery.azure.metric_logs.AzureMonitorLogsMetricProvider`
    in place of the upstream :class:`NoopMetricProvider` default so the
    detection pipeline (`core/detection/*`, `core/investigation/*`)
    receives real telemetry without every fork re-implementing the
    binding. ``None`` (default) keeps the no-op adapter, matching the
    dev-to-deploy parity contract for local-fake runs.

    ``monitor_queries`` - CSP-neutral ``metric_name`` -> KQL template map
    handed to the metric adapter. Only consulted when
    ``monitor_workspace_id`` is set. Defaults to the shipped
    :func:`~fdai.delivery.azure.demo_queries.default_metric_queries`
    (the union of the SRE-demo capture set and every metric requested
    by :func:`fdai.core.investigation.analyzers.default_analyzers`) so
    upstream ships a working detection baseline for **all** reference
    scenarios out of the box, not just the demo capture. A fork MAY
    pass its own map to add / override templates while keeping the
    returned ``value_column`` / ``timestamp_column`` / ``label_columns``
    shape.

    ``prometheus_base_url`` - Base URL of a Prometheus-compatible query
    endpoint (AKS Managed Prometheus, self-hosted Prom, Thanos, Cortex,
    Mimir). When supplied, :func:`wire_azure_container` binds a
    :class:`~fdai.delivery.prometheus.PrometheusMetricProvider` and,
    when a Log Analytics workspace is ALSO supplied, composes both
    behind a :class:`~fdai.shared.providers.routed_metric.RoutedMetricProvider`
    so metrics that Prometheus can serve (AKS-scoped: ``node_cpu_percent``,
    ...) hit Prom directly (sub-minute detection) while the non-AKS
    metrics still ride the AML KQL path (~2-5 min ingestion floor).
    When Prom is set but AML is not, Prom serves what it can and any
    other metric fails-closed. ``None`` (default) keeps the AML-only
    (or Noop) binding.

    ``prometheus_queries`` - CSP-neutral ``metric_name`` -> PromQL
    string map. Only consulted when ``prometheus_base_url`` is set;
    defaults to the shipped
    :func:`~fdai.delivery.prometheus.aks_managed_prometheus_queries`
    catalog. A fork's PromQL layout differs? Copy the map, override
    entries, pass the result via this override.

    ``prometheus_audience`` - Optional OIDC audience the Prometheus
    adapter mints a bearer token for (required by AKS Managed
    Prometheus + AAD auth). ``None`` skips authentication.
    """

    endpoint: str
    catalog_root: Path
    operator_memory_store: OperatorMemoryStore
    tool_providers: Mapping[str, Any] | None = None
    scope_resolver: Any | None = None
    model_endpoint_resolver: Callable[[str], str] | None = None
    metering_sink: MeteringSink | None = None
    model_health_sink: Any | None = None
    pricing: PricingTable | None = None
    monitor_workspace_id: str | None = None
    monitor_queries: Mapping[str, MetricKqlTemplate] | None = None
    metrics_api_queries: Mapping[str, Any] | None = None
    """Optional override for the Azure Monitor Metrics REST API template
    map (``metric_name`` -> ``MetricsApiTemplate``). Native resource metrics
    use the configured Azure identity without a Log Analytics workspace.
    Defaults to the shipped
    :func:`~fdai.delivery.azure.metrics_api_queries.azure_metrics_api_queries`
    catalog. The ``Any`` type keeps this module free of
    the ``metrics_api`` import at annotation time; the composition
    step below validates the shape by construction."""
    prometheus_base_url: str | None = None
    prometheus_queries: Mapping[str, str] | None = None
    prometheus_audience: str | None = None
    prompt_ablation_profile: str = "none"
    answer_continuity_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.endpoint:
            raise ValueError("AzureWireOverrides.endpoint MUST be non-empty")
        if self.operator_memory_store is None:
            raise ValueError(
                "AzureWireOverrides.operator_memory_store MUST be a concrete "
                "OperatorMemoryStore - pass InMemoryOperatorMemoryStore() "
                "explicitly if you do not want durability"
            )
        if not isinstance(self.answer_continuity_enabled, bool):
            raise ValueError("AzureWireOverrides.answer_continuity_enabled MUST be a boolean")
        # A caller that passes Logs queries without a workspace id has almost
        # certainly forgotten the workspace and would silently get a
        # NoopMetricProvider; fail-closed at build time so the misconfig
        # never reaches an Azure-mode deploy.
        if self.monitor_queries is not None and not self.monitor_workspace_id:
            raise ValueError(
                "AzureWireOverrides.monitor_queries requires "
                "monitor_workspace_id - queries without a workspace bind "
                "nothing"
            )
        # Symmetric guard for the Prometheus route.
        if self.prometheus_queries is not None and not self.prometheus_base_url:
            raise ValueError(
                "AzureWireOverrides.prometheus_queries requires "
                "prometheus_base_url - PromQL without an endpoint binds "
                "nothing"
            )
        if self.prometheus_audience is not None and not self.prometheus_base_url:
            raise ValueError(
                "AzureWireOverrides.prometheus_audience requires "
                "prometheus_base_url - an audience without an endpoint "
                "is a wiring bug"
            )


async def wire_azure_container(
    container: Container,
    *,
    http_client: httpx.AsyncClient,
    identity: WorkloadIdentity,
    overrides: AzureWireOverrides,
) -> Container:
    """Attach the full Azure delivery stack to ``container``.

    This is the **public API** a fork's composition root calls to
    finalize an azure-mode container. It replaces the previous private
    helper ``__main__._finalize_llm_bindings`` and captures the full
    wire-up pattern in one testable function:

    1. Build the prompt registry from ``overrides.catalog_root`` and
       compose the T2 primary system prompt.
    2. Build the tool registry + executor with the fork's
       ``overrides.tool_providers`` (empty upstream).
    3. Compose the optional Critic (``t2.critic``) and Judge
       (``t1.judge``) prompts. Missing prompts are logged and skipped;
       the debate orchestrator degrades to the pre-Wave-4 cross-check
       flow when either role is absent.
    4. Delegate to :func:`bind_azure_llm_bindings` to attach the AOAI
       adapters + optional Critic / Judge / DebateOrchestrator.

    Fail-closes on ``llm.mode != 'azure'`` - the caller MUST gate on
    mode before calling. Fail-closes on missing prompt registry files
    for the required T2 primary capability.

    :param container: The container returned by :func:`default_container`
        (or a fork's wrapper). MUST be in ``llm.mode='azure'``.
    :param http_client: Live :class:`httpx.AsyncClient`, owned by the
        caller. This function does NOT close it.
    :param identity: The :class:`WorkloadIdentity` (Managed Identity
        upstream) used to sign requests to Azure OpenAI.
    :param overrides: :class:`AzureWireOverrides` with the fork's
        concrete adapters.
    :returns: A new :class:`Container` with :attr:`llm_bindings`
        attached.
    """
    if container.config.llm.mode != LlmMode.AZURE:
        raise ValueError(
            f"wire_azure_container requires llm.mode='azure'; got {container.config.llm.mode!r}"
        )

    from ..core.tools import (
        CompositeToolRegistry,
        DefaultToolExecutor,
        FileSystemToolRegistry,
        StaticToolRegistry,
        ToolRegistry,
    )

    prompts = await compose_azure_prompt_bundle(
        catalog_root=overrides.catalog_root,
        operator_memory_store=overrides.operator_memory_store,
        answer_continuity_enabled=overrides.answer_continuity_enabled,
        prompt_ablation_profile=overrides.prompt_ablation_profile,
    )

    file_tool_registry = FileSystemToolRegistry(overrides.catalog_root)
    tool_registry: ToolRegistry = file_tool_registry
    if container.capability_runtime.reasoning_tools:
        tool_registry = CompositeToolRegistry(
            (
                file_tool_registry,
                StaticToolRegistry(container.capability_runtime.reasoning_tools),
            )
        )
    runtime_tool_providers = dict(container.capability_runtime.tool_providers)
    override_tool_providers = dict(overrides.tool_providers or {})
    duplicate_provider_ids = runtime_tool_providers.keys() & override_tool_providers.keys()
    if duplicate_provider_ids:
        names = ", ".join(sorted(duplicate_provider_ids))
        raise ValueError(
            f"duplicate tool providers across capability runtime and overrides: {names}"
        )
    tool_providers = runtime_tool_providers | override_tool_providers
    tool_executor = DefaultToolExecutor(
        registry=tool_registry,
        providers=tool_providers,
    )

    _LOGGER.info(
        "prompt_composed",
        extra={
            "capability_id": "t2.reasoner.primary",
            "layer_count": len(prompts.primary.layer_manifest),
            "token_estimate": prompts.primary.token_estimate,
            "layer_ids": [ref.id for ref in prompts.primary.layer_manifest],
            "tool_count": len(tool_registry.artifacts()),
            "operator_memory_store": type(overrides.operator_memory_store).__name__,
            "answer_continuity_enabled": overrides.answer_continuity_enabled,
            "prompt_ablation_profile": overrides.prompt_ablation_profile,
            "ablated_layer_ids": [ref.id for ref in prompts.primary.ablated_layers],
        },
    )

    # Default-load the shipped price table when a metering sink is wired
    # but no explicit pricing was supplied, so an injected sink produces
    # priced (not null-cost) records out of the box. A malformed file is
    # logged and degrades to unpriced rather than failing startup.
    pricing = overrides.pricing
    if pricing is None and overrides.metering_sink is not None:
        pricing_path = overrides.catalog_root / "llm-pricing.yaml"
        if pricing_path.is_file():
            # Lazy import to avoid a circular between __init__ and wire_azure.
            from . import load_pricing_table

            try:
                pricing = load_pricing_table(pricing_path)
            except Exception:  # noqa: BLE001 - pricing is best-effort, never fatal
                _LOGGER.warning("pricing_load_failed", extra={"path": str(pricing_path)})
                pricing = None

    container_with_llm = bind_azure_llm_bindings(
        container,
        identity=identity,
        http_client=http_client,
        endpoint=overrides.endpoint,
        system_prompt=prompts.primary.system_text,
        proposer_system_prompt=prompts.proposer.system_text,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        prompt_composer=prompts.composer,
        scope_resolver=overrides.scope_resolver,
        critic_system_prompt=prompts.critic,
        judge_system_prompt=prompts.judge,
        rca_system_prompt=prompts.rca,
        semantic_judgment_system_prompt=prompts.semantic_judgment,
        conversation_preflight_system_prompt=prompts.conversation_preflight,
        conversation_social_narrator_system_prompts=prompts.social_narrators,
        endpoint_resolver=overrides.model_endpoint_resolver,
        metering_sink=overrides.metering_sink,
        pricing=pricing,
        model_health_sink=overrides.model_health_sink,
    )
    container_with_distiller = await _bind_distiller(
        container_with_llm,
        identity,
        http_client,
        prompts.composer,
        overrides,
        pricing,
    )

    return attach_azure_observability(
        container_with_distiller,
        identity=identity,
        http_client=http_client,
        workspace_id=overrides.monitor_workspace_id,
        monitor_queries=overrides.monitor_queries,
        metrics_api_queries=overrides.metrics_api_queries,
        prometheus_base_url=overrides.prometheus_base_url,
        prometheus_queries=overrides.prometheus_queries,
        prometheus_audience=overrides.prometheus_audience,
        probe_root=overrides.catalog_root / "probes",
    )
