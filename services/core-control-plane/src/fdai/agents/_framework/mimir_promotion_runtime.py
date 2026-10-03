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
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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
from fdai.agents._framework.mimir_maintenance import (
    MimirCatalogPromotionOutcome,
)
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.core.operational_learning import (
    ShadowDwellDecision,
    ShadowDwellEvidence,
    ShadowDwellEvidenceError,
    evaluate_shadow_dwell,
)

if TYPE_CHECKING:
    from fdai.agents._framework.base import Agent as _AgentMixinBase
else:
    _AgentMixinBase = object


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


class MimirPromotionRuntimeMixin(_AgentMixinBase):
    """Behavior-preserving extracted runtime methods."""

    if TYPE_CHECKING:
        _catalog_draft_rule_ids: Any
        _catalog_governance_store: Any
        _checkpoint_rule_publication: Any
        _clock: Any
        _governance_state_store: Any
        _handle_rule_candidate: Any
        _handle_rule_generation_build_request: Any
        _handover_message: Any
        _investigation_candidates: Any
        _issue_fingerprints: Any
        _max_pending_candidates: Any
        _norns_issue_close_support: Any
        _operational_pending_targets: Any
        _pending_candidates: Any
        _persist_issue_fingerprint: Any
        _persist_promotion_record: Any
        _promotion_fail_count: Any
        _promotion_outcome_reader: Any
        _promotion_pass_count: Any
        _promotion_persist_pending: Any
        _promotion_persist_tasks: Any
        _promotion_publish_tasks: Any
        _promotions: Any
        _provider_timeout_seconds: Any
        _publish_claimed_rule_publication: Any
        _publish_rule_or_policy_promotion: Any
        _published_issue_close_evidence: Any
        _published_operational_targets: Any
        _published_promotion_keys: Any
        _quarantined_candidates: Any
        _rebuild_candidate_indexes: Any
        _record_norns_issue_close_support: Any
        _record_rule_generation_activation_result: Any
        _record_rule_generation_validation_result: Any
        _recover_rule_publications: Any
        _refresh_issue_candidate_counts_for_rule: Any
        _regression_runner: Any
        _retain_rule_generation_activation_command: Any
        _review_locks: Any
        _reviewed_repository_prefixes: Any
        _rule_deprecation_reader: Any
        _rule_generation_activation_binder: Any
        _rule_generation_build_handler: Any
        _rule_generation_state_store: Any
        _rule_source_poller: Any
        _shadow_dwell_thresholds: Any
        _test_context_message: Any

    def shadow_dwell_decision(self, candidate: dict[str, Any]) -> ShadowDwellDecision:
        """Re-derive the dwell verdict for one candidate from its own wire evidence.

        Mimir never reads another agent's memory to fill a gap: whatever the
        candidate failed to carry is missing evidence, and missing evidence is a
        gap, not a pass.
        """

        raw = candidate.get("shadow_dwell")
        if raw is None:
            return evaluate_shadow_dwell(None, self._shadow_dwell_thresholds)
        try:
            evidence = ShadowDwellEvidence.from_mapping(raw)
        except ShadowDwellEvidenceError as exc:
            return ShadowDwellDecision(
                eligible=False,
                gaps=(f"shadow_dwell_evidence_invalid:{exc.code}",),
            )
        target = str(candidate.get("target_rule_id") or "")
        if evidence.target != target:
            # Otherwise a candidate could borrow a well-behaved rule's record.
            return ShadowDwellDecision(eligible=False, gaps=("shadow_dwell_target_mismatch",))
        return evaluate_shadow_dwell(evidence, self._shadow_dwell_thresholds)

    def promotion_ready_candidates(self) -> tuple[dict[str, Any], ...]:
        """Pending candidates whose shadow dwell evidence clears every bar.

        This is the discovery loop's promotion-eligibility surface. Membership is
        earned by evidence; a candidate is absent until it proves the dwell, which
        is why it is computed here rather than stamped onto the candidate on
        intake. Eligibility is still not promotion - the catalog changes only
        through a merged catalog-as-code pull request.
        """

        return tuple(
            candidate
            for candidate in self._pending_candidates
            if self.shadow_dwell_decision(candidate).eligible
        )

    def promote(
        self,
        rule_id: str,
        *,
        source: str,
        reviewed_change_ref: str | None = None,
        updated_at: str | None = None,
    ) -> RulePromotion:
        if (
            rule_id.startswith(_OPERATIONAL_RULE_PREFIX)
            or rule_id in self._operational_pending_targets
            or rule_id in self._published_operational_targets
            or rule_id in self._catalog_draft_rule_ids
        ):
            self._promotion_fail_count += 1
            self.record_behavior("promotion:failed_operational_candidate")
            raise ValueError(
                "operational candidates require a reviewed catalog PR; "
                "direct runtime promotion is not supported"
            )
        blocking_gaps = self._dwell_gaps_for(rule_id)
        if blocking_gaps:
            self._promotion_fail_count += 1
            self.record_behavior("promotion:failed_shadow_dwell")
            raise ValueError(
                f"rule {rule_id} has a pending discovery-loop candidate whose shadow "
                f"dwell evidence is insufficient: {', '.join(blocking_gaps)}"
            )
        package_digest = _reviewed_package_digest(
            reviewed_change_ref,
            allowed_repository_prefixes=self._reviewed_repository_prefixes,
        )
        if package_digest is None:
            self._promotion_fail_count += 1
            self.record_behavior("promotion:invalid_reviewed_change_ref")
            raise ValueError(
                "rule promotion requires a reviewed catalog-as-code PR or commit reference "
                "with the reviewed package digest"
            )
        promo = RulePromotion(
            rule_id=rule_id, state="enforce", source=source, updated_at=updated_at
        )
        try:
            _run_coroutine_blocking(
                self._apply_promotion(
                    promo,
                    reviewed_change_ref=reviewed_change_ref,
                    reviewed_package_digest=package_digest,
                )
            )
        except Exception:
            self._promotions.pop(rule_id, None)
            self._promotion_fail_count += 1
            raise
        self._promotions[rule_id] = promo
        self._pending_candidates = deque(
            (
                candidate
                for candidate in self._pending_candidates
                if candidate.get("target_rule_id") != rule_id
            ),
        )
        _run_coroutine_blocking(self._refresh_issue_candidate_counts_for_rule(rule_id))
        self._rebuild_candidate_indexes()
        self._promotion_pass_count += 1
        self.record_behavior("promotion:passed")
        return promo

    def _dwell_gaps_for(self, rule_id: str) -> tuple[str, ...]:
        """Unmet dwell bars across every pending candidate that targets ``rule_id``."""

        gaps: list[str] = []
        for candidate in self._pending_candidates:
            if str(candidate.get("target_rule_id") or "") != rule_id:
                continue
            decision = self.shadow_dwell_decision(candidate)
            gaps.extend(gap for gap in decision.gaps if gap not in gaps)
        return tuple(gaps)

    def revoke(self, rule_id: str, *, updated_at: str | None = None) -> RulePromotion:
        promo = RulePromotion(
            rule_id=rule_id, state="retired", source="manual", updated_at=updated_at
        )
        _run_coroutine_blocking(self._apply_promotion(promo))
        self._promotions[rule_id] = promo
        return promo

    async def _apply_promotion(
        self,
        promotion: RulePromotion,
        *,
        reviewed_change_ref: str | None = None,
        reviewed_package_digest: str | None = None,
    ) -> None:
        await self._persist_promotion_record(promotion)
        await self._publish_rule_or_policy_promotion(
            promotion,
            reviewed_change_ref=reviewed_change_ref,
            reviewed_package_digest=reviewed_package_digest,
        )


__all__ = ["MimirPromotionRuntimeMixin"]
