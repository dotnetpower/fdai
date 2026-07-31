"""Runtime composition for autonomous conversation assurance."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from fdai.core.conversation_assurance import (
    ConversationAssuranceCoordinator,
    ConversationAssuranceEvaluator,
    ConversationAssuranceLedger,
    MixedFamilyAssuranceReviewer,
)
from fdai.core.metering import MeteringEmitter, MeteringSink
from fdai.core.metering.budget import BudgetLedger
from fdai.core.metering.pricing import PricingTable
from fdai.core.prompts import FileSystemPromptRegistry, PromptLayer
from fdai.delivery.azure.llm.conversation_assurance import (
    AzureConversationAssuranceEvaluator,
    AzureConversationAssuranceEvaluatorConfig,
)
from fdai.rule_catalog.schema.llm_resolver import CapabilityStatus, ResolvedModels
from fdai.shared.providers.workload_identity import WorkloadIdentity

_PRIMARY = "t2.reasoner.primary"
_SECONDARY = "t2.reasoner.secondary"
_TIE_BREAKER = "t2.reasoner.escalated"


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
    resolved_models_path: str,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    pricing: PricingTable,
    metering_sink: MeteringSink,
) -> tuple[ConversationAssuranceEvaluator, ...]:
    try:
        resolved = _load_resolved_models(resolved_models_path)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return ()
    if resolved.narrator is None or not resolved.narrator.endpoint:
        return ()
    capabilities = {item.name: item for item in resolved.capabilities}
    selected = [capabilities.get(_PRIMARY), capabilities.get(_SECONDARY)]
    if any(
        item is None
        or item.status is CapabilityStatus.HIL_ONLY
        or item.family is None
        or item.publisher is None
        for item in selected
    ):
        return ()
    tie = capabilities.get(_TIE_BREAKER)
    if (
        tie is not None
        and tie.status is not CapabilityStatus.HIL_ONLY
        and tie.family is not None
        and tie.publisher is not None
    ):
        selected.append(tie)
    concrete = tuple(item for item in selected if item is not None)
    if len({item.family for item in concrete}) != len(concrete):
        return ()
    prompt = next(
        artifact
        for artifact in FileSystemPromptRegistry(repo_root / "rule-catalog").artifacts()
        if artifact.id == "conversation-assurance" and artifact.layer is PromptLayer.RUBRIC
    )
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


def _load_resolved_models(path_or_json: str) -> ResolvedModels:
    stripped = path_or_json.strip()
    text = stripped if stripped.startswith("{") else Path(stripped).read_text()
    return ResolvedModels.from_json(text)


__all__ = [
    "build_azure_conversation_assurance_evaluators",
    "build_conversation_assurance_coordinator",
    "build_conversation_assurance_reviewer",
]
