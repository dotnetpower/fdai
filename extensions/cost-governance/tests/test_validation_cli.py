from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fdai.shared.providers.cost_governance_campaign import (
    CostCampaignEpisode,
    CostCampaignOutcome,
    CostCampaignSettlement,
)
from fdai.shared.providers.cost_governance_lifecycle import (
    CostEvidenceKind,
    CostLifecycleOperation,
    CostLifecycleOutcome,
    CostLifecycleReceipt,
    CostRevisionPin,
)

from fdai_cost_governance.review_targets import CostReadinessTarget
from fdai_cost_governance.validation import (
    CostReadinessTargetKind,
    CostReadinessThresholds,
)
from fdai_cost_governance.validation_cli import evaluate_cost_campaign

_NOW = datetime(2026, 9, 12, tzinfo=UTC)
_ACTION = "remediate.right-size"
_WORKFLOW = "cost-aware-remediation"


def _pin(revision: int = 5) -> CostRevisionPin:
    return CostRevisionPin(
        package_id="cost-governance",
        package_version="0.1.1",
        source_revision="a" * 40,
        wheel_digest=f"sha256:{'b' * 64}",
        image_digest=f"sha256:{'c' * 64}",
        asset_manifest_digest=f"sha256:{'d' * 64}",
        semantic_profile_digest=f"sha256:{'e' * 64}",
        ontology_release_digest=f"sha256:{'f' * 64}",
        runtime_config_digest=f"sha256:{'0' * 64}",
        activation_revision=revision,
    )


def _receipt(operation: CostLifecycleOperation, revision: int) -> CostLifecycleReceipt:
    return CostLifecycleReceipt(
        schema_version="1.0.0",
        receipt_id=f"receipt:{operation.value}:{revision}",
        idempotency_key=f"receipt:{operation.value}:{revision}",
        operation=operation,
        outcome=CostLifecycleOutcome.SUCCEEDED,
        revision_pin=_pin(revision),
        available=True,
        enabled=operation not in {CostLifecycleOperation.INSTALL, CostLifecycleOperation.DISABLE},
        occurred_at=_NOW + timedelta(minutes=revision),
        evidence_kind=CostEvidenceKind.LIVE_AUTHORITATIVE,
        evidence_refs=(f"evidence:{operation.value}",),
        retention_until=_NOW + timedelta(days=400),
    )


def _receipts() -> tuple[CostLifecycleReceipt, ...]:
    return tuple(
        _receipt(operation, revision)
        for revision, operation in enumerate(CostLifecycleOperation, start=1)
    )


def _episode(
    episode_id: str,
    *,
    target_refs: tuple[str, ...],
    observed_at: datetime,
    outcome: CostCampaignOutcome,
) -> CostCampaignEpisode:
    return CostCampaignEpisode(
        schema_version="1.0.0",
        campaign_id="campaign-001",
        episode_id=episode_id,
        revision=1,
        idempotency_key=f"episode:{episode_id}",
        revision_pin_digest=_pin().digest,
        evidence_kind=CostEvidenceKind.LIVE_AUTHORITATIVE,
        outcome=outcome,
        reason="verified.outcome",
        target_refs=target_refs,
        settlement_statuses=(CostCampaignSettlement.VERIFIED,),
        recovery_attempts=0,
        policy_excluded=False,
        policy_escape=False,
        objective_regression=False,
        audit_complete=True,
        hard_dependencies_complete=True,
        unauthorized_disclosure=False,
        ontology_competency_passed=True,
        topic_owner_correct=True,
        protected_objectives_complete=True,
        safeguards_complete=True,
        effect_path_complete=True,
        parity_explained=True,
        rollback_evidence_complete=True,
        decision_correct=True,
        observed_at=observed_at,
        evidence_refs=(f"evidence:{episode_id}",),
        retention_until=_NOW + timedelta(days=400),
    )


def _target(kind: CostReadinessTargetKind, target_id: str) -> CostReadinessTarget:
    return CostReadinessTarget(
        kind=kind,
        target_id=target_id,
        thresholds=CostReadinessThresholds(2, 86_400, Decimal("1")),
    )


def test_evaluation_is_separate_and_blocks_missing_target_evidence() -> None:
    episodes = (
        _episode(
            "action-first",
            target_refs=(_ACTION,),
            observed_at=_NOW,
            outcome=CostCampaignOutcome.NO_OP,
        ),
        _episode(
            "action-second",
            target_refs=(_ACTION,),
            observed_at=_NOW + timedelta(days=1),
            outcome=CostCampaignOutcome.ROLLBACK,
        ),
    )
    targets = (
        _target(CostReadinessTargetKind.PACKAGE_ACTIVATION, "cost-governance"),
        _target(CostReadinessTargetKind.ACTION_TYPE, _ACTION),
        _target(CostReadinessTargetKind.WORKFLOW, _WORKFLOW),
    )

    result = evaluate_cost_campaign(
        campaign_id="campaign-001",
        revision_pin=_pin(),
        lifecycle_receipts=_receipts(),
        episodes=episodes,
        targets=targets,
    )

    assert result["ready"] is False
    assert set(result) == {
        "campaign_id",
        "ready",
        "revision_pin_digest",
        "targets",
    }
    records = {item["target_id"]: item for item in result["targets"]}
    assert records["cost-governance"]["decision"] == "ready-for-independent-review"
    assert records[_ACTION]["decision"] == "ready-for-independent-review"
    assert records[_WORKFLOW]["decision"] == "blocked"
    assert records[_WORKFLOW]["sample_count"] == 0
