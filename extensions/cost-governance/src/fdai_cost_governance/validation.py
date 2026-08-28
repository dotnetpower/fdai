"""Bounded campaign accounting and release-review mechanics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from fdai.core.vertical_packages import VerticalPackageActivationMetadata
from fdai.shared.providers.cost_governance_campaign import (
    CostCampaignEpisode,
    CostCampaignOutcome,
    CostCampaignReport,
    CostCampaignSettlement,
    CostValidationStopCondition,
)
from fdai.shared.providers.cost_governance_lifecycle import (
    CostEvidenceKind,
    CostLifecycleOperation,
    CostLifecycleOutcome,
    CostLifecycleReceipt,
    CostRevisionPin,
)

_CHANGED_OUTCOMES = {
    CostCampaignOutcome.BENEFICIAL_ACTION,
    CostCampaignOutcome.EXECUTE,
    CostCampaignOutcome.ROLLBACK,
}


class CostReadinessTargetKind(StrEnum):
    """Review target classes with independent lifecycle decisions."""

    PACKAGE_ACTIVATION = "package-activation"
    ACTION_TYPE = "action-type"
    WORKFLOW = "workflow"


class CostReadinessDecision(StrEnum):
    """Review-only result that never approves or promotes a target."""

    BLOCKED = "blocked"
    READY_FOR_INDEPENDENT_REVIEW = "ready-for-independent-review"


class CostReadinessBlock(StrEnum):
    """Stable release blocks, including every operational stop condition."""

    MISSING_LIVE_AUTHORITATIVE_EVIDENCE = "missing-live-authoritative-evidence"
    REVISION_MISMATCH = "revision-mismatch"
    LIFECYCLE_INCOMPLETE = "lifecycle-incomplete"
    INSUFFICIENT_COHORT = "insufficient-cohort"
    INSUFFICIENT_SHADOW_DWELL = "insufficient-shadow-dwell"
    ACCURACY_BELOW_MINIMUM = "accuracy-below-minimum"
    MISSING_AUDIT = "missing-audit"
    ONTOLOGY_COMPETENCY_REGRESSION = "ontology-competency-regression"
    WRONG_TOPIC_OWNER = "wrong-topic-owner"
    MISSING_PROTECTED_OBJECTIVE = "missing-protected-objective"
    MISSING_SAFEGUARD = "missing-safeguard"
    MISSING_HARD_DEPENDENCY = "missing-hard-dependency"
    MISSING_EFFECT_PATH = "missing-effect-path"
    UNEXPLAINED_PARITY_DIFFERENCE = "unexplained-parity-difference"
    POLICY_ESCAPE = "policy-escape"
    OBJECTIVE_REGRESSION = "objective-regression"
    MISSING_SETTLEMENT = "missing-settlement"
    FAILED_ROLLBACK = "failed-rollback"
    DISCLOSURE_LEAK = "disclosure-leak"


@dataclass(frozen=True, slots=True)
class CostReadinessThresholds:
    """Configured promotion thresholds; values carry no promotion authority."""

    minimum_samples: int
    minimum_shadow_dwell_seconds: int
    minimum_accuracy: Decimal

    def __post_init__(self) -> None:
        if self.minimum_samples < 1 or self.minimum_shadow_dwell_seconds < 1:
            raise ValueError("readiness sample and dwell thresholds MUST be positive")
        if not Decimal("0") <= self.minimum_accuracy <= Decimal("1"):
            raise ValueError("readiness minimum_accuracy MUST be in [0, 1]")


@dataclass(frozen=True, slots=True)
class CostReadinessResult:
    """Typed auditable review input with no approval or promotion capability."""

    target_kind: CostReadinessTargetKind
    target_id: str
    decision: CostReadinessDecision
    blocks: tuple[CostReadinessBlock, ...]
    campaign_report_digest: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.target_id or len(self.target_id) > 256:
            raise ValueError("readiness target_id MUST be non-empty and bounded")
        blocks = tuple(sorted(set(self.blocks), key=str))
        object.__setattr__(self, "blocks", blocks)
        object.__setattr__(self, "evidence_refs", tuple(dict.fromkeys(self.evidence_refs)))
        if (self.decision is CostReadinessDecision.BLOCKED) != bool(blocks):
            raise ValueError("readiness decision and release blocks are inconsistent")


def build_lifecycle_receipt(
    *,
    receipt_id: str,
    idempotency_key: str,
    metadata: VerticalPackageActivationMetadata,
    source_revision: str,
    wheel_digest: str,
    runtime_config_digest: str,
    activation_revision: int,
    operation: CostLifecycleOperation,
    outcome: CostLifecycleOutcome,
    occurred_at: datetime,
    evidence_kind: CostEvidenceKind,
    evidence_refs: tuple[str, ...],
    retention_until: datetime,
    legal_hold_ref: str | None = None,
) -> CostLifecycleReceipt:
    """Bind manager-derived lifecycle state to one exact immutable receipt."""

    return CostLifecycleReceipt(
        schema_version="1.0.0",
        receipt_id=receipt_id,
        idempotency_key=idempotency_key,
        operation=operation,
        outcome=outcome,
        revision_pin=CostRevisionPin(
            package_id=metadata.package_id,
            package_version=metadata.package_version,
            source_revision=source_revision,
            wheel_digest=wheel_digest,
            image_digest=metadata.image_digest,
            asset_manifest_digest=metadata.asset_manifest_digest,
            semantic_profile_digest=metadata.semantic_profile_digest,
            ontology_release_digest=metadata.ontology_release_digest,
            runtime_config_digest=runtime_config_digest,
            activation_revision=activation_revision,
        ),
        available=metadata.available,
        enabled=metadata.enabled,
        occurred_at=occurred_at,
        evidence_kind=evidence_kind,
        evidence_refs=evidence_refs,
        retention_until=retention_until,
        legal_hold=legal_hold_ref is not None,
        legal_hold_ref=legal_hold_ref,
    )


class CostObservationCampaignReducer:
    """Reduce one exact-revision bounded cohort without manufacturing success."""

    def __init__(self, *, maximum_samples: int = 10_000) -> None:
        if maximum_samples < 1:
            raise ValueError("campaign maximum_samples MUST be positive")
        self._maximum_samples = maximum_samples

    def reduce(
        self,
        revision_pin: CostRevisionPin,
        episodes: Iterable[CostCampaignEpisode],
        *,
        review_target_id: str | None = None,
    ) -> CostCampaignReport:
        """Validate, optionally target-filter, and account for one campaign."""

        source = tuple(episodes)
        if len(source) > self._maximum_samples:
            raise ValueError("campaign exceeds the configured sample bound")
        selected = tuple(
            sorted(
                (
                    episode
                    for episode in source
                    if review_target_id is None or review_target_id in episode.target_refs
                ),
                key=lambda item: (item.observed_at, item.episode_id, item.revision),
            )
        )
        if not selected:
            raise ValueError("campaign MUST contain at least one selected episode")
        if any(episode.revision_pin_digest != revision_pin.digest for episode in selected):
            raise ValueError("campaign contains mixed or mismatched revision evidence")
        identities = {(episode.episode_id, episode.revision) for episode in selected}
        keys = {episode.idempotency_key for episode in selected}
        if len(identities) != len(selected) or len(keys) != len(selected):
            raise ValueError("campaign contains duplicate episode or idempotency identity")

        outcomes = Counter(episode.outcome for episode in selected)
        settlements = Counter(
            status for episode in selected for status in episode.settlement_statuses
        )
        eligible = tuple(episode for episode in selected if not episode.policy_excluded)
        beneficial = sum(
            episode.outcome is CostCampaignOutcome.BENEFICIAL_ACTION
            and bool(episode.settlement_statuses)
            and all(
                status is CostCampaignSettlement.VERIFIED for status in episode.settlement_statuses
            )
            for episode in eligible
        )
        approval_reasons = Counter(
            episode.reason
            for episode in selected
            if episode.outcome is CostCampaignOutcome.APPROVAL
        )
        stop_conditions = _stop_conditions(selected)
        observed = [episode.observed_at for episode in selected]
        return CostCampaignReport(
            schema_version="1.0.0",
            campaign_id=selected[0].campaign_id,
            review_target_id=review_target_id,
            revision_pin=revision_pin,
            sample_count=len(selected),
            eligible_count=len(eligible),
            excluded_count=len(selected) - len(eligible),
            beneficial_action_count=beneficial,
            no_op_count=outcomes[CostCampaignOutcome.NO_OP],
            deny_count=outcomes[CostCampaignOutcome.DENY],
            hold_unresolved_count=outcomes[CostCampaignOutcome.HOLD_UNRESOLVED],
            approval_count=outcomes[CostCampaignOutcome.APPROVAL],
            execute_count=outcomes[CostCampaignOutcome.EXECUTE],
            rollback_count=outcomes[CostCampaignOutcome.ROLLBACK],
            recovery_attempt_count=sum(item.recovery_attempts for item in selected),
            verified_settlement_count=settlements[CostCampaignSettlement.VERIFIED],
            failed_settlement_count=settlements[CostCampaignSettlement.FAILED],
            censored_settlement_count=settlements[CostCampaignSettlement.CENSORED],
            unscorable_settlement_count=settlements[CostCampaignSettlement.UNSCORABLE],
            policy_escape_count=sum(item.policy_escape for item in selected),
            objective_regression_count=sum(item.objective_regression for item in selected),
            audit_complete_count=sum(item.audit_complete for item in selected),
            hard_dependency_complete_count=sum(
                item.hard_dependencies_complete for item in selected
            ),
            unauthorized_disclosure_count=sum(item.unauthorized_disclosure for item in selected),
            correct_decision_count=sum(item.decision_correct for item in eligible),
            shadow_dwell_seconds=int((max(observed) - min(observed)).total_seconds()),
            evidence_kinds=tuple(item.evidence_kind for item in selected),
            stop_conditions=stop_conditions,
            approval_reason_counts=approval_reasons,
            evidence_refs=tuple(ref for episode in selected for ref in episode.evidence_refs),
        )


class CostPromotionReadinessGate:
    """Evaluate release blocks and stop at independent review readiness."""

    def evaluate(
        self,
        *,
        report: CostCampaignReport,
        lifecycle_receipts: tuple[CostLifecycleReceipt, ...],
        thresholds: CostReadinessThresholds,
        target_kind: CostReadinessTargetKind,
        target_id: str,
    ) -> CostReadinessResult:
        """Return blocked or review-ready without approving activation or promotion."""

        blocks = {CostReadinessBlock(condition.value) for condition in report.stop_conditions}
        if set(report.evidence_kinds) != {CostEvidenceKind.LIVE_AUTHORITATIVE}:
            blocks.add(CostReadinessBlock.MISSING_LIVE_AUTHORITATIVE_EVIDENCE)
        if report.sample_count < thresholds.minimum_samples:
            blocks.add(CostReadinessBlock.INSUFFICIENT_COHORT)
        if report.shadow_dwell_seconds < thresholds.minimum_shadow_dwell_seconds:
            blocks.add(CostReadinessBlock.INSUFFICIENT_SHADOW_DWELL)
        if report.accuracy < thresholds.minimum_accuracy:
            blocks.add(CostReadinessBlock.ACCURACY_BELOW_MINIMUM)
        if report.audit_complete_count != report.sample_count:
            blocks.add(CostReadinessBlock.MISSING_AUDIT)
        if report.hard_dependency_complete_count != report.sample_count:
            blocks.add(CostReadinessBlock.MISSING_HARD_DEPENDENCY)
        if report.policy_escape_count:
            blocks.add(CostReadinessBlock.POLICY_ESCAPE)
        if report.objective_regression_count:
            blocks.add(CostReadinessBlock.OBJECTIVE_REGRESSION)
        if report.unauthorized_disclosure_count:
            blocks.add(CostReadinessBlock.DISCLOSURE_LEAK)
        if (
            report.censored_settlement_count
            or report.unscorable_settlement_count
            or report.verified_settlement_count + report.failed_settlement_count == 0
        ):
            blocks.add(CostReadinessBlock.MISSING_SETTLEMENT)
        if report.rollback_count == 0:
            blocks.add(CostReadinessBlock.FAILED_ROLLBACK)
        blocks.update(_lifecycle_blocks(report.revision_pin, lifecycle_receipts))
        if target_kind is CostReadinessTargetKind.PACKAGE_ACTIVATION:
            if report.review_target_id is not None or target_id != report.revision_pin.package_id:
                blocks.add(CostReadinessBlock.REVISION_MISMATCH)
        elif report.review_target_id != target_id:
            blocks.add(CostReadinessBlock.REVISION_MISMATCH)

        ordered = tuple(sorted(blocks, key=str))
        return CostReadinessResult(
            target_kind=target_kind,
            target_id=target_id,
            decision=(
                CostReadinessDecision.BLOCKED
                if ordered
                else CostReadinessDecision.READY_FOR_INDEPENDENT_REVIEW
            ),
            blocks=ordered,
            campaign_report_digest=report.digest,
            evidence_refs=tuple(
                dict.fromkeys(
                    (
                        f"campaign-report:{report.digest}",
                        *(receipt.receipt_id for receipt in lifecycle_receipts),
                    )
                )
            ),
        )


def _stop_conditions(
    episodes: tuple[CostCampaignEpisode, ...],
) -> tuple[CostValidationStopCondition, ...]:
    conditions: set[CostValidationStopCondition] = set()
    checks = (
        ("ontology_competency_passed", CostValidationStopCondition.ONTOLOGY_COMPETENCY_REGRESSION),
        ("topic_owner_correct", CostValidationStopCondition.WRONG_TOPIC_OWNER),
        ("protected_objectives_complete", CostValidationStopCondition.MISSING_PROTECTED_OBJECTIVE),
        ("safeguards_complete", CostValidationStopCondition.MISSING_SAFEGUARD),
        ("hard_dependencies_complete", CostValidationStopCondition.MISSING_HARD_DEPENDENCY),
        ("effect_path_complete", CostValidationStopCondition.MISSING_EFFECT_PATH),
        ("parity_explained", CostValidationStopCondition.UNEXPLAINED_PARITY_DIFFERENCE),
    )
    for episode in episodes:
        conditions.update(condition for field, condition in checks if not getattr(episode, field))
        if episode.policy_escape:
            conditions.add(CostValidationStopCondition.POLICY_ESCAPE)
        if episode.objective_regression:
            conditions.add(CostValidationStopCondition.OBJECTIVE_REGRESSION)
        if episode.unauthorized_disclosure:
            conditions.add(CostValidationStopCondition.DISCLOSURE_LEAK)
        if episode.outcome in _CHANGED_OUTCOMES and (
            not episode.settlement_statuses
            or any(
                status
                in {
                    CostCampaignSettlement.CENSORED,
                    CostCampaignSettlement.UNSCORABLE,
                }
                for status in episode.settlement_statuses
            )
        ):
            conditions.add(CostValidationStopCondition.MISSING_SETTLEMENT)
        if (
            episode.outcome is CostCampaignOutcome.ROLLBACK
            and not episode.rollback_evidence_complete
        ):
            conditions.add(CostValidationStopCondition.FAILED_ROLLBACK)
    return tuple(sorted(conditions, key=str))


def _lifecycle_blocks(
    revision_pin: CostRevisionPin,
    receipts: tuple[CostLifecycleReceipt, ...],
) -> set[CostReadinessBlock]:
    blocks: set[CostReadinessBlock] = set()
    operations = {
        receipt.operation
        for receipt in receipts
        if receipt.outcome is CostLifecycleOutcome.SUCCEEDED
    }
    if operations != set(CostLifecycleOperation):
        blocks.add(CostReadinessBlock.LIFECYCLE_INCOMPLETE)
    if not receipts or any(
        receipt.evidence_kind is not CostEvidenceKind.LIVE_AUTHORITATIVE for receipt in receipts
    ):
        blocks.add(CostReadinessBlock.MISSING_LIVE_AUTHORITATIVE_EVIDENCE)
    successful = tuple(
        receipt for receipt in receipts if receipt.outcome is CostLifecycleOutcome.SUCCEEDED
    )
    current = (
        max(successful, key=lambda item: item.revision_pin.activation_revision)
        if successful
        else None
    )
    if (
        current is None
        or current.revision_pin != revision_pin
        or not current.available
        or not current.enabled
    ):
        blocks.add(CostReadinessBlock.REVISION_MISMATCH)
    activation_revisions = [item.revision_pin.activation_revision for item in receipts]
    if len(activation_revisions) != len(set(activation_revisions)):
        blocks.add(CostReadinessBlock.REVISION_MISMATCH)
    return blocks


__all__ = [
    "CostObservationCampaignReducer",
    "CostPromotionReadinessGate",
    "CostReadinessBlock",
    "CostReadinessDecision",
    "CostReadinessResult",
    "CostReadinessTargetKind",
    "CostReadinessThresholds",
    "build_lifecycle_receipt",
]
