"""W7 exact-revision campaign and readiness mechanics."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fdai.core.vertical_packages import VerticalPackageActivationMetadata
from fdai.shared.providers.cost_governance_campaign import (
    CostCampaignEpisode,
    CostCampaignOutcome,
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

from fdai_cost_governance.validation import (
    CostObservationCampaignReducer,
    CostPromotionReadinessGate,
    CostReadinessBlock,
    CostReadinessDecision,
    CostReadinessTargetKind,
    CostReadinessThresholds,
    build_lifecycle_receipt,
)

_NOW = datetime(2026, 8, 29, tzinfo=UTC)
_DIGEST = "sha256:" + "1" * 64
_ACTIONS = ("remediate.right-size", "remediate.tag-add")
_WORKFLOW = "cost-aware-remediation"
_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests/integration/fixtures/cost_governance_w7_validation/synthetic-campaign.json"
)


def _pin(revision: int = 5) -> CostRevisionPin:
    return CostRevisionPin(
        package_id="cost-governance",
        package_version="0.1.1",
        source_revision="a" * 40,
        wheel_digest="sha256:" + "2" * 64,
        image_digest="sha256:" + "3" * 64,
        asset_manifest_digest="sha256:" + "4" * 64,
        semantic_profile_digest="sha256:" + "5" * 64,
        ontology_release_digest="sha256:" + "6" * 64,
        runtime_config_digest="sha256:" + "7" * 64,
        activation_revision=revision,
    )


def _episode(
    episode_id: str,
    *,
    outcome: CostCampaignOutcome,
    settlement: CostCampaignSettlement = CostCampaignSettlement.VERIFIED,
    evidence_kind: CostEvidenceKind = CostEvidenceKind.LIVE_AUTHORITATIVE,
    observed_offset: int = 0,
    target_refs: tuple[str, ...] = (*_ACTIONS, _WORKFLOW),
) -> CostCampaignEpisode:
    return CostCampaignEpisode(
        schema_version="1.0.0",
        campaign_id="campaign-001",
        episode_id=episode_id,
        revision=1,
        idempotency_key=f"episode:{episode_id}",
        revision_pin_digest=_pin().digest,
        evidence_kind=evidence_kind,
        outcome=outcome,
        reason="verified.outcome",
        target_refs=target_refs,
        settlement_statuses=(settlement,),
        recovery_attempts=1,
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
        observed_at=_NOW + timedelta(seconds=observed_offset),
        evidence_refs=(f"evidence:{episode_id}",),
        retention_until=_NOW + timedelta(days=90),
    )


def _receipt(
    operation: CostLifecycleOperation,
    revision: int,
    *,
    pin: CostRevisionPin | None = None,
    evidence_kind: CostEvidenceKind = CostEvidenceKind.LIVE_AUTHORITATIVE,
) -> CostLifecycleReceipt:
    enabled = operation not in {
        CostLifecycleOperation.INSTALL,
        CostLifecycleOperation.DISABLE,
    }
    return CostLifecycleReceipt(
        schema_version="1.0.0",
        receipt_id=f"receipt:{operation.value}:{revision}",
        idempotency_key=f"lifecycle:{operation.value}:{revision}",
        operation=operation,
        outcome=CostLifecycleOutcome.SUCCEEDED,
        revision_pin=pin or _pin(revision),
        available=True,
        enabled=enabled,
        occurred_at=_NOW + timedelta(minutes=revision),
        evidence_kind=evidence_kind,
        evidence_refs=(f"lifecycle:{operation.value}",),
        retention_until=_NOW + timedelta(days=90),
    )


def _receipts() -> tuple[CostLifecycleReceipt, ...]:
    return (
        _receipt(CostLifecycleOperation.INSTALL, 1),
        _receipt(CostLifecycleOperation.ENABLE, 2),
        _receipt(CostLifecycleOperation.DISABLE, 3),
        _receipt(CostLifecycleOperation.UPGRADE, 4),
        _receipt(CostLifecycleOperation.ROLLBACK, 5),
    )


def _report(
    *,
    evidence_kind: CostEvidenceKind = CostEvidenceKind.LIVE_AUTHORITATIVE,
    target: str | None = None,
):
    episodes = (
        _episode(
            "beneficial",
            outcome=CostCampaignOutcome.BENEFICIAL_ACTION,
            evidence_kind=evidence_kind,
        ),
        _episode(
            "rollback",
            outcome=CostCampaignOutcome.ROLLBACK,
            evidence_kind=evidence_kind,
            observed_offset=3_600,
        ),
    )
    return CostObservationCampaignReducer().reduce(_pin(), episodes, review_target_id=target)


def test_reducer_keeps_all_outcomes_and_excludes_unscorable_success() -> None:
    episodes = (
        _episode("beneficial", outcome=CostCampaignOutcome.BENEFICIAL_ACTION),
        _episode("noop", outcome=CostCampaignOutcome.NO_OP),
        _episode("deny", outcome=CostCampaignOutcome.DENY),
        _episode("hold", outcome=CostCampaignOutcome.HOLD_UNRESOLVED),
        _episode("approval", outcome=CostCampaignOutcome.APPROVAL),
        _episode("execute", outcome=CostCampaignOutcome.EXECUTE),
        _episode("rollback", outcome=CostCampaignOutcome.ROLLBACK),
        replace(
            _episode("excluded", outcome=CostCampaignOutcome.NO_OP),
            policy_excluded=True,
            decision_correct=False,
            settlement_statuses=(CostCampaignSettlement.UNSCORABLE,),
        ),
        replace(
            _episode("failed", outcome=CostCampaignOutcome.EXECUTE),
            settlement_statuses=(CostCampaignSettlement.FAILED,),
            decision_correct=False,
        ),
        replace(
            _episode("censored", outcome=CostCampaignOutcome.EXECUTE),
            settlement_statuses=(CostCampaignSettlement.CENSORED,),
            decision_correct=False,
        ),
    )

    report = CostObservationCampaignReducer().reduce(_pin(), episodes)

    assert report.sample_count == 10
    assert report.eligible_count == 9
    assert report.excluded_count == 1
    assert report.beneficial_action_count == 1
    assert (report.no_op_count, report.deny_count, report.hold_unresolved_count) == (
        2,
        1,
        1,
    )
    assert (report.approval_count, report.execute_count, report.rollback_count) == (
        1,
        3,
        1,
    )
    assert (
        report.verified_settlement_count,
        report.failed_settlement_count,
        report.censored_settlement_count,
        report.unscorable_settlement_count,
    ) == (7, 1, 1, 1)
    assert report.accuracy == Decimal(7) / Decimal(9)
    assert CostValidationStopCondition.MISSING_SETTLEMENT in report.stop_conditions


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (
            {"ontology_competency_passed": False},
            CostValidationStopCondition.ONTOLOGY_COMPETENCY_REGRESSION,
        ),
        ({"topic_owner_correct": False}, CostValidationStopCondition.WRONG_TOPIC_OWNER),
        (
            {"protected_objectives_complete": False},
            CostValidationStopCondition.MISSING_PROTECTED_OBJECTIVE,
        ),
        ({"safeguards_complete": False}, CostValidationStopCondition.MISSING_SAFEGUARD),
        (
            {"hard_dependencies_complete": False},
            CostValidationStopCondition.MISSING_HARD_DEPENDENCY,
        ),
        (
            {"effect_path_complete": False},
            CostValidationStopCondition.MISSING_EFFECT_PATH,
        ),
        (
            {"parity_explained": False},
            CostValidationStopCondition.UNEXPLAINED_PARITY_DIFFERENCE,
        ),
        ({"policy_escape": True}, CostValidationStopCondition.POLICY_ESCAPE),
        (
            {"objective_regression": True},
            CostValidationStopCondition.OBJECTIVE_REGRESSION,
        ),
        (
            {"settlement_statuses": (CostCampaignSettlement.CENSORED,)},
            CostValidationStopCondition.MISSING_SETTLEMENT,
        ),
        (
            {"rollback_evidence_complete": False},
            CostValidationStopCondition.FAILED_ROLLBACK,
        ),
        (
            {"unauthorized_disclosure": True},
            CostValidationStopCondition.DISCLOSURE_LEAK,
        ),
    ],
)
def test_every_release_stop_condition_is_explicit(
    changes: dict[str, object],
    expected: CostValidationStopCondition,
) -> None:
    episode = replace(_episode("rollback", outcome=CostCampaignOutcome.ROLLBACK), **changes)
    report = CostObservationCampaignReducer().reduce(_pin(), (episode,))
    assert expected in report.stop_conditions
    result = CostPromotionReadinessGate().evaluate(
        report=report,
        lifecycle_receipts=_receipts(),
        thresholds=CostReadinessThresholds(1, 1, Decimal("0")),
        target_kind=CostReadinessTargetKind.PACKAGE_ACTIVATION,
        target_id="cost-governance",
    )
    assert CostReadinessBlock(expected.value) in result.blocks


def test_reducer_rejects_revision_duplicates_and_bounds() -> None:
    episode = _episode("one", outcome=CostCampaignOutcome.NO_OP)
    with pytest.raises(ValueError, match="mismatched revision"):
        CostObservationCampaignReducer().reduce(
            _pin(), (replace(episode, revision_pin_digest=_DIGEST),)
        )
    with pytest.raises(ValueError, match="duplicate"):
        CostObservationCampaignReducer().reduce(_pin(), (episode, episode))
    with pytest.raises(ValueError, match="sample bound"):
        CostObservationCampaignReducer(maximum_samples=1).reduce(
            _pin(),
            (
                episode,
                replace(
                    episode,
                    episode_id="two",
                    idempotency_key="episode:two",
                ),
            ),
        )


def test_reducer_is_reorder_and_restart_deterministic() -> None:
    episodes = (
        _episode(
            "first",
            outcome=CostCampaignOutcome.NO_OP,
            observed_offset=10,
        ),
        _episode(
            "second",
            outcome=CostCampaignOutcome.DENY,
            observed_offset=20,
        ),
    )
    reducer = CostObservationCampaignReducer()

    first = reducer.reduce(_pin(), episodes)
    restarted = CostObservationCampaignReducer().reduce(_pin(), tuple(reversed(episodes)))

    assert first == restarted
    assert first.digest == restarted.digest
    assert first.evidence_refs == ("evidence:first", "evidence:second")


def test_readiness_is_review_only_and_separate_per_target() -> None:
    gate = CostPromotionReadinessGate()
    thresholds = CostReadinessThresholds(2, 3_600, Decimal("1"))
    package_result = gate.evaluate(
        report=_report(),
        lifecycle_receipts=_receipts(),
        thresholds=thresholds,
        target_kind=CostReadinessTargetKind.PACKAGE_ACTIVATION,
        target_id="cost-governance",
    )
    action_results = tuple(
        gate.evaluate(
            report=_report(target=action_id),
            lifecycle_receipts=_receipts(),
            thresholds=thresholds,
            target_kind=CostReadinessTargetKind.ACTION_TYPE,
            target_id=action_id,
        )
        for action_id in _ACTIONS
    )
    workflow_result = gate.evaluate(
        report=_report(target=_WORKFLOW),
        lifecycle_receipts=_receipts(),
        thresholds=thresholds,
        target_kind=CostReadinessTargetKind.WORKFLOW,
        target_id=_WORKFLOW,
    )

    assert {
        package_result.decision,
        *(result.decision for result in action_results),
        workflow_result.decision,
    } == {CostReadinessDecision.READY_FOR_INDEPENDENT_REVIEW}
    assert len({item.target_id for item in (*action_results, workflow_result)}) == 3
    assert not hasattr(package_result, "approval_authority")
    assert not hasattr(package_result, "promotion_authority")


def test_synthetic_evidence_and_activation_never_promote() -> None:
    result = CostPromotionReadinessGate().evaluate(
        report=_report(evidence_kind=CostEvidenceKind.SYNTHETIC),
        lifecycle_receipts=tuple(
            replace(receipt, evidence_kind=CostEvidenceKind.SYNTHETIC) for receipt in _receipts()
        ),
        thresholds=CostReadinessThresholds(2, 3_600, Decimal("1")),
        target_kind=CostReadinessTargetKind.PACKAGE_ACTIVATION,
        target_id="cost-governance",
    )
    assert result.decision is CostReadinessDecision.BLOCKED
    assert CostReadinessBlock.MISSING_LIVE_AUTHORITATIVE_EVIDENCE in result.blocks
    assert not hasattr(result, "approval_authority")
    assert not hasattr(result, "promotion_authority")


def test_frozen_synthetic_fixture_proves_mechanics_but_not_operations() -> None:
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(fixture, dict)
    fixture_pin = fixture["revision_pin"]
    assert isinstance(fixture_pin, dict)
    assert fixture_pin["activation_revision"] == _pin().activation_revision
    value = fixture["outcomes"]
    assert isinstance(value, list)
    episodes = tuple(
        replace(
            _episode(
                str(item["episode_id"]),
                outcome=CostCampaignOutcome(str(item["outcome"])),
                settlement=CostCampaignSettlement(str(item["settlement"])),
                evidence_kind=CostEvidenceKind.SYNTHETIC,
                observed_offset=index * 600,
            ),
            campaign_id=str(fixture["campaign_id"]),
        )
        for index, raw in enumerate(value)
        for item in (raw if isinstance(raw, dict) else _invalid_fixture(raw),)
    )
    report = CostObservationCampaignReducer().reduce(_pin(), episodes)
    expected = fixture["expected"]
    assert isinstance(expected, dict)
    typed_expected = _string_dict(expected)

    assert report.sample_count == 7
    assert report.beneficial_action_count == typed_expected["beneficial_action"]
    assert report.no_op_count == typed_expected["no_op"]
    assert report.deny_count == typed_expected["deny"]
    assert report.hold_unresolved_count == typed_expected["hold_unresolved"]
    assert report.approval_count == typed_expected["approval"]
    assert report.execute_count == typed_expected["execute"]
    assert report.rollback_count == typed_expected["rollback"]
    result = CostPromotionReadinessGate().evaluate(
        report=report,
        lifecycle_receipts=tuple(
            replace(receipt, evidence_kind=CostEvidenceKind.SYNTHETIC) for receipt in _receipts()
        ),
        thresholds=CostReadinessThresholds(2, 600, Decimal("0")),
        target_kind=CostReadinessTargetKind.PACKAGE_ACTIVATION,
        target_id="cost-governance",
    )
    assert result.decision.value == typed_expected["operational_readiness"]
    assert (
        CostReadinessBlock.MISSING_LIVE_AUTHORITATIVE_EVIDENCE.value
        == typed_expected["operational_readiness_reason"]
    )
    assert CostReadinessBlock.MISSING_LIVE_AUTHORITATIVE_EVIDENCE in result.blocks


def test_readiness_blocks_revision_lifecycle_and_threshold_failures() -> None:
    report = replace(
        _report(),
        correct_decision_count=0,
        audit_complete_count=1,
        hard_dependency_complete_count=1,
    )
    bad_receipts = (
        _receipt(CostLifecycleOperation.ENABLE, 8),
        _receipt(CostLifecycleOperation.INSTALL, 8),
    )
    result = CostPromotionReadinessGate().evaluate(
        report=report,
        lifecycle_receipts=bad_receipts,
        thresholds=CostReadinessThresholds(20, 86_400, Decimal("1")),
        target_kind=CostReadinessTargetKind.ACTION_TYPE,
        target_id="different-action",
    )
    assert {
        CostReadinessBlock.REVISION_MISMATCH,
        CostReadinessBlock.LIFECYCLE_INCOMPLETE,
        CostReadinessBlock.INSUFFICIENT_COHORT,
        CostReadinessBlock.INSUFFICIENT_SHADOW_DWELL,
        CostReadinessBlock.ACCURACY_BELOW_MINIMUM,
        CostReadinessBlock.MISSING_AUDIT,
        CostReadinessBlock.MISSING_HARD_DEPENDENCY,
    } <= set(result.blocks)


def test_receipt_digest_detects_tampering_and_revision_identity() -> None:
    receipt = _receipt(CostLifecycleOperation.ENABLE, 2)
    assert receipt.verify_digest(receipt.digest)
    tampered = replace(receipt, evidence_refs=("tampered:evidence",))
    assert tampered.digest != receipt.digest
    assert not tampered.verify_digest(receipt.digest)
    assert replace(receipt.revision_pin, activation_revision=3).digest != _pin().digest


def test_receipt_builder_binds_manager_derived_artifact_identity() -> None:
    metadata = VerticalPackageActivationMetadata(
        vertical_id="finops",
        package_id="cost-governance",
        available=True,
        enabled=False,
        availability_reasons=(),
        package_version="0.1.1",
        image_digest="sha256:" + "3" * 64,
        asset_manifest_digest="sha256:" + "4" * 64,
        semantic_profile_digest="sha256:" + "5" * 64,
        ontology_release_digest="sha256:" + "6" * 64,
    )
    receipt = build_lifecycle_receipt(
        receipt_id="receipt:manager:install",
        idempotency_key="lifecycle:manager:install",
        metadata=metadata,
        source_revision="a" * 40,
        wheel_digest="sha256:" + "2" * 64,
        runtime_config_digest="sha256:" + "7" * 64,
        activation_revision=1,
        operation=CostLifecycleOperation.INSTALL,
        outcome=CostLifecycleOutcome.SUCCEEDED,
        occurred_at=_NOW,
        evidence_kind=CostEvidenceKind.SYNTHETIC,
        evidence_refs=("manager:activation:1",),
        retention_until=_NOW + timedelta(days=90),
    )

    assert receipt.revision_pin.package_id == metadata.package_id
    assert receipt.revision_pin.asset_manifest_digest == metadata.asset_manifest_digest
    assert receipt.revision_pin.semantic_profile_digest == metadata.semantic_profile_digest
    assert receipt.revision_pin.ontology_release_digest == metadata.ontology_release_digest
    assert not receipt.enabled


def test_no_validation_contract_grants_runtime_authority() -> None:
    for value in (
        _receipt(CostLifecycleOperation.ENABLE, 2),
        CostPromotionReadinessGate().evaluate(
            report=_report(),
            lifecycle_receipts=_receipts(),
            thresholds=CostReadinessThresholds(2, 3_600, Decimal("1")),
            target_kind=CostReadinessTargetKind.PACKAGE_ACTIVATION,
            target_id="cost-governance",
        ),
    ):
        assert not getattr(value, "approval_authority", False)
        assert not getattr(value, "execution_authority", False)
        assert not getattr(value, "promotion_authority", False)


def _invalid_fixture(value: object) -> dict[str, Any]:
    raise AssertionError(f"invalid fixture outcome: {value!r}")


def _string_dict(value: dict[object, object]) -> dict[str, Any]:
    return {str(key): item for key, item in value.items()}
