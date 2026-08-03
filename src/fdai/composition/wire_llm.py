"""Azure OpenAI LlmBindings wiring (extracted from composition.py, G-3).

Contains ``bind_azure_llm_bindings`` - the single largest binder in the
old monolith (~308 LOC). It reads ``resolved-models.json``, builds the
per-capability Azure OpenAI adapters (embedding + T2 cross-check + optional
Critic + optional Judge + optional RCA reasoner), auto-constructs the
debate orchestrator when both Critic and Judge bind, and returns a new
:class:`~fdai.composition.Container` with ``llm_bindings`` populated.

Kept a plain function (not a method) so ``core/`` can never call it
accidentally - the imports inside pull ``delivery.azure.llm``, which
is prohibited from ``core/``.

Public API stays at :mod:`fdai.composition` via re-export from the
package facade.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

import httpx

from ..core.metering.emitter import MeteringEmitter
from ..core.metering.pricing import PricingTable
from ..core.metering.sink import MeteringSink
from ..core.quality_gate.critic import CriticModel
from ..core.quality_gate.debate import DebateOrchestrator, DebateOrchestratorConfig
from ..core.quality_gate.gate import CrossCheckModel
from ..core.quality_gate.judge import JudgeModel
from ..core.quality_gate.testing import MatchTypeCrossCheckModel, MismatchCrossCheckModel
from ..core.rca import LlmRcaReasoner, RcaReasoner
from ..core.tiers.t2_reasoning import BoundedFailoverT2Proposer, T2Proposer
from ..core.tiers.t2_reasoning.testing import AbstainingT2Proposer
from ..rule_catalog.schema.llm_resolver import ResolvedCapability
from ..rule_catalog.schema.model_endpoint import ModelAuthKind, ModelEndpointBinding
from ..shared.config.models import LlmMode
from ..shared.providers.workload_identity import WorkloadIdentity
from ._helpers import (
    Container,  # re-export for typing
    LlmBindings,
    LlmBindingsUnavailableError,
    _capability,
    _default_dim_for_family,
    _load_resolved_models,
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
    rca_system_prompt: str | None = None,
    proposer_system_prompt: str | None = None,
    metering_sink: MeteringSink | None = None,
    pricing: PricingTable | None = None,
    model_health_sink: Any | None = None,
    endpoint_resolver: Callable[[str], str] | None = None,
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
    design (docs/roadmap/decisioning/prompt-composition.md). The composition root
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
    from ..delivery.azure.llm.critic import (
        AzureOpenAICriticModel,
        AzureOpenAICriticModelConfig,
    )
    from ..delivery.azure.llm.cross_check import (
        AzureOpenAICrossCheckModel,
        AzureOpenAICrossCheckModelConfig,
    )
    from ..delivery.azure.llm.embeddings import (
        AzureOpenAIEmbeddingModel,
        AzureOpenAIEmbeddingModelConfig,
    )
    from ..delivery.azure.llm.judge import (
        AzureOpenAIJudgeModel,
        AzureOpenAIJudgeModelConfig,
    )
    from ..delivery.azure.llm.latency_routed_cross_check import (
        LatencyRoutedCrossCheckModel,
    )
    from ..delivery.azure.llm.proposer import (
        AzureOpenAIProposer,
        AzureOpenAIProposerConfig,
    )
    from ..delivery.azure.llm.rca_model import (
        AzureOpenAIRcaModel,
        AzureOpenAIRcaModelConfig,
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
    endpoint_bindings = {binding.capability: binding for binding in resolved.endpoint_bindings}
    supported_binding_capabilities = {
        "t1.embedding",
        "t1.judge",
        "t2.critic",
        "t2.rca",
        "t2.reasoner.primary",
        "t2.reasoner.secondary",
        "t2.ontology.council.alpha",
        "t2.ontology.council.beta",
        "t2.ontology.council.gamma",
    }
    unsupported_bindings = sorted(set(endpoint_bindings) - supported_binding_capabilities)
    if unsupported_bindings:
        raise LlmBindingsUnavailableError(
            "resolved endpoint bindings include capabilities whose gateway transport is not "
            f"implemented: {', '.join(unsupported_bindings)}"
        )
    if endpoint_bindings and endpoint_resolver is None:
        raise LlmBindingsUnavailableError(
            "resolved endpoint bindings require an endpoint_ref resolver at composition"
        )
    if (
        any(binding.route_kind.value == "apim-gateway" for binding in endpoint_bindings.values())
        and model_health_sink is None
    ):
        raise LlmBindingsUnavailableError(
            "APIM endpoint bindings require a durable model health transition sink"
        )
    if "t2.reasoner.primary" in endpoint_bindings and resolved.reasoner_primary_candidates:
        raise LlmBindingsUnavailableError(
            "a bound T2 primary endpoint cannot also use the legacy primary latency pool"
        )

    def _target(
        capability_id: str,
        *,
        legacy_deployment: str,
        legacy_api_version: str,
    ) -> dict[str, Any]:
        binding = endpoint_bindings.get(capability_id)
        if binding is None:
            return {
                "endpoint": endpoint,
                "deployment": legacy_deployment,
                "api_version": legacy_api_version,
            }
        return _binding_target(binding, endpoint_resolver)

    def _emitter_for(
        capability_id: str, cap: ResolvedCapability, tier: str
    ) -> MeteringEmitter | None:
        """Build a metering emitter for one capability, or None when metering is off.

        ``model_key`` is the resolved model family (``gpt-4o``, matching
        ``rule-catalog/llm-pricing.yaml``); it falls back to the
        capability/deployment name when no family is recorded so an
        unpriced call is still counted (with an unknown cost).
        """
        if metering_sink is None:
            return None
        return MeteringEmitter(
            sink=metering_sink,
            capability_id=capability_id,
            model_key=(cap.family or cap.name),
            tier=tier,
            pricing=pricing,
        )

    rca_cap = _capability(resolved, "t2.rca")
    rca_reasoner: RcaReasoner | None = None
    if rca_cap is not None and rca_system_prompt:
        rca_reasoner = LlmRcaReasoner(
            model=AzureOpenAIRcaModel(
                identity=identity,
                http_client=http_client,
                config=AzureOpenAIRcaModelConfig(
                    **_target(
                        "t2.rca",
                        legacy_deployment=rca_cap.name,
                        legacy_api_version="2024-06-01",
                    ),
                    system_prompt=rca_system_prompt,
                    model_family=rca_cap.family,
                ),
                metering=_emitter_for("t2.rca", rca_cap, "T2"),
            )
        )

    proposer: T2Proposer = (
        AzureOpenAIProposer(
            identity=identity,
            http_client=http_client,
            config=AzureOpenAIProposerConfig(
                **_target(
                    "t2.reasoner.primary",
                    legacy_deployment=primary_cap.name,
                    legacy_api_version="2024-06-01",
                ),
                system_prompt=proposer_system_prompt,
                model_family=primary_cap.family,
            ),
            metering=_emitter_for("t2.reasoner.primary", primary_cap, "T2"),
            gateway_route_sink=model_health_sink,
        )
        if primary_cap is not None and proposer_system_prompt
        else AbstainingT2Proposer()
    )

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
                        **_target(
                            "t2.reasoner.primary",
                            legacy_deployment=primary_cap.name,
                            legacy_api_version="2024-06-01",
                        ),
                        system_prompt=system_prompt,
                        model_family=primary_cap.family,
                    ),
                    tool_registry=tool_registry,
                    tool_executor=tool_executor,
                    prompt_composer=prompt_composer,
                    capability_id=("t2.reasoner.primary" if prompt_composer is not None else None),
                    scope_resolver=scope_resolver,
                    metering=_emitter_for("t2.reasoner.primary", primary_cap, "T2"),
                    gateway_route_sink=model_health_sink,
                )
            else:
                primary_model = MatchTypeCrossCheckModel(model_id="hil-only-primary-noop")
            embedding = AzureOpenAIEmbeddingModel(
                identity=identity,
                http_client=http_client,
                config=AzureOpenAIEmbeddingModelConfig(
                    **_target(
                        "t1.embedding",
                        legacy_deployment=embedding_cap.name,
                        legacy_api_version="2024-06-01",
                    ),
                    dim=_default_dim_for_family(embedding_cap.family or ""),
                ),
                metering=_emitter_for("t1.embedding", embedding_cap, "T1"),
            )
            bindings = LlmBindings(
                embedding_model=embedding,
                cross_check_models=(
                    primary_model,
                    MismatchCrossCheckModel(model_id="hil-only-force-disagree"),
                ),
                rca_reasoner=rca_reasoner,
                t2_proposer=proposer,
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
            **_target(
                "t1.embedding",
                legacy_deployment=embedding_cap.name,
                legacy_api_version="2024-06-01",
            ),
            dim=_default_dim_for_family(embedding_cap.family or ""),
        ),
        metering=_emitter_for("t1.embedding", embedding_cap, "T1"),
    )
    primary: CrossCheckModel = AzureOpenAICrossCheckModel(
        identity=identity,
        http_client=http_client,
        config=AzureOpenAICrossCheckModelConfig(
            **_target(
                "t2.reasoner.primary",
                legacy_deployment=primary_cap.name,
                legacy_api_version="2024-06-01",
            ),
            system_prompt=system_prompt,
            model_family=primary_cap.family,
        ),
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        prompt_composer=prompt_composer,
        capability_id=("t2.reasoner.primary" if prompt_composer is not None else None),
        scope_resolver=scope_resolver,
        metering=_emitter_for("t2.reasoner.primary", primary_cap, "T2"),
        gateway_route_sink=model_health_sink,
    )
    # T2 Primary Latency Pool (invariant-safe, opt-in). When the flag is on AND
    # the resolver emitted >= 2 same-publisher candidates, wrap the primary
    # proposer so each cross-check call routes to the fastest deployment. The
    # publisher never changes (``collect_primary_candidates`` guarantees a
    # single publisher), so the mixed-model invariant
    # (primary.publisher != secondary.publisher) is preserved. Off by default,
    # shadow-first - see docs/roadmap/architecture/llm-strategy.md
    # (T2 Primary Latency Pool).
    primary_pool = resolved.reasoner_primary_candidates
    if container.config.llm.t2_primary_latency_routing and len(primary_pool) >= 2:
        # Attribute each pool member's metering to its OWN model family (the
        # ``t2primary-<family>`` deployment capability carries it), so a
        # gpt-4.1 member is not priced as gpt-4o. Falls back to primary_cap
        # when the deployment companion capability is absent (e.g. a
        # hand-authored resolved-models.json without --emit-primary-pool).
        _cap_by_name = {c.name: c for c in resolved.capabilities}
        pool_members: list[tuple[str, CrossCheckModel]] = [
            (
                cand.deployment,
                AzureOpenAICrossCheckModel(
                    identity=identity,
                    http_client=http_client,
                    config=AzureOpenAICrossCheckModelConfig(
                        endpoint=cand.endpoint,
                        deployment=cand.deployment,
                        system_prompt=system_prompt,
                        api_version=cand.api_version,
                        model_family=_cap_by_name.get(cand.deployment, primary_cap).family,
                    ),
                    tool_registry=tool_registry,
                    tool_executor=tool_executor,
                    prompt_composer=prompt_composer,
                    capability_id=("t2.reasoner.primary" if prompt_composer is not None else None),
                    scope_resolver=scope_resolver,
                    metering=_emitter_for(
                        "t2.reasoner.primary",
                        _cap_by_name.get(cand.deployment, primary_cap),
                        "T2",
                    ),
                ),
            )
            for cand in primary_pool
        ]
        primary = LatencyRoutedCrossCheckModel(
            candidates=pool_members,
            transition_sink=model_health_sink,
        )
    secondary = AzureOpenAICrossCheckModel(
        identity=identity,
        http_client=http_client,
        config=AzureOpenAICrossCheckModelConfig(
            **_target(
                "t2.reasoner.secondary",
                legacy_deployment=secondary_cap.name,
                legacy_api_version="2024-06-01",
            ),
            system_prompt=system_prompt,
            model_family=secondary_cap.family,
        ),
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        prompt_composer=prompt_composer,
        capability_id=("t2.reasoner.secondary" if prompt_composer is not None else None),
        scope_resolver=scope_resolver,
        metering=_emitter_for("t2.reasoner.secondary", secondary_cap, "T2"),
        gateway_route_sink=model_health_sink,
    )
    if proposer_system_prompt:
        secondary_proposer = AzureOpenAIProposer(
            identity=identity,
            http_client=http_client,
            config=AzureOpenAIProposerConfig(
                **_target(
                    "t2.reasoner.secondary",
                    legacy_deployment=secondary_cap.name,
                    legacy_api_version="2024-06-01",
                ),
                system_prompt=proposer_system_prompt,
                model_family=secondary_cap.family,
            ),
            metering=_emitter_for("t2.reasoner.secondary", secondary_cap, "T2"),
            gateway_route_sink=model_health_sink,
        )
        proposer = BoundedFailoverT2Proposer(
            candidates=(("primary", proposer), ("secondary", secondary_proposer))
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
                **_target(
                    "t2.critic",
                    legacy_deployment=critic_cap.name,
                    legacy_api_version="2024-06-01",
                ),
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
                **_target(
                    "t1.judge",
                    legacy_deployment=judge_cap.name,
                    legacy_api_version="2024-06-01",
                ),
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
        rca_reasoner=rca_reasoner,
        t2_proposer=proposer,
    )
    return replace(container, llm_bindings=bindings)


def _binding_target(
    binding: ModelEndpointBinding,
    endpoint_resolver: Callable[[str], str] | None,
) -> dict[str, Any]:
    if endpoint_resolver is None:  # pragma: no cover - guarded by caller
        raise LlmBindingsUnavailableError("endpoint_ref resolver is unavailable")
    if binding.auth_kind is not ModelAuthKind.ENTRA or binding.auth_audience is None:
        raise LlmBindingsUnavailableError(
            f"endpoint binding {binding.binding_id!r} requires unsupported auth kind "
            f"{binding.auth_kind.value!r}; runtime model bindings require Entra auth"
        )
    endpoint = endpoint_resolver(binding.endpoint_ref)
    if not endpoint:
        raise LlmBindingsUnavailableError(
            f"endpoint binding {binding.binding_id!r} resolved to an empty endpoint"
        )
    return {
        "endpoint": endpoint,
        "deployment": binding.deployment,
        "api_version": binding.api_version or "2024-06-01",
        "api_style": binding.api_style,
        "auth_audience": binding.auth_audience,
        "route_kind": binding.route_kind,
        "binding_id": binding.binding_id,
    }
