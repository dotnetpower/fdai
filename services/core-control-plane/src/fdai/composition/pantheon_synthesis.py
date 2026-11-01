"""Bind the existing independent Azure models to verified read-only Pantheon synthesis."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from fdai.core.metering.budget import ModelBudget
from fdai.core.metering.pricing import PricingTable
from fdai.core.metering.sink import MeteringSink
from fdai.core.prompts import FileSystemPromptRegistry
from fdai.delivery.azure.llm.adaptive_answer import AzureOpenAIAdaptiveModel
from fdai.delivery.persistence.state_store_model_budget import StateStoreBudgetLedger
from fdai.delivery.verified_pantheon_synthesis import (
    VerifiedPantheonSynthesisVerifier,
    VerifiedPantheonSynthesizer,
)
from fdai.rule_catalog.schema.llm_resolver import ResolvedModels
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

from .adaptive_model_targets import resolved_model_config

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PantheonSynthesisBindings:
    synthesizer: VerifiedPantheonSynthesizer
    verifier: VerifiedPantheonSynthesisVerifier
    budget: ModelBudget
    ledger: StateStoreBudgetLedger
    model_key: str


def build_pantheon_synthesis(
    *,
    resolved: ResolvedModels | None,
    identity: WorkloadIdentity | None,
    http_client: httpx.AsyncClient | None,
    endpoint: str | None,
    endpoint_resolver: Callable[[str], str] | None,
    catalog_root: Path,
    state_store: StateStore,
    pricing: PricingTable | None,
    metering: MeteringSink | None,
    held_capabilities: frozenset[str] = frozenset(),
    timeout_seconds: float = 8.0,
) -> PantheonSynthesisBindings | None:
    if (
        resolved is None
        or identity is None
        or http_client is None
        or pricing is None
        or metering is None
    ):
        return None
    try:
        config = resolved_model_config(
            resolved,
            endpoint=endpoint,
            endpoint_resolver=endpoint_resolver,
            held_capabilities=held_capabilities,
            timeout_seconds=timeout_seconds,
            max_tokens=1024,
            primary_capability="t2.reasoner.primary",
            reviewer_capability="t2.reasoner.secondary",
        )
        if config is None:
            return None
        registry = FileSystemPromptRegistry(catalog_root)
        prompts = []
        for capability, expected in (
            ("conversation.pantheon.synthesize", "pantheon-synthesis"),
            ("conversation.pantheon.verify", "pantheon-review"),
        ):
            packs = registry.get_packs(capability)
            if len(packs) != 1 or packs[0].id != expected:
                raise ValueError("Pantheon synthesis requires exact reviewed prompt packs")
            prompts.append(packs[0].body)
        model = AzureOpenAIAdaptiveModel(identity=identity, http_client=http_client, config=config)
        budget = ModelBudget(max_calls_per_correlation=2)
        ledger = StateStoreBudgetLedger(state_store, budget)
        author_key = config.primary.target.deployment
        review_key = config.reviewer.target.deployment
        author_identity = f"{config.primary.publisher}:{config.primary.family}:{author_key}"
        reviewer_identity = f"{config.reviewer.publisher}:{config.reviewer.family}:{review_key}"
        return PantheonSynthesisBindings(
            synthesizer=VerifiedPantheonSynthesizer(
                model,
                prompts[0],
                author_identity,
                config.primary.family,
                author_key,
                ledger,
                pricing,
                metering,
            ),
            verifier=VerifiedPantheonSynthesisVerifier(
                model,
                prompts[1],
                author_identity,
                reviewer_identity,
                review_key,
                ledger,
                pricing,
                metering,
                budget,
            ),
            budget=budget,
            ledger=ledger,
            model_key=author_key,
        )
    except (LookupError, OSError, ValueError) as exc:
        _LOG.warning("pantheon_synthesis_unavailable", extra={"reason": type(exc).__name__})
        return None
