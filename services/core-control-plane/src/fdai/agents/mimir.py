"""Mimir - Rule Steward (Wave 2 behavior).

Mimir tracks rule shadow / enforce promotion. Wave 2 exposes a minimal
in-memory promotion tracker; the concrete rule catalog loader stays in
:mod:`fdai.rule_catalog`. Mimir's job here is the promotion state
machine and the RuleCandidate intake.
"""

from __future__ import annotations

import asyncio
import re
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.handover_knowledge import HandoverKnowledgeMixin
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
    capped_list,
    mentioned,
    semantic_intents,
)
from fdai.agents._framework.mimir_catalog_recovery import (
    CatalogReviewCapacityError,
    MimirCatalogReviewMixin,
)
from fdai.agents._framework.mimir_constants import (
    _DEFAULT_PROVIDER_TIMEOUT_SECONDS as _DEFAULT_PROVIDER_TIMEOUT_SECONDS,
)
from fdai.agents._framework.mimir_constants import (
    _DEPRECATION_CANDIDATE_PREFIX as _DEPRECATION_CANDIDATE_PREFIX,
)
from fdai.agents._framework.mimir_constants import (
    _GOVERNANCE_PREFIX as _GOVERNANCE_PREFIX,
)
from fdai.agents._framework.mimir_constants import (
    _GOVERNANCE_RECOVERY_PAGE as _GOVERNANCE_RECOVERY_PAGE,
)
from fdai.agents._framework.mimir_constants import (
    _ISSUE_FINGERPRINT_PREFIX as _ISSUE_FINGERPRINT_PREFIX,
)
from fdai.agents._framework.mimir_constants import (
    _MAX_CATALOG_REVIEW_PACKAGES as _MAX_CATALOG_REVIEW_PACKAGES,
)
from fdai.agents._framework.mimir_constants import (
    _MAX_ISSUE_FINGERPRINTS as _MAX_ISSUE_FINGERPRINTS,
)
from fdai.agents._framework.mimir_constants import (
    _MAX_MAINTENANCE_RECORDS as _MAX_MAINTENANCE_RECORDS,
)
from fdai.agents._framework.mimir_constants import (
    _MAX_PENDING_CANDIDATES as _MAX_PENDING_CANDIDATES,
)
from fdai.agents._framework.mimir_constants import (
    _MAX_PROMOTION_PERSIST_ATTEMPTS as _MAX_PROMOTION_PERSIST_ATTEMPTS,
)
from fdai.agents._framework.mimir_constants import (
    _MAX_PROMOTION_PERSIST_QUEUE as _MAX_PROMOTION_PERSIST_QUEUE,
)
from fdai.agents._framework.mimir_constants import (
    _MAX_QUARANTINE as _MAX_QUARANTINE,
)
from fdai.agents._framework.mimir_constants import (
    _OPERATIONAL_RULE_PREFIX as _OPERATIONAL_RULE_PREFIX,
)
from fdai.agents._framework.mimir_constants import (
    _REVIEWED_CATALOG_COMMIT_REF as _REVIEWED_CATALOG_COMMIT_REF,
)
from fdai.agents._framework.mimir_constants import (
    _REVIEWED_CATALOG_PR_REF as _REVIEWED_CATALOG_PR_REF,
)
from fdai.agents._framework.mimir_constants import (
    _REVIEWED_REPOSITORY_PREFIX as _REVIEWED_REPOSITORY_PREFIX,
)
from fdai.agents._framework.mimir_constants import (
    _RULE_GENERATION_COMMAND_PREFIX as _RULE_GENERATION_COMMAND_PREFIX,
)
from fdai.agents._framework.mimir_constants import (
    _RULE_GENERATION_RECEIPT_PREFIX as _RULE_GENERATION_RECEIPT_PREFIX,
)
from fdai.agents._framework.mimir_constants import (
    _RULE_GENERATION_RECEIPT_RETAIN as _RULE_GENERATION_RECEIPT_RETAIN,
)
from fdai.agents._framework.mimir_constants import (
    _RULE_GENERATION_VALIDATION_PREFIX as _RULE_GENERATION_VALIDATION_PREFIX,
)
from fdai.agents._framework.mimir_constants import (
    _RULE_PUBLICATION_CLAIM_LEASE as _RULE_PUBLICATION_CLAIM_LEASE,
)
from fdai.agents._framework.mimir_constants import (
    _RULE_PUBLICATION_MAINTENANCE_PAGE as _RULE_PUBLICATION_MAINTENANCE_PAGE,
)
from fdai.agents._framework.mimir_constants import (
    _RULE_PUBLICATION_PREFIX as _RULE_PUBLICATION_PREFIX,
)
from fdai.agents._framework.mimir_constants import (
    _RULE_STATE_PREFIX as _RULE_STATE_PREFIX,
)
from fdai.agents._framework.mimir_context import MimirContextMixin
from fdai.agents._framework.mimir_governance_maintenance import MimirGovernanceMaintenanceMixin
from fdai.agents._framework.mimir_governance_persistence import MimirGovernancePersistenceMixin
from fdai.agents._framework.mimir_governance_recovery import MimirGovernanceRecoveryMixin
from fdai.agents._framework.mimir_maintenance import (
    MimirCatalogPromotionOutcome,
    MimirCatalogPromotionOutcomeReader,
    MimirRegressionRunner,
    MimirRuleDeprecationReader,
    MimirRuleSourcePoller,
)
from fdai.agents._framework.mimir_promotion_runtime import MimirPromotionRuntimeMixin
from fdai.agents._framework.mimir_rule_generation import MimirRuleGenerationMixin
from fdai.agents._framework.mimir_rule_publication import MimirRulePublicationMixin
from fdai.agents._framework.pantheon import _MIMIR
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.core.operational_learning import (
    CatalogCandidateCompiler,
    CatalogReviewPublisher,
    ShadowDwellThresholds,
)
from fdai.core.rule_semantic_generation import (
    RuleGenerationActivationBinder,
    RuleGenerationBuildHandler,
)
from fdai.shared.providers.state_store import StateStore


