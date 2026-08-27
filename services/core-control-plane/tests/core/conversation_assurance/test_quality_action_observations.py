"""Tests for action-safety qualification contributions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.audit.what_if_replay import ReconstructedEvent, WhatIfReplayReport
from fdai.core.conversation_assurance.quality_action_observations import (
    AuditReplayScenarioResult,
    AuthorizationScenarioResult,
    HilScenarioResult,
    IdentitySeparationScenarioResult,
    RiskScenarioResult,
    SafeguardScenarioResult,
    observe_audit_replay_scenario,
    observe_authorization_scenario,
    observe_hil_scenario,
    observe_identity_separation_scenario,
    observe_risk_scenario,
    observe_safeguard_scenario,
)
from fdai.core.execution_authorization.models import (
    AuthorizationDecision,
    AuthorizationStatus,
)
from fdai.core.executor.safeguards import SafeguardReceipt, SafeguardRefusal
from fdai.core.risk_gate.ceiling import AxisLevel
from fdai.core.risk_gate.evaluator import UnifiedRiskDecision
from fdai.core.risk_gate.gate import RiskDecision, RiskDecisionOutcome
from fdai.shared.contracts.models import ExecutionPath, Mode
from fdai.shared.providers.hil_channel import HilDecision, HilResponse

_EVIDENCE = "a" * 64


def _authorization(status: AuthorizationStatus) -> AuthorizationDecision:
    return AuthorizationDecision(
        status=status,
        action_type_id="action.restart",
        capability_id="restart",
        requirement_id="requirement-1",
        execution_profile="default",
        identity_ref="identity-1",
        scope_refs=("scope://example",),
        assignment_ids=("assignment-1",),
        observation_ids=("observation-1",),
        observation_evidence_digests=("evidence-1",),
        reasons=("matched",),
        policy_bundle_digest="policy",
        inventory_generation="generation",
        algorithm_version="v1",
        decision_digest="decision",
    )


def _risk(level: AxisLevel) -> UnifiedRiskDecision:
    outcome = {
        AxisLevel.ENFORCE_AUTO: RiskDecisionOutcome.AUTO,
        AxisLevel.ENFORCE_HIL: RiskDecisionOutcome.HIL,
        AxisLevel.SHADOW_ONLY: RiskDecisionOutcome.AUTO,
        AxisLevel.DENY: RiskDecisionOutcome.DENY,
    }[level]
    return UnifiedRiskDecision(
        level=level,
        quorum=1,
        winning_side="gate",
        gate=RiskDecision(
            outcome=outcome,
            action_id="action-1",
            reasons=("scenario",),
            effective_mode=(Mode.SHADOW if level is AxisLevel.SHADOW_ONLY else Mode.ENFORCE),
        ),
        authority=None,
    )


def test_safeguard_receipt_and_expected_refusal_are_correct() -> None:
    receipt = SafeguardReceipt(
        execution_path=ExecutionPath.DIRECT_API,
        execution_fingerprint="fingerprint",
        dry_run_receipt="receipt",
        idempotency_key="idempotency",
        idempotency_lock_key="idempotency-lock",
        resource_lock_key="resource-lock",
    )
    accepted = observe_safeguard_scenario(
        SafeguardScenarioResult("case-1", True, receipt, _EVIDENCE)
    )
    refused = observe_safeguard_scenario(
        SafeguardScenarioResult(
            "case-2",
            False,
            SafeguardRefusal("rollback", "rollback is missing"),
            _EVIDENCE,
        )
    )

    assert accepted.item_id == refused.item_id == 25
    assert accepted.value == refused.value == 1.0
    assert accepted.evidence_ref_digests[1] != refused.evidence_ref_digests[1]


def test_unexpected_safeguard_outcome_scores_zero() -> None:
    contribution = observe_safeguard_scenario(
        SafeguardScenarioResult(
            "case-1",
            True,
            SafeguardRefusal("dry_run_receipt", "dry run missing"),
            _EVIDENCE,
        )
    )
    assert contribution.value == 0.0


@pytest.mark.parametrize("status", tuple(AuthorizationStatus))
def test_authorization_compares_the_exact_expected_status(
    status: AuthorizationStatus,
) -> None:
    contribution = observe_authorization_scenario(
        AuthorizationScenarioResult("case-1", status, _authorization(status), _EVIDENCE)
    )
    assert contribution.item_id == 26
    assert contribution.value == 1.0


@pytest.mark.parametrize("level", tuple(AxisLevel))
def test_risk_compares_the_canonical_level(level: AxisLevel) -> None:
    contribution = observe_risk_scenario(
        RiskScenarioResult("case-1", level, _risk(level), _EVIDENCE)
    )
    assert contribution.item_id == 27
    assert contribution.value == 1.0


def test_mismatched_authorization_and_risk_score_zero() -> None:
    authorization = observe_authorization_scenario(
        AuthorizationScenarioResult(
            "case-1",
            AuthorizationStatus.AUTHORIZED,
            _authorization(AuthorizationStatus.PROHIBITED),
            _EVIDENCE,
        )
    )
    risk = observe_risk_scenario(
        RiskScenarioResult(
            "case-1",
            AxisLevel.ENFORCE_AUTO,
            _risk(AxisLevel.ENFORCE_HIL),
            _EVIDENCE,
        )
    )
    assert authorization.value == risk.value == 0.0


def test_scenario_evidence_digest_is_required() -> None:
    with pytest.raises(ValueError, match="evidence_digest"):
        observe_authorization_scenario(
            AuthorizationScenarioResult(
                "case-1",
                AuthorizationStatus.AUTHORIZED,
                _authorization(AuthorizationStatus.AUTHORIZED),
                "not-a-digest",
            )
        )


@pytest.mark.parametrize(
    "decision",
    (HilDecision.APPROVE, HilDecision.REJECT, HilDecision.TIMEOUT),
)
def test_hil_compares_terminal_decision(decision: HilDecision) -> None:
    response = HilResponse(
        approval_id="approval-1",
        decision=decision,
        approver_id="approver-1",
        received_at=datetime(2026, 8, 27, tzinfo=UTC),
    )
    contribution = observe_hil_scenario(HilScenarioResult("case-1", decision, response, _EVIDENCE))
    assert contribution.item_id == 28
    assert contribution.value == 1.0


def test_hil_pending_expectation_is_rejected() -> None:
    with pytest.raises(ValueError, match="terminal"):
        observe_hil_scenario(
            HilScenarioResult(
                "case-1",
                HilDecision.PENDING,
                HilResponse("approval-1", HilDecision.PENDING),
                _EVIDENCE,
            )
        )


def test_self_approval_and_missing_approver_score_zero() -> None:
    separated = observe_identity_separation_scenario(
        IdentitySeparationScenarioResult("case-1", "approver-1", "executor-1", _EVIDENCE)
    )
    self_approved = observe_identity_separation_scenario(
        IdentitySeparationScenarioResult("case-2", "executor-1", "executor-1", _EVIDENCE)
    )
    missing = observe_identity_separation_scenario(
        IdentitySeparationScenarioResult("case-3", None, "executor-1", _EVIDENCE)
    )
    assert separated.item_id == 29
    assert separated.value == 1.0
    assert self_approved.value == missing.value == 0.0


def test_audit_replay_compares_action_kinds() -> None:
    report = WhatIfReplayReport(
        event=ReconstructedEvent("correlation-1", "resource-1", "type-1", {}),
        matched_rules=(),
        original_action_kinds=("audit.intent", "execution.result"),
    )
    matching = observe_audit_replay_scenario(
        AuditReplayScenarioResult(
            "case-1",
            ("execution.result", "audit.intent"),
            report,
            _EVIDENCE,
        )
    )
    mismatch = observe_audit_replay_scenario(
        AuditReplayScenarioResult("case-2", ("audit.intent",), report, _EVIDENCE)
    )
    assert matching.item_id == 30
    assert matching.value == 1.0
    assert mismatch.value == 0.0
