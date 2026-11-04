"""Staging parity, Wave 5 safety, auto-settler, learning feedback, and parity (Items 26-30).

Provides:
26. ``verify_action_staging_parity``: verifies exact parity between expected state delta and
    independently observed staging execution delta before mutation behavior is presented or
    promoted.
27. ``WorkflowScaleSafetyController``: Wave 5 per-target distributed lock, per-scope backpressure,
    process SLI computation, and automatic demotion to ``SHADOW`` on guard breach or policy escape.
28. ``PostWindowValueClaimAutoSettler``: scheduled worker settling mature ``ValueClaimDeclaration``
    items once ``window_end <= now`` and recording them in ``StateStoreValueClaimLedger``.
29. ``recalibrate_option_utility_from_settlement``: feeds ``ValueClaimSettlement`` back into
    operational learning to adjust ``ActionOption`` confidence, utility, and review holds.
30. ``evaluate_sre_agent_parity_cohort``: compares FDAI ontology answers against Azure SRE Agent
    answers over a labeled incident cohort using ground-truth accuracy, citation validity, and
    abstention discipline.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.measurement.value_claim import (
    ValueClaimDeclaration,
    ValueClaimSettlement,
    ValueClaimStatus,
    ValueCohortObservation,
    settle_value_claim,
)
from fdai.core.measurement.value_claim_ledger import StateStoreValueClaimLedger
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.state_store import StateStore


@dataclass(frozen=True, slots=True)
class StagingParityEvidence:
    """Item 26: Expected vs staging-observed state delta for one ActionType."""

    action_type_ref: str
    staging_run_id: str
    expected_state_delta: Mapping[str, Any]
    staging_observed_delta: Mapping[str, Any]
    rollback_rehearsed: bool
    policy_escape_count: int
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class StagingParityReceipt:
    """Item 26: Replay-stable receipt proving or rejecting staging mutation parity."""

    action_type_ref: str
    staging_run_id: str
    parity_verified: bool
    mismatched_keys: tuple[str, ...]
    reason_codes: tuple[str, ...]
    receipt_digest: str
    execution_authority: Literal[False] = False


def verify_action_staging_parity(evidence: StagingParityEvidence) -> StagingParityReceipt:
    """Item 26: Require exact state-delta match, rehearsed rollback, and zero policy escapes."""

    if evidence.observed_at.tzinfo is None or evidence.observed_at.utcoffset() is None:
        raise ValueError("StagingParityEvidence.observed_at MUST be timezone-aware")
    reasons: list[str] = []
    if not evidence.expected_state_delta:
        reasons.append("expected_delta_empty")
    all_keys = sorted(set(evidence.expected_state_delta) | set(evidence.staging_observed_delta))
    mismatched = tuple(
        key
        for key in all_keys
        if evidence.expected_state_delta.get(key) != evidence.staging_observed_delta.get(key)
    )
    if mismatched:
        reasons.append("state_delta_mismatch")
    if not evidence.rollback_rehearsed:
        reasons.append("rollback_not_rehearsed")
    if evidence.policy_escape_count > 0:
        reasons.append("policy_escape_detected")
    verified = not reasons
    digest = content_digest(
        {
            "action_type_ref": evidence.action_type_ref,
            "staging_run_id": evidence.staging_run_id,
            "parity_verified": verified,
            "mismatched_keys": list(mismatched),
            "reason_codes": reasons,
        }
    )
    return StagingParityReceipt(
        action_type_ref=evidence.action_type_ref,
        staging_run_id=evidence.staging_run_id,
        parity_verified=verified,
        mismatched_keys=mismatched,
        reason_codes=tuple(reasons),
        receipt_digest=digest,
    )


@dataclass(frozen=True, slots=True)
class WorkflowSliSnapshot:
    """Item 27: Operational SLIs for one workflow over a measurement window."""

    workflow_name: str
    total_runs: int
    succeeded_runs: int
    failed_runs: int
    rolled_back_runs: int
    policy_escape_count: int
    success_rate: float
    failure_or_rollback_rate: float


@dataclass(frozen=True, slots=True)
class WorkflowAutoDemotionReceipt:
    """Item 27: Automatic demotion decision returning an unhealthy workflow to SHADOW."""

    workflow_name: str
    previous_mode: Mode
    effective_mode: Mode
    demoted: bool
    reason_codes: tuple[str, ...]
    receipt_digest: str


class WorkflowScaleSafetyController:
    """Item 27: Wave 5 distributed target lock, per-scope backpressure, SLIs, and auto-demotion."""

    def __init__(
        self,
        store: StateStore,
        *,
        max_active_per_scope: int = 4,
        max_failure_rate: float = 0.10,
    ) -> None:
        if max_active_per_scope < 1:
            raise ValueError("max_active_per_scope MUST be >= 1")
        if not 0.0 <= max_failure_rate <= 1.0:
            raise ValueError("max_failure_rate MUST be in [0.0, 1.0]")
        self._store = store
        self._max_active_per_scope = max_active_per_scope
        self._max_failure_rate = max_failure_rate
        self._scope_counts: dict[str, int] = {}

    async def acquire_target_and_scope(
        self,
        *,
        scope_ref: str,
        target_resource_ref: str,
        process_id: str,
    ) -> tuple[bool, str | None]:
        """Acquire a durable per-target lock and check per-scope backpressure."""

        active_in_scope = self._scope_counts.get(scope_ref, 0)
        if active_in_scope >= self._max_active_per_scope:
            return False, "scope_backpressure_limit_reached"
        lock_key = f"workflow:wave5:target-lock:{target_resource_ref}"
        claimed = await self._store.write_state_if_absent(
            lock_key,
            {"process_id": process_id, "scope_ref": scope_ref},
        )
        if not claimed:
            return False, "target_distributed_lock_held"
        self._scope_counts[scope_ref] = active_in_scope + 1
        return True, None

    async def release_target_and_scope(
        self,
        *,
        scope_ref: str,
        target_resource_ref: str,
        process_id: str,
    ) -> None:
        lock_key = f"workflow:wave5:target-lock:{target_resource_ref}"
        existing = await self._store.read_state(lock_key)
        if existing is not None and existing.get("process_id") == process_id:
            await self._store.write_state(lock_key, {"released_by": process_id})
        current = self._scope_counts.get(scope_ref, 0)
        if current > 0:
            self._scope_counts[scope_ref] = current - 1

    def evaluate_sli_and_demotion(
        self,
        *,
        workflow_name: str,
        current_mode: Mode,
        succeeded_runs: int,
        failed_runs: int,
        rolled_back_runs: int,
        policy_escape_count: int,
    ) -> tuple[WorkflowSliSnapshot, WorkflowAutoDemotionReceipt]:
        total = succeeded_runs + failed_runs + rolled_back_runs
        success_rate = round(succeeded_runs / total, 6) if total > 0 else 1.0
        bad_rate = round((failed_runs + rolled_back_runs) / total, 6) if total > 0 else 0.0
        sli = WorkflowSliSnapshot(
            workflow_name=workflow_name,
            total_runs=total,
            succeeded_runs=succeeded_runs,
            failed_runs=failed_runs,
            rolled_back_runs=rolled_back_runs,
            policy_escape_count=policy_escape_count,
            success_rate=success_rate,
            failure_or_rollback_rate=bad_rate,
        )
        reasons: list[str] = []
        if policy_escape_count > 0:
            reasons.append("policy_escape_breach")
        if total > 0 and bad_rate > self._max_failure_rate:
            reasons.append("failure_or_rollback_rate_breach")
        demoted = bool(reasons) and current_mode is Mode.ENFORCE
        effective_mode = Mode.SHADOW if reasons else current_mode
        digest = content_digest(
            {
                "workflow_name": workflow_name,
                "previous_mode": current_mode.value,
                "effective_mode": effective_mode.value,
                "demoted": demoted,
                "reasons": reasons,
            }
        )
        return sli, WorkflowAutoDemotionReceipt(
            workflow_name=workflow_name,
            previous_mode=current_mode,
            effective_mode=effective_mode,
            demoted=demoted,
            reason_codes=tuple(reasons),
            receipt_digest=digest,
        )


@dataclass(frozen=True, slots=True)
class AutoSettlementBatchResult:
    """Item 28: Summary of a post-window automatic ValueClaim settlement tick."""

    settled: tuple[ValueClaimSettlement, ...]
    deferred_claim_ids: tuple[str, ...]
    batch_digest: str


class PostWindowValueClaimAutoSettler:
    """Item 28: Settle and persist mature ValueClaimDeclarations once window_end <= now."""

    def __init__(self, store: StateStore) -> None:
        self._ledger = StateStoreValueClaimLedger(store)

    async def run_tick(
        self,
        pending: Sequence[tuple[ValueClaimDeclaration, tuple[ValueCohortObservation, ...]]],
        *,
        now: datetime,
    ) -> AutoSettlementBatchResult:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("AutoSettler now MUST be timezone-aware")
        settled: list[ValueClaimSettlement] = []
        deferred: list[str] = []
        for declaration, cohorts in pending:
            if declaration.window_end > now:
                deferred.append(declaration.claim_id)
                continue
            settlement = settle_value_claim(declaration, cohorts)
            await self._ledger.record(declaration, settlement)
            settled.append(settlement)
        digest = content_digest(
            {
                "now": now.astimezone(UTC).isoformat(),
                "settled_digests": [s.settlement_digest for s in settled],
                "deferred_claim_ids": sorted(deferred),
            }
        )
        return AutoSettlementBatchResult(
            settled=tuple(settled),
            deferred_claim_ids=tuple(sorted(deferred)),
            batch_digest=digest,
        )


@dataclass(frozen=True, slots=True)
class RecalibratedOptionUtility:
    """Item 29: Closed-loop operational learning update from a ValueClaimSettlement."""

    option_id: str
    prior_utility: float
    prior_confidence: float
    updated_utility: float
    updated_confidence: float
    hold_for_review: bool
    reason_code: str


def recalibrate_option_utility_from_settlement(
    *,
    option_id: str,
    prior_utility: float,
    prior_confidence: float,
    expected_improvement_per_event: Decimal,
    settlement: ValueClaimSettlement,
) -> RecalibratedOptionUtility:
    """Item 29: Adjust ActionOption utility & confidence from observed vs expected settlement."""

    if expected_improvement_per_event <= Decimal(0):
        raise ValueError("expected_improvement_per_event MUST be positive")
    if settlement.status is ValueClaimStatus.BLOCKED_POLICY_ESCAPE:
        return RecalibratedOptionUtility(
            option_id=option_id,
            prior_utility=prior_utility,
            prior_confidence=prior_confidence,
            updated_utility=-1.0,
            updated_confidence=0.0,
            hold_for_review=True,
            reason_code="policy_escape_quarantine",
        )
    if settlement.status is ValueClaimStatus.REGRESSED:
        return RecalibratedOptionUtility(
            option_id=option_id,
            prior_utility=prior_utility,
            prior_confidence=prior_confidence,
            updated_utility=round(max(-1.0, prior_utility - 0.5), 4),
            updated_confidence=round(max(0.1, prior_confidence * 0.5), 4),
            hold_for_review=True,
            reason_code="regression_demotion",
        )
    if settlement.status is ValueClaimStatus.IMPROVED:
        realized = settlement.conservative_improvement_per_event or Decimal(0)
        ratio = min(float(realized / expected_improvement_per_event), 1.25)
        new_util = round(min(1.0, max(-1.0, prior_utility * (0.5 + 0.5 * ratio))), 4)
        new_conf = round(min(0.99, prior_confidence + 0.05), 4)
        return RecalibratedOptionUtility(
            option_id=option_id,
            prior_utility=prior_utility,
            prior_confidence=prior_confidence,
            updated_utility=new_util,
            updated_confidence=new_conf,
            hold_for_review=False,
            reason_code="verified_improvement_boost",
        )
    return RecalibratedOptionUtility(
        option_id=option_id,
        prior_utility=prior_utility,
        prior_confidence=prior_confidence,
        updated_utility=round(prior_utility * 0.85, 4),
        updated_confidence=round(max(0.1, prior_confidence - 0.05), 4),
        hold_for_review=False,
        reason_code="inconclusive_attenuation",
    )


@dataclass(frozen=True, slots=True)
class SreAgentParityCase:
    """Item 30: One incident question comparing FDAI vs Azure SRE Agent against ground truth."""

    case_id: str
    ground_truth_cause_ref: str | None
    should_abstain: bool
    fdai_cause_ref: str | None
    fdai_abstained: bool
    fdai_citations_valid: bool
    peer_cause_ref: str | None
    peer_abstained: bool
    peer_citations_valid: bool


@dataclass(frozen=True, slots=True)
class SreAgentParityReport:
    """Item 30: Redacted parity benchmark report between FDAI and Azure SRE Agent."""

    total_cases: int
    fdai_accuracy: float
    peer_accuracy: float
    fdai_safe_abstention_rate: float
    peer_safe_abstention_rate: float
    parity_satisfied: bool
    report_digest: str
    execution_authority: Literal[False] = False


def evaluate_sre_agent_parity_cohort(
    cases: Sequence[SreAgentParityCase],
) -> SreAgentParityReport:
    """Item 30: Score FDAI vs Azure SRE Agent on accuracy, citation validity, and abstention."""

    if not cases or len({c.case_id for c in cases}) != len(cases):
        raise ValueError("SreAgentParityCase list MUST be non-empty and unique")
    fdai_ok = 0
    peer_ok = 0
    abstain_cases = 0
    fdai_abstain_ok = 0
    peer_abstain_ok = 0
    for c in cases:
        if c.should_abstain:
            abstain_cases += 1
            if c.fdai_abstained:
                fdai_ok += 1
                fdai_abstain_ok += 1
            if c.peer_abstained:
                peer_ok += 1
                peer_abstain_ok += 1
        else:
            if (
                not c.fdai_abstained
                and c.fdai_cause_ref == c.ground_truth_cause_ref
                and c.fdai_citations_valid
            ):
                fdai_ok += 1
            if (
                not c.peer_abstained
                and c.peer_cause_ref == c.ground_truth_cause_ref
                and c.peer_citations_valid
            ):
                peer_ok += 1
    n = len(cases)
    fdai_acc = round(fdai_ok / n, 6)
    peer_acc = round(peer_ok / n, 6)
    fdai_abs = round(fdai_abstain_ok / abstain_cases, 6) if abstain_cases else 1.0
    peer_abs = round(peer_abstain_ok / abstain_cases, 6) if abstain_cases else 1.0
    satisfied = fdai_acc >= peer_acc and fdai_abs >= peer_abs
    digest = content_digest(
        {
            "total_cases": n,
            "fdai_accuracy": fdai_acc,
            "peer_accuracy": peer_acc,
            "fdai_safe_abstention_rate": fdai_abs,
            "peer_safe_abstention_rate": peer_abs,
            "parity_satisfied": satisfied,
        }
    )
    return SreAgentParityReport(
        total_cases=n,
        fdai_accuracy=fdai_acc,
        peer_accuracy=peer_acc,
        fdai_safe_abstention_rate=fdai_abs,
        peer_safe_abstention_rate=peer_abs,
        parity_satisfied=satisfied,
        report_digest=digest,
    )


__all__ = [
    "AutoSettlementBatchResult",
    "PostWindowValueClaimAutoSettler",
    "RecalibratedOptionUtility",
    "SreAgentParityCase",
    "SreAgentParityReport",
    "StagingParityEvidence",
    "StagingParityReceipt",
    "WorkflowAutoDemotionReceipt",
    "WorkflowScaleSafetyController",
    "WorkflowSliSnapshot",
    "evaluate_sre_agent_parity_cohort",
    "recalibrate_option_utility_from_settlement",
    "verify_action_staging_parity",
]