@dataclass(frozen=True, slots=True)
class RulePromotion:
    rule_id: str
    state: str  # shadow | enforce | retired
    source: str  # handoff | override | manual | coherence
    updated_at: str | None


def _rule_state_key(rule_id: str) -> str:
    return f"{_RULE_STATE_PREFIX}/{rule_id}"


def _issue_fingerprint_key(fingerprint: str) -> str:
    return f"{_ISSUE_FINGERPRINT_PREFIX}/{fingerprint}"


def _rule_publication_key(idempotency_key: str) -> str:
    return f"{_RULE_PUBLICATION_PREFIX}/{idempotency_key}"


def _issue_close_evidence_idempotency_key(outcome: MimirCatalogPromotionOutcome) -> str:
    return stable_idempotency_key(
        "mimir-issue-close-promotion-evidence",
        outcome.problem_fingerprint,
        outcome.promotion_pr,
        outcome.correlation_id,
    )


def _reviewed_package_digest(
    reviewed_change_ref: str | None,
    *,
    allowed_repository_prefixes: frozenset[str] = frozenset(),
) -> str | None:
    if reviewed_change_ref is None:
        return None
    candidate = reviewed_change_ref.strip()
    pr_match = _REVIEWED_CATALOG_PR_REF.fullmatch(candidate)
    if pr_match is not None:
        repository = _normalize_reviewed_repository_prefix(pr_match.group("repository"))
        if repository is None:
            return None
        if allowed_repository_prefixes and repository not in allowed_repository_prefixes:
            return None
        return pr_match.group("digest")
    commit_match = _REVIEWED_CATALOG_COMMIT_REF.fullmatch(candidate)
    if commit_match is not None:
        return commit_match.group("digest")
    return None


