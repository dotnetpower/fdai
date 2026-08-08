"""Runtime composition for off-path post-turn improvement review."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from fdai.core.learning import (
    ConsensusPostTurnReviewer,
    GovernedPostTurnProposalRouter,
    InMemoryPostTurnReviewLedger,
    NoOpPostTurnReviewer,
    PostTurnEligibilityPolicy,
    PostTurnProposalModel,
    PostTurnReviewCoordinator,
    PostTurnReviewLedger,
    PostTurnReviewMetrics,
    RuleCandidateHint,
    RuleHintSubmitter,
)
from fdai.core.operator_memory import (
    InMemoryOperatorMemoryProposalStore,
    OperatorMemoryProposalWorkshop,
    OperatorMemoryStore,
)
from fdai.core.operator_memory.proposals import OperatorMemoryProposalStore
from fdai.core.prompts import FileSystemPromptRegistry
from fdai.core.skills import (
    InMemorySkillProposalStore,
    SkillProposalStore,
    SkillWorkshop,
)
from fdai.delivery.azure.llm.post_turn_reviewer import (
    AzureOpenAIPostTurnModel,
    AzureOpenAIPostTurnModelConfig,
)
from fdai.rule_catalog.schema.llm_resolver import CapabilityStatus, ResolvedModels
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

_CAPABILITIES = ("t2.reasoner.primary", "t2.reasoner.secondary")


class _DenyRuntimeReviewAuthorizer:
    def can_review(self, reviewer_id: str) -> bool:  # noqa: ARG002
        return False


class _StateStoreProposalAudit:
    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def append(self, event: Mapping[str, Any]) -> None:
        proposal_id = str(event.get("proposal_id") or "unknown")
        action_kind = str(event.get("action_kind") or "post-turn.proposal")
        await self._store.append_audit_entry(
            {
                **event,
                "correlation_id": proposal_id,
                "idempotency_key": f"{action_kind}:{proposal_id}",
                "mode": "shadow",
            }
        )


class _DeferredRuleHintSubmitter:
    def __init__(self) -> None:
        self._delegate: RuleHintSubmitter | None = None

    def bind(self, delegate: RuleHintSubmitter) -> None:
        if self._delegate is not None:
            raise RuntimeError("post-turn rule-hint submitter is already bound")
        self._delegate = delegate

    async def submit_rule_hint(
        self,
        hint: RuleCandidateHint,
        *,
        proposed_by: str,
        at: datetime,
    ) -> str:
        if self._delegate is None:
            raise RuntimeError("post-turn rule-hint submitter is unavailable")
        return await self._delegate.submit_rule_hint(hint, proposed_by=proposed_by, at=at)


@dataclass(frozen=True, slots=True)
class PostTurnReviewRuntime:
    coordinator: PostTurnReviewCoordinator
    reviews: PostTurnReviewLedger
    memory_proposals: OperatorMemoryProposalStore
    skill_proposals: SkillProposalStore
    metrics: PostTurnReviewMetrics
    _rule_hints: _DeferredRuleHintSubmitter

    def bind_rule_hints(self, submitter: RuleHintSubmitter) -> None:
        self._rule_hints.bind(submitter)


def build_post_turn_review_runtime(
    *,
    state_store: StateStore,
    operator_memory: OperatorMemoryStore,
    models: tuple[PostTurnProposalModel, ...] = (),
    dsn: str | None = None,
    now: Callable[[], datetime] | None = None,
) -> PostTurnReviewRuntime:
    """Build proposal-only review with durable stores when a DSN is available."""
    reviews, memory_proposals, skill_proposals = _proposal_stores(dsn)
    audit = _StateStoreProposalAudit(state_store)
    authorizer = _DenyRuntimeReviewAuthorizer()
    rule_hints = _DeferredRuleHintSubmitter()
    metrics = PostTurnReviewMetrics()
    reviewer = ConsensusPostTurnReviewer(models) if len(models) >= 2 else NoOpPostTurnReviewer()
    coordinator = PostTurnReviewCoordinator(
        eligibility=PostTurnEligibilityPolicy(),
        reviewer=reviewer,
        router=GovernedPostTurnProposalRouter(
            operator_memory=OperatorMemoryProposalWorkshop(
                proposals=memory_proposals,
                memory=operator_memory,
                audit=audit,
                authorizer=authorizer,
            ),
            skills=SkillWorkshop(
                store=skill_proposals,
                audit=audit,
                authorizer=authorizer,
            ),
            rule_hints=rule_hints,
        ),
        ledger=reviews,
        metrics=metrics,
        now=now or (lambda: datetime.now(UTC)),
    )
    return PostTurnReviewRuntime(
        coordinator=coordinator,
        reviews=reviews,
        memory_proposals=memory_proposals,
        skill_proposals=skill_proposals,
        metrics=metrics,
        _rule_hints=rule_hints,
    )


def build_azure_post_turn_models(
    *,
    repo_root: Path,
    resolved_models_path: str,
    endpoint: str,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
) -> tuple[PostTurnProposalModel, ...]:
    """Bind exactly two resolved, distinct-family Azure proposal models."""
    resolved = _load_resolved_models(resolved_models_path)
    capabilities = {item.name: item for item in resolved.capabilities}
    selected = tuple(capabilities.get(name) for name in _CAPABILITIES)
    if any(
        item is None
        or item.status is CapabilityStatus.HIL_ONLY
        or item.family is None
        or item.publisher is None
        for item in selected
    ):
        return ()
    concrete = tuple(item for item in selected if item is not None)
    if len({item.family for item in concrete}) != len(concrete):
        return ()
    prompt = FileSystemPromptRegistry(repo_root / "rule-catalog").get_base("norns.post-turn-review")
    return tuple(
        AzureOpenAIPostTurnModel(
            identity=identity,
            http_client=http_client,
            config=AzureOpenAIPostTurnModelConfig(
                endpoint=endpoint,
                deployment=item.name,
                model_identity=f"{item.publisher}:{item.family}:{item.name}",
                model_family=item.family or "",
                system_prompt=prompt.body,
            ),
        )
        for item in concrete
    )


def _proposal_stores(
    dsn: str | None,
) -> tuple[PostTurnReviewLedger, OperatorMemoryProposalStore, SkillProposalStore]:
    if not dsn:
        return (
            InMemoryPostTurnReviewLedger(),
            InMemoryOperatorMemoryProposalStore(),
            InMemorySkillProposalStore(),
        )
    from fdai.delivery.persistence import (
        PostgresOperatorMemoryProposalStore,
        PostgresOperatorMemoryProposalStoreConfig,
        PostgresPostTurnReviewLedger,
        PostgresPostTurnReviewLedgerConfig,
        PostgresSkillProposalStore,
        PostgresSkillProposalStoreConfig,
    )

    return (
        PostgresPostTurnReviewLedger(config=PostgresPostTurnReviewLedgerConfig(dsn=dsn)),
        PostgresOperatorMemoryProposalStore(
            config=PostgresOperatorMemoryProposalStoreConfig(dsn=dsn)
        ),
        PostgresSkillProposalStore(config=PostgresSkillProposalStoreConfig(dsn=dsn)),
    )


def _load_resolved_models(path_or_json: str) -> ResolvedModels:
    stripped = path_or_json.strip()
    text = stripped if stripped.startswith("{") else Path(stripped).read_text()
    return ResolvedModels.from_json(text)


def post_turn_review_dsn() -> str | None:
    return os.environ.get("FDAI_STATE_STORE_DSN", "").strip() or None


__all__ = [
    "PostTurnReviewRuntime",
    "build_azure_post_turn_models",
    "build_post_turn_review_runtime",
    "post_turn_review_dsn",
]
