"""Composition root - the ONE place that instantiates concrete implementations.

``core/`` modules never construct adapters; they receive :class:`Container`
instances (or the individual seam Protocols) via arguments. Only entry points
(``__main__``, CLIs, tests) call :func:`default_container` /
:func:`default_container_from_env`. A per-customer fork registers its own
bindings by exposing its own container factory in its composition root -
it MUST NOT edit ``core/`` or patch upstream defaults.

Fail-fast contract
------------------
:func:`default_container` **requires an explicit** :class:`AppConfig`. There
is no implicit env-var read in the primary factory. That way, unit tests
build a config in code (no environment surprises), and only the operator's
entry point calls :func:`default_container_from_env`, which does read the
process environment.

LLM bindings
------------

The container carries an :class:`LlmBindings` that resolves the T1 embedding
model and the T2 cross-check models. In ``llm.mode == 'local-fake'`` (the
default in dev), the composition root binds the deterministic in-memory
fakes from ``core/tiers/t1_lightweight/testing.py`` and
``core/quality_gate/testing.py`` - the pipeline works end-to-end with zero
Azure credentials. In ``llm.mode == 'azure'``, ``Container.llm_bindings``
starts as ``None``; the entry point MUST call :func:`bind_azure_llm_bindings`
with a live :class:`httpx.AsyncClient` and a :class:`WorkloadIdentity` to
attach the real adapters. Attempting to use ``Container.llm_bindings``
before that hand-off raises :class:`LlmBindingsUnavailableError`, so the
process cannot silently degrade to fakes in production.

Design references
-----------------
- ``docs/roadmap/project-structure.md § Customization via Dependency Injection``
- ``docs/roadmap/dev-and-deploy-parity.md § Parity Contract``
- ``docs/roadmap/deploy-and-onboard.md § Runtime Configuration Matrix``
- ``.github/instructions/generic-scope.instructions.md``
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from .core.quality_gate.critic import CriticModel
from .core.quality_gate.debate import DebateOrchestrator, DebateOrchestratorConfig
from .core.quality_gate.gate import CrossCheckModel
from .core.quality_gate.judge import JudgeModel
from .core.quality_gate.testing import MatchTypeCrossCheckModel, MismatchCrossCheckModel
from .core.tiers.t1_lightweight.testing import DeterministicEmbeddingModel
from .core.tiers.t1_lightweight.tier import EmbeddingModel
from .rule_catalog.schema.llm_resolver import (
    CapabilityStatus,
    ResolvedCapability,
    ResolvedModels,
)
from .shared.config.loader import load_config_from_env
from .shared.config.models import AppConfig, LlmMode
from .shared.contracts.registry import (
    PackageResourceSchemaRegistry,
    SchemaRegistry,
)
from .shared.contracts.validation import (
    ContractValidator,
    EventValidator,
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)
from .shared.providers.exemption import (
    ExemptionRegistry,
    empty_exemption_registry,
)
from .shared.providers.feasibility_probe import FeasibilityProbe
from .shared.providers.workload_identity import WorkloadIdentity

if TYPE_CHECKING:
    from .core.operator_memory import OperatorMemoryStore

_LOGGER = logging.getLogger(__name__)


class LlmBindingsUnavailableError(RuntimeError):
    """Raised when core code touches LLM bindings that were never attached.

    Fail-close guard: azure-mode containers start with ``llm_bindings=None``
    and MUST be finalized via :func:`bind_azure_llm_bindings`. A caller that
    reaches this exception is running in production without having wired
    the Azure adapters - the process refuses to proceed.
    """


@dataclass(frozen=True, slots=True)
class LlmBindings:
    """Runtime-bound LLM seams handed to core code.

    ``cross_check_models`` MUST contain the number of models the quality
    gate expects to reach quorum (default 2 - see
    :class:`~fdai.core.quality_gate.gate.QualityGateConfig`).

    ``critic_model`` (Wave 4 beta-2) is OPTIONAL. When the
    ``t2.critic`` capability resolves in ``resolved-models.json`` the
    composition root binds a real :class:`CriticModel` here so the
    Wave 4.5 debate orchestrator can consume it; otherwise the
    field stays ``None`` and the flow keeps its pre-Wave-4 shape.

    ``judge_model`` (Wave 4.5 delta-1) is OPTIONAL. Analogous to
    ``critic_model`` but backed by the ``t1.judge`` capability. Kept
    as an independent binding (not derived from ``critic_model``) so
    a fork can bind the Judge without the Critic (e.g. for a
    single-role review pass) or vice versa.

    ``debate_orchestrator`` (Wave 4.5 delta-1) is OPTIONAL and is
    auto-constructed by the composition root **only when both
    ``critic_model`` AND ``judge_model`` are bound**. A fork that
    supplies its own orchestrator implementation (custom max_rounds,
    different transcript store) can pass one in via
    :func:`dataclasses.replace`.
    """

    embedding_model: EmbeddingModel
    cross_check_models: tuple[CrossCheckModel, ...]
    critic_model: CriticModel | None = None
    judge_model: JudgeModel | None = None
    debate_orchestrator: DebateOrchestrator | None = None

    def __post_init__(self) -> None:
        if not self.cross_check_models:
            raise ValueError("LlmBindings.cross_check_models MUST have at least one entry")
        # Cross-consistency: the orchestrator needs both role models.
        # A caller that manually built LlmBindings without both roles
        # but with an orchestrator has a wiring bug that will surface
        # as a runtime failure inside the orchestrator; catch it here.
        if self.debate_orchestrator is not None and (
            self.critic_model is None or self.judge_model is None
        ):
            raise ValueError(
                "LlmBindings.debate_orchestrator requires both critic_model "
                "and judge_model to be bound"
            )


@dataclass(frozen=True, slots=True)
class Container:
    """Bag of already-bound seams handed to the rest of the app.

    Immutable so a caller cannot silently rewire a seam mid-flight. A
    fork MAY produce a new :class:`Container` via
    :func:`dataclasses.replace` to substitute individual seams without
    editing ``core/``.
    """

    config: AppConfig
    schema_registry: SchemaRegistry
    contract_validator: ContractValidator
    event_validator: EventValidator
    exemption_registry: ExemptionRegistry
    feasibility_probes: tuple[FeasibilityProbe, ...] = ()
    llm_bindings: LlmBindings | None = field(default=None)

    def require_llm_bindings(self) -> LlmBindings:
        """Return :attr:`llm_bindings` or raise :class:`LlmBindingsUnavailableError`."""
        if self.llm_bindings is None:
            raise LlmBindingsUnavailableError(
                "Container.llm_bindings is None. In llm.mode='azure' the "
                "entry point MUST call bind_azure_llm_bindings() before "
                "core code invokes the T1/T2 tiers."
            )
        return self.llm_bindings


def _local_fake_llm_bindings() -> LlmBindings:
    """Build deterministic fakes for `llm.mode='local-fake'`."""
    return LlmBindings(
        embedding_model=DeterministicEmbeddingModel(),
        cross_check_models=(
            MatchTypeCrossCheckModel(model_id="fake-primary"),
            MatchTypeCrossCheckModel(model_id="fake-secondary"),
        ),
    )


def default_container(config: AppConfig) -> Container:
    """Return the upstream default binding of every seam.

    The caller MUST hand in an already-validated :class:`AppConfig`. Building
    one from the process environment is the entry point's job - see
    :func:`default_container_from_env`.

    A fork MAY:

    - construct a :class:`Container` with a different :class:`SchemaRegistry`
      (e.g. a remote registry adapter),
    - or wrap :func:`default_container` and override individual fields via
      :func:`dataclasses.replace`.

    This function MUST NOT be called from within ``core/``.
    """
    registry: SchemaRegistry = PackageResourceSchemaRegistry()
    contract_v: ContractValidator = JsonSchemaContractValidator(registry)
    event_v: EventValidator = JsonSchemaEventValidator(contract_v)
    llm = _local_fake_llm_bindings() if config.llm.mode == LlmMode.LOCAL_FAKE else None
    return Container(
        config=config,
        schema_registry=registry,
        contract_validator=contract_v,
        event_validator=event_v,
        exemption_registry=empty_exemption_registry(),
        feasibility_probes=(),
        llm_bindings=llm,
    )


def bind_azure_llm_bindings(
    container: Container,
    *,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    endpoint: str,
    system_prompt: str,
    tool_registry: Any | None = None,
    tool_executor: Any | None = None,
    prompt_composer: Any | None = None,
    scope_resolver: Any | None = None,
    critic_system_prompt: str | None = None,
    judge_system_prompt: str | None = None,
) -> Container:
    """Return a new :class:`Container` with the Azure OpenAI adapters attached.

    Reads ``resolved-models.json`` from the path in
    ``container.config.llm.resolved_models_path``, filters out
    ``hil-only`` capabilities (they never bind to a model), and constructs
    :class:`~fdai.delivery.azure.llm.embeddings.AzureOpenAIEmbeddingModel`
    + :class:`~fdai.delivery.azure.llm.cross_check.AzureOpenAICrossCheckModel`
    entries for the T1 embedding + T2 reasoners.

    Deliberately kept a plain function (not a method) so ``core/`` can
    never call it accidentally: the imports below pull in
    ``delivery.azure.llm``, which is prohibited from ``core/``.

    ``system_prompt``: REQUIRED as of Wave 2 of the evolving-system-prompt
    design (docs/roadmap/prompt-composition.md). The composition root
    MUST produce this string by calling
    :class:`~fdai.core.prompts.PromptComposer` against the
    ``rule-catalog/prompts/`` tree. Both cross-check reasoners receive
    the same text so mixed-model cross-check sees identical instruction
    context - only the model differs. When ``prompt_composer`` is also
    provided (Wave 3 step C-2), the static ``system_prompt`` becomes a
    startup-safety fallback and each ``propose()`` re-composes per event.

    ``tool_registry`` + ``tool_executor``: OPTIONAL as of Wave 2.5-B
    step 2b. When both are provided, the adapter advertises every
    enforce-mode tool via OpenAI's ``tools`` parameter and routes
    model-issued ``tool_calls`` through the executor. Both MUST be
    provided together; the adapter refuses a half-wired setup.
    ``core/`` never touches ``delivery.azure.llm``, so the parameter
    types are erased at this boundary and enforced downstream.

    ``prompt_composer`` + ``scope_resolver`` (Wave 3 step C-2): OPTIONAL.
    When ``prompt_composer`` is supplied, each T2 reasoner uses it to
    re-compose its system prompt per event (against the capability id
    matching its role). ``scope_resolver`` MAY additionally derive an
    :class:`~fdai.core.operator_memory.OperatorScope` from the
    candidate so operator-memory entries are injected at the right
    resource-group / resource layer. ``scope_resolver`` without a
    composer is rejected downstream (nothing to feed).

    ``critic_system_prompt`` (Wave 4 beta-2): OPTIONAL. When both this
    string is supplied AND the ``t2.critic`` capability resolves in
    ``resolved-models.json``, the composition binds a live
    :class:`~fdai.delivery.azure.llm.critic.AzureOpenAICriticModel`
    on ``LlmBindings.critic_model``. Both conditions must hold - a
    fork that opts out of the Critic by omitting the capability keeps
    the field ``None`` and the future debate orchestrator degrades
    gracefully.

    ``judge_system_prompt`` (Wave 4.5 delta-1): OPTIONAL. Analogous to
    ``critic_system_prompt`` but paired with the ``t1.judge``
    capability. When both this string is supplied AND ``t1.judge``
    resolves, the composition binds
    :class:`~fdai.delivery.azure.llm.judge.AzureOpenAIJudgeModel`
    on ``LlmBindings.judge_model``. When BOTH ``critic_model`` AND
    ``judge_model`` land, a default :class:`DebateOrchestrator`
    (max_rounds=1) is auto-constructed on
    ``LlmBindings.debate_orchestrator``; otherwise the field stays
    ``None`` and Wave 4.5's live-integration path degrades to the
    pre-Wave-4 cross-check flow.
    """
    from .delivery.azure.llm.critic import (
        AzureOpenAICriticModel,
        AzureOpenAICriticModelConfig,
    )
    from .delivery.azure.llm.cross_check import (
        AzureOpenAICrossCheckModel,
        AzureOpenAICrossCheckModelConfig,
    )
    from .delivery.azure.llm.embeddings import (
        AzureOpenAIEmbeddingModel,
        AzureOpenAIEmbeddingModelConfig,
    )
    from .delivery.azure.llm.judge import (
        AzureOpenAIJudgeModel,
        AzureOpenAIJudgeModelConfig,
    )

    if not system_prompt:
        raise ValueError(
            "bind_azure_llm_bindings requires a non-empty system_prompt - "
            "compose it via fdai.core.prompts.PromptComposer"
        )

    if container.config.llm.mode != LlmMode.AZURE:
        raise ValueError(
            f"bind_azure_llm_bindings called but llm.mode="
            f"{container.config.llm.mode!r} - only 'azure' is supported"
        )
    if container.config.llm.resolved_models_path is None:
        raise ValueError(
            "bind_azure_llm_bindings requires llm.resolved_models_path (validated earlier)"
        )

    resolved = _load_resolved_models(container.config.llm.resolved_models_path)
    embedding_cap = _capability(resolved, "t1.embedding")
    primary_cap = _capability(resolved, "t2.reasoner.primary")
    secondary_cap = _capability(resolved, "t2.reasoner.secondary")

    if embedding_cap is None:
        raise LlmBindingsUnavailableError(
            "resolved-models.json lacks a bindable 't1.embedding' capability"
        )
    if primary_cap is None or secondary_cap is None:
        # `hil-only` mode is a designed opt-out - the region cannot host
        # a distinct-publisher secondary reasoner. Bind the primary (or a
        # deterministic fake if even the primary is missing) plus an
        # always-disagree fake secondary so every T2 quality-gate call
        # returns DISAGREE and the pipeline routes to HIL by design.
        if resolved.mixed_model_mode == "hil-only":
            primary_model: CrossCheckModel
            if primary_cap is not None:
                primary_model = AzureOpenAICrossCheckModel(
                    identity=identity,
                    http_client=http_client,
                    config=AzureOpenAICrossCheckModelConfig(
                        endpoint=endpoint,
                        deployment=primary_cap.name,
                        system_prompt=system_prompt,
                    ),
                    tool_registry=tool_registry,
                    tool_executor=tool_executor,
                    prompt_composer=prompt_composer,
                    capability_id=("t2.reasoner.primary" if prompt_composer is not None else None),
                    scope_resolver=scope_resolver,
                )
            else:
                primary_model = MatchTypeCrossCheckModel(model_id="hil-only-primary-noop")
            embedding = AzureOpenAIEmbeddingModel(
                identity=identity,
                http_client=http_client,
                config=AzureOpenAIEmbeddingModelConfig(
                    endpoint=endpoint,
                    deployment=embedding_cap.name,
                    dim=_default_dim_for_family(embedding_cap.family or ""),
                ),
            )
            bindings = LlmBindings(
                embedding_model=embedding,
                cross_check_models=(
                    primary_model,
                    MismatchCrossCheckModel(model_id="hil-only-force-disagree"),
                ),
            )
            return replace(container, llm_bindings=bindings)

        raise LlmBindingsUnavailableError(
            "resolved-models.json lacks bindable T2 reasoner capabilities - "
            "the quality gate cannot form a quorum"
        )

    embedding = AzureOpenAIEmbeddingModel(
        identity=identity,
        http_client=http_client,
        config=AzureOpenAIEmbeddingModelConfig(
            endpoint=endpoint,
            deployment=embedding_cap.name,
            dim=_default_dim_for_family(embedding_cap.family or ""),
        ),
    )
    primary = AzureOpenAICrossCheckModel(
        identity=identity,
        http_client=http_client,
        config=AzureOpenAICrossCheckModelConfig(
            endpoint=endpoint,
            deployment=primary_cap.name,
            system_prompt=system_prompt,
        ),
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        prompt_composer=prompt_composer,
        capability_id=("t2.reasoner.primary" if prompt_composer is not None else None),
        scope_resolver=scope_resolver,
    )
    secondary = AzureOpenAICrossCheckModel(
        identity=identity,
        http_client=http_client,
        config=AzureOpenAICrossCheckModelConfig(
            endpoint=endpoint,
            deployment=secondary_cap.name,
            system_prompt=system_prompt,
        ),
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        prompt_composer=prompt_composer,
        capability_id=("t2.reasoner.secondary" if prompt_composer is not None else None),
        scope_resolver=scope_resolver,
    )
    # Wave 4 beta-2: opt-in Critic binding. Only bind when both the
    # ``t2.critic`` capability resolves AND the caller supplied a
    # ``critic_system_prompt``. A fork that omits either keeps the
    # field ``None`` and the future debate orchestrator degrades to
    # the pre-Wave-4 cross-check flow.
    critic_cap = _capability(resolved, "t2.critic")
    critic_model: CriticModel | None = None
    if critic_cap is not None and critic_system_prompt:
        critic_model = AzureOpenAICriticModel(
            identity=identity,
            http_client=http_client,
            config=AzureOpenAICriticModelConfig(
                endpoint=endpoint,
                deployment=critic_cap.name,
                system_prompt=critic_system_prompt,
            ),
        )
    # Wave 4.5 delta-1: opt-in Judge binding + auto-constructed
    # DebateOrchestrator. Judge binds when ``t1.judge`` resolves AND
    # ``judge_system_prompt`` is supplied. The orchestrator is built
    # only when BOTH role models are bound; a fork that opts out of
    # either role keeps ``debate_orchestrator = None`` and the caller
    # falls back to the cross-check quorum path.
    judge_cap = _capability(resolved, "t1.judge")
    judge_model: JudgeModel | None = None
    if judge_cap is not None and judge_system_prompt:
        judge_model = AzureOpenAIJudgeModel(
            identity=identity,
            http_client=http_client,
            config=AzureOpenAIJudgeModelConfig(
                endpoint=endpoint,
                deployment=judge_cap.name,
                system_prompt=judge_system_prompt,
            ),
        )
    debate_orchestrator: DebateOrchestrator | None = None
    if critic_model is not None and judge_model is not None:
        debate_orchestrator = DebateOrchestrator(
            critic=critic_model,
            judge=judge_model,
            config=DebateOrchestratorConfig(max_rounds=1),
        )
    bindings = LlmBindings(
        embedding_model=embedding,
        cross_check_models=(primary, secondary),
        critic_model=critic_model,
        judge_model=judge_model,
        debate_orchestrator=debate_orchestrator,
    )
    return replace(container, llm_bindings=bindings)


def _load_resolved_models(path_or_ref: str) -> ResolvedModels:
    """Load ``resolved-models.json``.

    Two shapes are accepted:

    - a filesystem path - used when Container Apps mounts the KV secret
      as a file under ``/mnt/secrets/`` (or when a dev laptop writes the
      resolver output next to the checkout);
    - an inline JSON document - used when the Container App reads the
      secret through a ``secretRef`` env var (no volume-mount extension
      required). Detected by a leading ``{`` after stripping whitespace.

    A future Key-Vault-backed loader lands with the reconciler; for now
    the filesystem / env-var pair covers the day-zero deployment.
    """
    stripped = path_or_ref.strip()
    if stripped.startswith("{"):
        return ResolvedModels.from_json(stripped)
    path = Path(path_or_ref)
    if not path.exists():
        raise LlmBindingsUnavailableError(
            f"resolved-models.json not found at {path_or_ref!r}. "
            "Run the bootstrap resolver first (llm_resolver_cli)."
        )
    return ResolvedModels.from_json(path.read_text(encoding="utf-8"))


def _capability(resolved: ResolvedModels, name: str) -> ResolvedCapability | None:
    """Return the resolved capability iff it is bindable (not hil-only)."""
    for cap in resolved.capabilities:
        if cap.name != name:
            continue
        if cap.status is CapabilityStatus.HIL_ONLY:
            return None
        return cap
    return None


def _default_dim_for_family(family: str) -> int:
    """Sensible dim defaults for the shipped embedding families.

    A future resolver revision MAY carry the vector dim on
    ``ResolvedCapability`` directly; today we keep the mapping small.
    """
    return {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
    }.get(family, 1536)


def default_container_from_env() -> Container:
    """Entry-point convenience: load config from env, then bind every seam.

    A missing / invalid env raises :class:`fdai.shared.config.ConfigError`
    with every problem listed. Never returns a partially-built container.

    Side-effect: configures process-wide telemetry (JSON logging + OTel
    tracer/meter providers) before returning. Idempotent.
    """
    config = load_config_from_env()
    # Wire telemetry once, before any provider emits log or span.
    from .shared.telemetry.setup import configure_telemetry

    configure_telemetry(config)
    return default_container(config)


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
    """

    endpoint: str
    catalog_root: Path
    operator_memory_store: OperatorMemoryStore
    tool_providers: Mapping[str, Any] | None = None
    scope_resolver: Any | None = None

    def __post_init__(self) -> None:
        if not self.endpoint:
            raise ValueError("AzureWireOverrides.endpoint MUST be non-empty")
        if self.operator_memory_store is None:
            raise ValueError(
                "AzureWireOverrides.operator_memory_store MUST be a concrete "
                "OperatorMemoryStore - pass InMemoryOperatorMemoryStore() "
                "explicitly if you do not want durability"
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

    from .core.prompts import DefaultPromptComposer, FileSystemPromptRegistry
    from .core.tools import DefaultToolExecutor, FileSystemToolRegistry

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

    return bind_azure_llm_bindings(
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
    )


__all__ = [
    "AzureWireOverrides",
    "Container",
    "LlmBindings",
    "LlmBindingsUnavailableError",
    "bind_azure_llm_bindings",
    "default_container",
    "default_container_from_env",
    "wire_azure_container",
]