def _normalize_reviewed_repository_prefix(prefix: str) -> str | None:
    match = _REVIEWED_REPOSITORY_PREFIX.fullmatch(prefix.strip())
    if match is None:
        return None
    host = match.group("host").lower()
    if not _valid_review_host(host):
        return None
    owner = match.group("owner")
    repo = match.group("repo")
    if owner in {".", ".."} or repo in {".", ".."}:
        return None
    return f"https://{host}/{owner}/{repo}"


def _normalize_reviewed_repository_prefixes(prefixes: Sequence[str]) -> frozenset[str]:
    normalized: set[str] = set()
    for prefix in prefixes:
        value = _normalize_reviewed_repository_prefix(prefix)
        if value is None:
            raise ValueError("Mimir reviewed repository prefix MUST be a structural HTTPS repo URL")
        normalized.add(value)
    return frozenset(normalized)


def _valid_review_host(host: str) -> bool:
    if len(host) > 253 or "." not in host:
        return False
    labels = host.split(".")
    return all(
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) is not None
        for label in labels
    )


def _run_coroutine_blocking(awaitable: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    result: dict[str, Any] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(awaitable)
        except BaseException as exc:  # noqa: BLE001 - re-raise in caller thread
            result["error"] = exc

    thread = threading.Thread(target=runner, name="mimir-promotion-sync")
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def _promotion_topic(rule_id: str, source: str) -> str:
    if rule_id.startswith("policy.") or source == "policy":
        return "object.policy"
    return "object.rule"


class Mimir(
    MimirContextMixin,
    MimirGovernanceRecoveryMixin,
    MimirRuleGenerationMixin,
    MimirPromotionRuntimeMixin,
    MimirRulePublicationMixin,
    MimirGovernanceMaintenanceMixin,
    MimirGovernancePersistenceMixin,
    Agent,
    HandoverKnowledgeMixin,
    MimirCatalogReviewMixin,
):
    """Wave-2 Mimir: promotion state + candidate intake."""

    def __init__(
        self,
        *,
        catalog_candidate_compiler: CatalogCandidateCompiler | None = None,
        catalog_review_publisher: CatalogReviewPublisher | None = None,
        catalog_review_state_store: StateStore | None = None,
        governance_state_store: StateStore | None = None,
        shadow_dwell_thresholds: ShadowDwellThresholds | None = None,
        max_pending_candidates: int = _MAX_PENDING_CANDIDATES,
        max_review_packages: int = _MAX_CATALOG_REVIEW_PACKAGES,
        clock: Callable[[], datetime] | None = None,
        provider_timeout_seconds: float = _DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        reviewed_repository_prefixes: Sequence[str] = (),
    ) -> None:
        super().__init__(spec=_MIMIR)
        if min(max_pending_candidates, max_review_packages) < 1:
            raise ValueError("Mimir review capacities MUST be positive")
        if provider_timeout_seconds <= 0:
            raise ValueError("Mimir provider timeout MUST be positive")
        self._reviewed_repository_prefixes = _normalize_reviewed_repository_prefixes(
            reviewed_repository_prefixes
        )
        self._promotions: dict[str, RulePromotion] = {}
        self._governance_state_store = governance_state_store
        self._promotion_persist_tasks: set[asyncio.Task[None]] = set()
        self._promotion_publish_tasks: set[asyncio.Task[Any]] = set()
        self._published_promotion_keys: BoundedLruSet[str] = BoundedLruSet(
            _MAX_PROMOTION_PERSIST_QUEUE
        )
        self._promotion_persist_pending: dict[str, RulePromotion] = {}
        self._promotion_persist_worker: asyncio.Task[None] | None = None
        self._shadow_dwell_thresholds = shadow_dwell_thresholds or ShadowDwellThresholds()
        self._init_catalog_review(
            compiler=catalog_candidate_compiler,
            publisher=catalog_review_publisher,
            state_store=catalog_review_state_store or governance_state_store,
            max_pending_candidates=max_pending_candidates,
            max_review_packages=max_review_packages,
            max_quarantine=_MAX_QUARANTINE,
        )
        self._review_lock = asyncio.Lock()
        self._review_locks: dict[str, asyncio.Lock] = {}
        self._rule_generation_build_handler: RuleGenerationBuildHandler | None = None
        self._rule_generation_activation_binder: RuleGenerationActivationBinder | None = None
        self._rule_generation_state_store: StateStore | None = None
        self._clock = clock or (lambda: datetime.now(UTC))
        self._provider_timeout_seconds = provider_timeout_seconds
        self._issue_fingerprints: BoundedLruDict[str, dict[str, Any]] = BoundedLruDict(
            _MAX_ISSUE_FINGERPRINTS
        )
        self._operational_pending_targets: BoundedLruSet[str] = BoundedLruSet(
            max_pending_candidates
        )
        self._catalog_draft_rule_ids: BoundedLruSet[str] = BoundedLruSet(max_review_packages)
        self._promotion_pass_count = 0
        self._promotion_fail_count = 0
        self._promotion_outcome_reader: MimirCatalogPromotionOutcomeReader | None = None
        self._regression_runner: MimirRegressionRunner | None = None
        self._rule_source_poller: MimirRuleSourcePoller | None = None
        self._rule_deprecation_reader: MimirRuleDeprecationReader | None = None
        self._norns_issue_close_support: BoundedLruDict[str, dict[str, Any]] = BoundedLruDict(
            _MAX_ISSUE_FINGERPRINTS
        )
        self._published_issue_close_evidence: BoundedLruSet[str] = BoundedLruSet(
            _MAX_PROMOTION_PERSIST_QUEUE
        )
        self._last_rule_source_poll: dict[str, Any] = {
            "status": "unbound",
            "outcome": "bounded_noop",
        }
        self._last_regression_suite: dict[str, Any] = {
            "status": "unbound",
            "outcome": "bounded_noop",
        }
        self._last_deprecation_cycle: dict[str, Any] = {
            "status": "unbound",
            "outcome": "bounded_noop",
        }

    def bind_rule_generation_build_handler(
        self,
        handler: RuleGenerationBuildHandler,
    ) -> None:
        """Bind the durable mechanical generation builder at composition time."""

        if self._rule_generation_build_handler is not None:
            raise RuntimeError("Mimir Rule generation build handler is already bound")
        self._rule_generation_build_handler = handler

    def bind_rule_generation_activation_binder(
        self,
        binder: RuleGenerationActivationBinder,
    ) -> None:
        """Bind exact catalog-pointer activation at composition time."""

        if self._rule_generation_activation_binder is not None:
            raise RuntimeError("Mimir Rule generation activation binder is already bound")
        self._rule_generation_activation_binder = binder

    def bind_rule_generation_state_store(self, store: StateStore) -> None:
        """Bind the durable accountability projection at composition time."""

        if self._rule_generation_state_store is not None:
            raise RuntimeError("Mimir Rule generation receipt store is already bound")
        self._rule_generation_state_store = store

    def bind_governance_state_store(self, store: StateStore) -> None:
        """Bind durable Mimir governance projections at composition time."""
        if self._governance_state_store is not None:
            raise RuntimeError("Mimir governance state store is already bound")
        self._governance_state_store = store
        self._catalog_governance_store.bind(store)

    def bind_catalog_promotion_outcome_reader(
        self,
        reader: MimirCatalogPromotionOutcomeReader,
    ) -> None:
        """Bind the read-only reviewed catalog outcome source."""

        if self._promotion_outcome_reader is not None:
            raise RuntimeError("Mimir catalog promotion outcome reader is already bound")
        self._promotion_outcome_reader = reader

    def bind_regression_runner(self, runner: MimirRegressionRunner) -> None:
        """Bind the read-only regression suite used for clean-window evidence."""

        if self._regression_runner is not None:
            raise RuntimeError("Mimir regression runner is already bound")
        self._regression_runner = runner

    def bind_rule_source_poller(self, poller: MimirRuleSourcePoller) -> None:
        """Bind the read-only rule source poller."""

        if self._rule_source_poller is not None:
            raise RuntimeError("Mimir rule source poller is already bound")
        self._rule_source_poller = poller

    def bind_rule_deprecation_reader(self, reader: MimirRuleDeprecationReader) -> None:
        """Bind the read-only rule deprecation evidence source."""

        if self._rule_deprecation_reader is not None:
            raise RuntimeError("Mimir rule deprecation reader is already bound")
        self._rule_deprecation_reader = reader

    def _rebuild_candidate_indexes(self) -> None:
        self._operational_pending_targets = BoundedLruSet(self._max_pending_candidates)
        self._catalog_draft_rule_ids = BoundedLruSet(self._max_review_packages)
        for candidate in self._pending_candidates:
            if candidate.get("source_signal") == "operational_case_fingerprint_cohort":
                target = str(candidate.get("target_rule_id") or "")
                if target:
                    self._operational_pending_targets.add(target)
        for package in self._catalog_review_packages.values():
            rule_id = str(package.draft_rule.mapping["id"])
            if rule_id:
                self._catalog_draft_rule_ids.add(rule_id)

    def status(self, rule_id: str) -> RulePromotion | None:
        return self._promotions.get(rule_id)

    def health(self) -> dict[str, Any]:
        durable_governance = self._governance_state_store is not None
        stale_rules = sum(1 for promotion in self._promotions.values() if not promotion.updated_at)
        tracked_rules = len(self._promotions)
        status = "ok" if durable_governance and stale_rules == 0 else "degraded"
        return {
            "agent": self.spec.name,
            "status": status,
            "rule_cache": {
                "tracked_rules": tracked_rules,
                "fresh_rules": tracked_rules - stale_rules,
                "stale_rules": stale_rules,
                "freshness_state": "measured" if tracked_rules else "not_observed",
                "warning": "stale_rule_metadata" if stale_rules else None,
            },
            "persistence": {
                "governance_state": "durable" if durable_governance else "process_local",
                "catalog_review_state": (
                    "durable" if self._catalog_review_journal.durable else "process_local"
                ),
                "pending_promotion_writes": len(self._promotion_persist_pending),
            },
            "catalog_review": {
                "pending_candidates": len(self._pending_candidates),
                "quarantined_candidates": len(self._quarantined_candidates),
                "review_packages": len(self._catalog_review_packages),
            },
            "maintenance": {
                "rule_source_poll": self._last_rule_source_poll,
                "regression_suite": self._last_regression_suite,
                "deprecation_cycle": self._last_deprecation_cycle,
                "norns_issue_close_support_count": len(self._norns_issue_close_support),
            },
            "kpis": {
                "rule_freshness_score": _ratio_kpi(
                    tracked_rules - stale_rules,
                    tracked_rules,
                ),
                "promotion_pass_rate": _ratio_kpi(
                    self._promotion_pass_count,
                    self._promotion_pass_count + self._promotion_fail_count,
                ),
                "shadow_failure_rate": _ratio_kpi(
                    sum(
                        1
                        for candidate in self._pending_candidates
                        if self.shadow_dwell_decision(candidate).gaps
                    ),
                    len(self._pending_candidates),
                ),
                "stale_rule_ratio": _ratio_kpi(stale_rules, tracked_rules),
            },
        }

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Rule answers rest on tracked promotions and the candidate queue."""
        return bool(self._promotions or self._pending_candidates or self._quarantined_candidates)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            "tracked_rules": capped_list(sorted(self._promotions)),
            "tracked_rules_count": len(self._promotions),
            "pending_candidates": len(self._pending_candidates),
            "promotion_ready_candidates": None,
            "promotion_ready_candidates_evidence_state": "not_recomputed",
            "quarantined_candidates": len(self._quarantined_candidates),
            "catalog_review_packages": len(self._catalog_review_packages),
            "catalog_review_publication_receipts": len(self._published_reviews),
            "open_issue_fingerprints": len(self._issue_fingerprints),
            "policy_history_available": False,
            "rule_id": None,
            "state": None,
            "source": None,
            "updated_at": None,
        }
        if "policy_history" in semantic_intents(context):
            evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
            facts["evidence_refs"] = [evidence_ref]
            return IntrospectionResult(
                answer=(
                    "No governed policy history is bound to this conversational projection. "
                    f"Evidence: {evidence_ref}."
                ),
                facts=facts,
            )
        rules = mentioned(question, self._promotions)
        if rules:
            promo = self._promotions[rules[0]]
            facts.update(
                {
                    "rule_id": promo.rule_id,
                    "state": promo.state,
                    "source": promo.source,
                    # When the state last changed, so an operator can tell a
                    # fresh promotion from a long-settled one.
                    "updated_at": promo.updated_at,
                }
            )
            evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
            facts["evidence_refs"] = [evidence_ref]
            answer = (
                f"Rule {promo.rule_id!r} is {promo.state} (source: {promo.source}). "
                f"Evidence: {evidence_ref}."
            )
            return IntrospectionResult(answer=answer, facts=facts)
        evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
        facts["evidence_refs"] = [evidence_ref]
        if context.get("locale") == "ko":
            answer = (
                "저는 거버넌스 계층의 rule steward인 Mimir입니다. Odin에게 보고합니다. Rule, "
                "Policy, RuleGenerationBuildRequest 및 RuleGenerationBuildResult를 소유합니다. "
                "모든 후보는 품질 gate, 회귀 검사와 shadow 근거를 통과해야 하며 운영 규칙은 검토된 "
                "catalog PR 없이는 승격할 수 없습니다. 작업을 판단하거나 승인하거나 실행하지 "
                "않습니다. 이 대화 포트는 읽기 전용이며 catalog 변경 요청은 운영자 권한으로 "
                "타입이 지정된 파이프라인에 다시 진입해야 합니다. 숨겨진 시스템 프롬프트는 "
                f"공개하지 않습니다. 이 런타임은 Rule {facts['tracked_rules_count']}개, 대기 후보 "
                f"{facts['pending_candidates']}개, 승격 준비 후보 "
                f"{facts['promotion_ready_candidates']}개, 격리 후보 "
                f"{facts['quarantined_candidates']}개를 추적합니다. 근거: {evidence_ref}."
            )
        else:
            answer = (
                "I am Mimir, the governance-layer rule steward. I report to Odin. I own Rule, "
                "Policy, RuleGenerationBuildRequest, and RuleGenerationBuildResult. Every "
                "candidate must pass the quality gate, regression checks, and shadow evidence; "
                "operational rules cannot promote without a reviewed catalog PR. I never judge, "
                "approve, or execute an action. This conversational port is read-only; catalog "
                "change requests re-enter the typed pipeline under the operator's authority. I do "
                "not reveal hidden system prompts. This runtime tracks "
                f"{facts['tracked_rules_count']} Rules, {facts['pending_candidates']} pending "
                f"candidates, {facts['promotion_ready_candidates']} promotion-ready candidates, "
                f"and {facts['quarantined_candidates']} quarantined candidates. "
                f"Evidence: {evidence_ref}."
            )
        return IntrospectionResult(answer=answer, facts=facts)


def _ratio_kpi(numerator: int, denominator: int) -> dict[str, Any]:
    if denominator <= 0:
        return {
            "value": None,
            "evidence_state": "not_observed",
            "numerator": numerator,
            "denominator": denominator,
            "unit": "ratio",
        }
    return {
        "value": numerator / denominator,
        "evidence_state": "measured",
        "numerator": numerator,
        "denominator": denominator,
        "unit": "ratio",
    }


__all__ = ["CatalogReviewCapacityError", "Mimir", "RulePromotion"]
