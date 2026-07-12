"""Azure fork-wire container (extracted from composition.py, G-3).

Contains :class:`AzureWireOverrides` (declarative fork overrides
dataclass) and :func:`wire_azure_container` (async composition helper
that combines a fork's overrides with the upstream defaults + the
:func:`bind_azure_llm_bindings` result).

Kept in its own module so a fork maintainer can read the whole
Azure-wire path without scrolling past every unrelated binder in the
old ``composition.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
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
from .wire_llm import bind_azure_llm_bindings

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AzureWireOverrides:
    """Declarative fork overrides for :func:`wire_azure_container`.

    A fork's composition root constructs one of these once with its
    concrete adapters and passes it in. This is the **structured
    replacement** for the previous pattern of reproducing
    ``__main__._finalize_llm_bindings`` (a private helper) - a fork
    now writes a few lines of :class:`AzureWireOverrides` and calls
    :func:`wire_azure_container` instead of ~200 lines of glue.

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
    a production fork typically supplies
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
    :func:`~fdai.delivery.azure.demo_queries.sre_demo_capture_queries`
    map so upstream ships a working detection baseline; a fork MAY pass
    its own map to add / override templates while keeping the returned
    ``value_column`` / ``timestamp_column`` / ``label_columns`` shape.
    """

    endpoint: str
    catalog_root: Path
    operator_memory_store: OperatorMemoryStore
    tool_providers: Mapping[str, Any] | None = None
    scope_resolver: Any | None = None
    metering_sink: MeteringSink | None = None
    pricing: PricingTable | None = None
    monitor_workspace_id: str | None = None
    monitor_queries: Mapping[str, MetricKqlTemplate] | None = None

    def __post_init__(self) -> None:
        if not self.endpoint:
            raise ValueError("AzureWireOverrides.endpoint MUST be non-empty")
        if self.operator_memory_store is None:
            raise ValueError(
                "AzureWireOverrides.operator_memory_store MUST be a concrete "
                "OperatorMemoryStore - pass InMemoryOperatorMemoryStore() "
                "explicitly if you do not want durability"
            )
        # A caller that passes queries without a workspace id has almost
        # certainly forgotten the workspace and would silently get a
        # NoopMetricProvider; fail-closed at build time so the misconfig
        # never reaches an Azure-mode deploy.
        if self.monitor_queries is not None and not self.monitor_workspace_id:
            raise ValueError(
                "AzureWireOverrides.monitor_queries requires "
                "monitor_workspace_id - queries without a workspace bind "
                "nothing"
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

    from ..core.prompts import DefaultPromptComposer, FileSystemPromptRegistry
    from ..core.tools import DefaultToolExecutor, FileSystemToolRegistry

    prompt_registry = FileSystemPromptRegistry(overrides.catalog_root)
    composer = DefaultPromptComposer(
        registry=prompt_registry,
        operator_memory_store=overrides.operator_memory_store,
    )
    composed = await composer.compose(capability_id="t2.reasoner.primary")

    tool_registry = FileSystemToolRegistry(overrides.catalog_root)
    tool_executor = DefaultToolExecutor(
        registry=tool_registry,
        providers=dict(overrides.tool_providers) if overrides.tool_providers else {},
    )

    # Wave 4 beta-2: compose the Critic system prompt from the shipped
    # ``rule-catalog/prompts/base/t2-critic.v1.yaml`` seed. When no
    # critic base prompt is found we log and skip - the bind step then
    # leaves ``LlmBindings.critic_model = None`` and the debate
    # orchestrator degrades to the pre-Wave-4 cross-check flow.
    critic_system_prompt: str | None = None
    try:
        critic_composed = await composer.compose(capability_id="t2.critic")
    except LookupError:
        _LOGGER.info("critic_prompt_missing", extra={"capability_id": "t2.critic"})
    else:
        critic_system_prompt = critic_composed.system_text
        _LOGGER.info(
            "critic_prompt_composed",
            extra={
                "capability_id": "t2.critic",
                "layer_count": len(critic_composed.layer_manifest),
                "token_estimate": critic_composed.token_estimate,
            },
        )

    # Wave 4.5 delta-1: same shape for the Judge. When both critic and
    # judge prompts compose AND both capabilities resolve, the bind
    # step auto-constructs the DebateOrchestrator.
    judge_system_prompt: str | None = None
    try:
        judge_composed = await composer.compose(capability_id="t1.judge")
    except LookupError:
        _LOGGER.info("judge_prompt_missing", extra={"capability_id": "t1.judge"})
    else:
        judge_system_prompt = judge_composed.system_text
        _LOGGER.info(
            "judge_prompt_composed",
            extra={
                "capability_id": "t1.judge",
                "layer_count": len(judge_composed.layer_manifest),
                "token_estimate": judge_composed.token_estimate,
            },
        )

    # RCA T2 reasoner prompt (symmetric to Critic / Judge). Missing prompt
    # is logged and skipped; the bind step then leaves
    # ``LlmBindings.rca_reasoner = None`` and T2 RCA stays dark.
    rca_system_prompt: str | None = None
    try:
        rca_composed = await composer.compose(capability_id="t2.rca")
    except LookupError:
        _LOGGER.info("rca_prompt_missing", extra={"capability_id": "t2.rca"})
    else:
        rca_system_prompt = rca_composed.system_text
        _LOGGER.info(
            "rca_prompt_composed",
            extra={
                "capability_id": "t2.rca",
                "layer_count": len(rca_composed.layer_manifest),
                "token_estimate": rca_composed.token_estimate,
            },
        )

    _LOGGER.info(
        "prompt_composed",
        extra={
            "capability_id": "t2.reasoner.primary",
            "layer_count": len(composed.layer_manifest),
            "token_estimate": composed.token_estimate,
            "layer_ids": [ref.id for ref in composed.layer_manifest],
            "tool_count": len(tool_registry.artifacts()),
            "operator_memory_store": type(overrides.operator_memory_store).__name__,
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
        system_prompt=composed.system_text,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        prompt_composer=composer,
        scope_resolver=overrides.scope_resolver,
        critic_system_prompt=critic_system_prompt,
        judge_system_prompt=judge_system_prompt,
        rca_system_prompt=rca_system_prompt,
        metering_sink=overrides.metering_sink,
        pricing=pricing,
    )

    # Chain the Azure Monitor Logs metric adapter in when the fork (or
    # __main__'s ``FDAI_MONITOR_WORKSPACE_ID`` resolver) supplies a
    # workspace. Upstream defaults to the shipped SRE-demo capture query
    # map so the detection pipeline (`core/detection/*`,
    # `core/investigation/*`) receives real telemetry out of the box;
    # a fork passes ``monitor_queries`` to add or override templates.
    if overrides.monitor_workspace_id:
        from ..delivery.azure.demo_queries import sre_demo_capture_queries
        from ..delivery.azure.metric_logs import AzureMonitorLogsConfig
        from . import bind_azure_monitor_logs

        queries = overrides.monitor_queries or sre_demo_capture_queries()
        monitor_config = AzureMonitorLogsConfig(
            workspace_id=overrides.monitor_workspace_id,
            queries=queries,
        )
        _LOGGER.info(
            "azure_monitor_logs_bound",
            extra={
                "workspace_id": overrides.monitor_workspace_id,
                "query_count": len(queries),
                "query_source": (
                    "override"
                    if overrides.monitor_queries is not None
                    else "sre_demo_capture_queries"
                ),
            },
        )
        return bind_azure_monitor_logs(
            container_with_llm,
            config=monitor_config,
            identity=identity,
            http_client=http_client,
        )

    _LOGGER.info(
        "azure_monitor_logs_skipped",
        extra={"reason": "monitor_workspace_id not supplied"},
    )
    return container_with_llm
