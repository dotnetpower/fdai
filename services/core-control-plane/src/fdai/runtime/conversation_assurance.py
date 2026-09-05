"""Runtime composition for autonomous conversation assurance."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from fdai.agents import PantheonRuntime
from fdai.core.conversation_assurance import (
    ConversationAssuranceCoordinator,
    ConversationAssuranceEvaluator,
    ConversationAssuranceLedger,
    MixedFamilyAssuranceReviewer,
)
from fdai.core.metering import MeteringEmitter, MeteringSink
from fdai.core.metering.budget import (
    BudgetLedger,
    InMemoryBudgetLedger,
    ModelBudget,
)
from fdai.core.metering.pricing import PricingTable
from fdai.core.prompts import FileSystemPromptRegistry, PromptLayer
from fdai.delivery.azure.llm.conversation_assurance import (
    AzureConversationAssuranceEvaluator,
    AzureConversationAssuranceEvaluatorConfig,
)
from fdai.delivery.persistence import (
    PostgresConversationAssuranceLedger,
    PostgresConversationAssuranceLedgerConfig,
)
from fdai.rule_catalog.schema.llm_resolver import CapabilityStatus, ResolvedModels
from fdai.shared.providers.workload_identity import WorkloadIdentity

from .pantheon_conversation_assurance import (
    RuntimePantheonConversationAssurance,
    runtime_source_identity,
)

_PRIMARY = "t2.reasoner.primary"
_SECONDARY = "t2.reasoner.secondary"
_TIE_BREAKER = "t2.reasoner.escalated"
_ASSESSMENT_CALL_BUDGET = 3
_ASSESSMENT_COST_BUDGET_MICROUSD = 150_000


def build_conversation_assurance_coordinator(
    *,
    ledger: ConversationAssuranceLedger,
    budget: BudgetLedger | None,
    evaluators: tuple[ConversationAssuranceEvaluator, ...],
) -> ConversationAssuranceCoordinator:
    reviewer = build_conversation_assurance_reviewer(
        budget=budget,
        evaluators=evaluators,
    )
    return ConversationAssuranceCoordinator(
        ledger=ledger,
        reviewer=reviewer,
        rubric_version="1.0.0",
    )


def build_conversation_assurance_reviewer(
    *,
    budget: BudgetLedger | None,
    evaluators: tuple[ConversationAssuranceEvaluator, ...],
) -> MixedFamilyAssuranceReviewer | None:
    if len(evaluators) < 2:
        return None
    return MixedFamilyAssuranceReviewer(
        first=evaluators[0],
        second=evaluators[1],
        tie_breaker=evaluators[2] if len(evaluators) >= 3 else None,
        budget=budget,
        prospective_cost_microusd_per_call=max(
            item.prospective_cost_microusd for item in evaluators
        ),
    )


def build_azure_conversation_assurance_evaluators(
    *,
    repo_root: Path,
    resolved_models_path: str | None = None,
    resolved_models: ResolvedModels | None = None,
    held_capabilities: frozenset[str] = frozenset(),
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    pricing: PricingTable,
    metering_sink: MeteringSink,
) -> tuple[ConversationAssuranceEvaluator, ...]:
    if resolved_models is None:
        if resolved_models_path is None:
            return ()
        try:
            resolved_models = _load_resolved_models(resolved_models_path)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return ()
    resolved = resolved_models
    if resolved.narrator is None or not resolved.narrator.endpoint:
        return ()
    capabilities = {item.name: item for item in resolved.capabilities}
    selected = [capabilities.get(_PRIMARY), capabilities.get(_SECONDARY)]
    if any(
        item is None
        or item.name in held_capabilities
        or item.status is CapabilityStatus.HIL_ONLY
        or item.family is None
        or item.publisher is None
        for item in selected
    ):
        return ()
    tie = capabilities.get(_TIE_BREAKER)
    if (
        tie is not None
        and tie.name not in held_capabilities
        and tie.status is not CapabilityStatus.HIL_ONLY
        and tie.family is not None
        and tie.publisher is not None
    ):
        selected.append(tie)
    concrete = tuple(item for item in selected if item is not None)
    if len({item.family for item in concrete}) != len(concrete):
        return ()
    prompt = max(
        (
            artifact
            for artifact in FileSystemPromptRegistry(repo_root / "rule-catalog").artifacts()
            if artifact.id == "conversation-assurance" and artifact.layer is PromptLayer.RUBRIC
        ),
        key=lambda artifact: artifact.version,
        default=None,
    )
    if prompt is None:
        return ()
    return tuple(
        AzureConversationAssuranceEvaluator(
            identity=identity,
            http_client=http_client,
            config=AzureConversationAssuranceEvaluatorConfig(
                endpoint=resolved.narrator.endpoint,
                deployment=item.name,
                model_identity=f"{item.publisher}:{item.family}:{item.name}",
                model_family=item.family or "",
                system_prompt=prompt.body,
            ),
            metering=MeteringEmitter(
                sink=metering_sink,
                capability_id="conversation.assurance",
                model_key=item.family or "",
                tier="T2",
                pricing=pricing,
            ),
            pricing=pricing,
        )
        for item in concrete
    )


def build_runtime_pantheon_conversation_assurance(
    *,
    pantheon: PantheonRuntime | None,
    repo_root: Path,
    environment: dict[str, str],
    dsn: str | None,
    resolved_models: ResolvedModels | None,
    held_capabilities: frozenset[str] = frozenset(),
    identity: WorkloadIdentity | None,
    http_client: httpx.AsyncClient | None,
    pricing: PricingTable | None,
    metering_sink: MeteringSink | None,
) -> RuntimePantheonConversationAssurance | None:
    """Bind the live diagnostic only when its durable and revision inputs exist."""

    source_identity = runtime_source_identity(repo_root, environment)
    if pantheon is None or not dsn or source_identity is None:
        return None
    evaluators: tuple[ConversationAssuranceEvaluator, ...] = ()
    if (
        resolved_models is not None
        and identity is not None
        and http_client is not None
        and pricing is not None
        and metering_sink is not None
    ):
        evaluators = build_azure_conversation_assurance_evaluators(
            repo_root=repo_root,
            resolved_models=resolved_models,
            held_capabilities=held_capabilities,
            identity=identity,
            http_client=http_client,
            pricing=pricing,
            metering_sink=metering_sink,
        )
    budget = InMemoryBudgetLedger(
        ModelBudget(
            max_calls_per_correlation=_ASSESSMENT_CALL_BUDGET,
            max_cost_microusd_per_correlation=_ASSESSMENT_COST_BUDGET_MICROUSD,
        )
    )
    coordinator = build_conversation_assurance_coordinator(
        ledger=PostgresConversationAssuranceLedger(
            config=PostgresConversationAssuranceLedgerConfig(dsn=dsn)
        ),
        budget=budget,
        evaluators=evaluators,
    )
    source_revision, source_content_digest = source_identity
    return RuntimePantheonConversationAssurance(
        pantheon=pantheon,
        coordinator=coordinator,
        source_revision=source_revision,
        source_content_digest=source_content_digest,
    )


def _load_resolved_models(path_or_json: str) -> ResolvedModels:
    stripped = path_or_json.strip()
    text = stripped if stripped.startswith("{") else Path(stripped).read_text()
    return ResolvedModels.from_json(text)


__all__ = [
    "build_azure_conversation_assurance_evaluators",
    "build_conversation_assurance_coordinator",
    "build_conversation_assurance_reviewer",
    "build_runtime_pantheon_conversation_assurance",
]
