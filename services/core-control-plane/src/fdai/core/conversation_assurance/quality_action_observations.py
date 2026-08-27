"""Qualification contributions from existing action-safety decision results."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from fdai.core.audit.what_if_replay import WhatIfReplayReport
from fdai.core.conversation_assurance.quality_observation_models import (
    QualificationDimensionContribution,
)
from fdai.core.conversation_assurance.quality_scorecard import (
    CHATOPS_QUALITY_CONTRACT_V1,
    QualityDimension,
)
from fdai.core.execution_authorization.models import (
    AuthorizationDecision,
    AuthorizationStatus,
)
from fdai.core.executor.safeguards import SafeguardReceipt, SafeguardRefusal
from fdai.core.irp.coordinator import MitigationProposal
from fdai.core.risk_gate.ceiling import AxisLevel
from fdai.core.risk_gate.evaluator import UnifiedRiskDecision
from fdai.core.runbook.models import RunbookResult
from fdai.shared.contracts.models import Action, Operation
from fdai.shared.providers.hil_channel import HilDecision, HilResponse


@dataclass(frozen=True, slots=True)
class SafeguardScenarioResult:
    case_id: str
    expected_eligible: bool
    actual: SafeguardReceipt | SafeguardRefusal
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class AuthorizationScenarioResult:
    case_id: str
    expected_status: AuthorizationStatus
    actual: AuthorizationDecision
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class RiskScenarioResult:
    case_id: str
    expected_level: AxisLevel
    actual: UnifiedRiskDecision
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class HilScenarioResult:
    case_id: str
    expected_decision: HilDecision
    actual: HilResponse
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class IdentitySeparationScenarioResult:
    case_id: str
    approver_identity_ref: str | None
    executor_identity_ref: str
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class AuditReplayScenarioResult:
    case_id: str
    expected_action_kinds: tuple[str, ...]
    actual: WhatIfReplayReport
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class RemediationScenarioResult:
    case_id: str
    expected_remediation_ref: str
    actual: MitigationProposal
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class RunbookScenarioResult:
    case_id: str
    expected_runbook_id: str
    actual: RunbookResult
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class WhatIfScenarioResult:
    case_id: str
    expected_rule_ids: tuple[str, ...]
    actual: WhatIfReplayReport
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class TypedActionScenarioResult:
    case_id: str
    expected_action_type: str
    expected_target_resource_ref: str
    expected_operation: Operation
    actual: Action
    evidence_digest: str


def observe_remediation_scenario(
    result: RemediationScenarioResult,
) -> QualificationDimensionContribution:
    """Measure item 21 from the existing typed mitigation proposal."""

    return _contribution(
        case_id=result.case_id,
        item_id=21,
        correct=result.actual.remediation_ref == result.expected_remediation_ref,
        reason_code="remediation_reference_match",
        evidence_digest=result.evidence_digest,
        observed_digest=_digest(
            {
                "remediation_ref": result.actual.remediation_ref,
                "target_resource_ref": result.actual.target_resource_ref,
                "citations": sorted(result.actual.citations),
            }
        ),
    )


def observe_runbook_scenario(
    result: RunbookScenarioResult,
) -> QualificationDimensionContribution:
    """Measure item 22 from the existing runbook execution result."""

    return _contribution(
        case_id=result.case_id,
        item_id=22,
        correct=result.actual.runbook_id == result.expected_runbook_id,
        reason_code="runbook_identifier_match",
        evidence_digest=result.evidence_digest,
        observed_digest=_digest(
            {
                "runbook_id": result.actual.runbook_id,
                "terminal_outcome": result.actual.terminal_outcome.value,
                "step_results": [
                    {
                        "step_id": step.step_id,
                        "action_type": step.action_type,
                        "outcome": step.outcome.value,
                    }
                    for step in result.actual.step_results
                ],
            }
        ),
    )


def observe_what_if_scenario(
    result: WhatIfScenarioResult,
) -> QualificationDimensionContribution:
    """Measure item 23 from the existing what-if replay matches."""

    actual_rule_ids = tuple(
        sorted(str(rule["rule_id"]) for rule in result.actual.matched_rules if "rule_id" in rule)
    )
    return _contribution(
        case_id=result.case_id,
        item_id=23,
        correct=actual_rule_ids == tuple(sorted(set(result.expected_rule_ids))),
        reason_code="what_if_rule_set_match",
        evidence_digest=result.evidence_digest,
        observed_digest=_digest(result.actual.as_json()),
    )


def observe_typed_action_scenario(
    result: TypedActionScenarioResult,
) -> QualificationDimensionContribution:
    """Measure item 24 from the existing typed Action contract."""

    correct = (
        result.actual.action_type == result.expected_action_type
        and result.actual.target_resource_ref == result.expected_target_resource_ref
        and result.actual.operation is result.expected_operation
    )
    return _contribution(
        case_id=result.case_id,
        item_id=24,
        correct=correct,
        reason_code="typed_action_match",
        evidence_digest=result.evidence_digest,
        observed_digest=_digest(result.actual.model_dump(mode="json")),
    )


def observe_safeguard_scenario(
    result: SafeguardScenarioResult,
) -> QualificationDimensionContribution:
    """Measure item 25 against a predeclared eligibility oracle."""

    observed_eligible = isinstance(result.actual, SafeguardReceipt)
    return _contribution(
        case_id=result.case_id,
        item_id=25,
        correct=observed_eligible is result.expected_eligible,
        reason_code="safeguard_eligibility_match",
        evidence_digest=result.evidence_digest,
        observed_digest=_safeguard_digest(result.actual),
    )


def observe_authorization_scenario(
    result: AuthorizationScenarioResult,
) -> QualificationDimensionContribution:
    """Measure item 26 against a predeclared authorization outcome."""

    return _contribution(
        case_id=result.case_id,
        item_id=26,
        correct=result.actual.status is result.expected_status,
        reason_code="authorization_status_match",
        evidence_digest=result.evidence_digest,
        observed_digest=_digest(result.actual.as_audit_dict()),
    )


def observe_risk_scenario(
    result: RiskScenarioResult,
) -> QualificationDimensionContribution:
    """Measure item 27 against a predeclared canonical risk level."""

    return _contribution(
        case_id=result.case_id,
        item_id=27,
        correct=result.actual.level is result.expected_level,
        reason_code="risk_level_match",
        evidence_digest=result.evidence_digest,
        observed_digest=_digest(result.actual.as_audit_dict()),
    )


def observe_hil_scenario(
    result: HilScenarioResult,
) -> QualificationDimensionContribution:
    """Measure item 28 against a predeclared terminal HIL outcome."""

    if result.expected_decision is HilDecision.PENDING:
        raise ValueError("expected HIL decision MUST be terminal")
    return _contribution(
        case_id=result.case_id,
        item_id=28,
        correct=result.actual.decision is result.expected_decision,
        reason_code="hil_terminal_decision_match",
        evidence_digest=result.evidence_digest,
        observed_digest=_digest(
            {
                "approval_id": result.actual.approval_id,
                "decision": result.actual.decision.value,
                "approver_id": result.actual.approver_id,
                "received_at": (
                    None
                    if result.actual.received_at is None
                    else result.actual.received_at.isoformat()
                ),
            }
        ),
    )


def observe_identity_separation_scenario(
    result: IdentitySeparationScenarioResult,
) -> QualificationDimensionContribution:
    """Measure item 29 from the existing approver and executor identities."""

    separated = (
        result.approver_identity_ref is not None
        and result.approver_identity_ref != result.executor_identity_ref
    )
    return _contribution(
        case_id=result.case_id,
        item_id=29,
        correct=separated,
        reason_code="approver_executor_identity_separation",
        evidence_digest=result.evidence_digest,
        observed_digest=_digest(
            {
                "approver_identity_digest": (
                    None
                    if result.approver_identity_ref is None
                    else _digest(result.approver_identity_ref)
                ),
                "executor_identity_digest": _digest(result.executor_identity_ref),
            }
        ),
    )


def observe_audit_replay_scenario(
    result: AuditReplayScenarioResult,
) -> QualificationDimensionContribution:
    """Measure item 30 from a reconstructed audit replay report."""

    expected = tuple(sorted(set(result.expected_action_kinds)))
    return _contribution(
        case_id=result.case_id,
        item_id=30,
        correct=result.actual.original_action_kinds == expected,
        reason_code="audit_replay_action_kinds_match",
        evidence_digest=result.evidence_digest,
        observed_digest=_digest(result.actual.as_json()),
    )


def _contribution(
    *,
    case_id: str,
    item_id: int,
    correct: bool,
    reason_code: str,
    evidence_digest: str,
    observed_digest: str,
) -> QualificationDimensionContribution:
    _require_digest(evidence_digest)
    item = CHATOPS_QUALITY_CONTRACT_V1.items[item_id - 1]
    return QualificationDimensionContribution(
        case_id=case_id,
        item_id=item_id,
        workstream=item.workstream,
        metric=item.metric,
        dimension=QualityDimension.FUNCTIONAL_CORRECTNESS,
        value=1.0 if correct else 0.0,
        reason_code=reason_code,
        evidence_ref_digests=(evidence_digest, observed_digest),
    )


def _safeguard_digest(result: SafeguardReceipt | SafeguardRefusal) -> str:
    if isinstance(result, SafeguardReceipt):
        payload: dict[str, object] = {
            "kind": "receipt",
            "execution_path": result.execution_path.value,
            "execution_fingerprint": result.execution_fingerprint,
            "dry_run_receipt": result.dry_run_receipt,
            "idempotency_key_digest": _digest(result.idempotency_key),
            "idempotency_lock_key_digest": _digest(result.idempotency_lock_key),
            "resource_lock_key_digest": _digest(result.resource_lock_key),
        }
    else:
        payload = {
            "kind": "refusal",
            "safeguard": result.safeguard,
            "reason_digest": _digest(result.reason),
        }
    return _digest(payload)


def _digest(value: object) -> str:
    serialized = (
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        if not isinstance(value, str)
        else value
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


def _require_digest(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("scenario evidence_digest MUST be a lowercase SHA-256 digest")

__all__ = [
    "AuditReplayScenarioResult",
    "AuthorizationScenarioResult",
    "HilScenarioResult",
    "IdentitySeparationScenarioResult",
    "RemediationScenarioResult",
    "RiskScenarioResult",
    "RunbookScenarioResult",
    "SafeguardScenarioResult",
    "TypedActionScenarioResult",
    "WhatIfScenarioResult",
    "observe_authorization_scenario",
    "observe_audit_replay_scenario",
    "observe_hil_scenario",
    "observe_identity_separation_scenario",
    "observe_remediation_scenario",
    "observe_risk_scenario",
    "observe_runbook_scenario",
    "observe_safeguard_scenario",
    "observe_typed_action_scenario",
    "observe_what_if_scenario",
]
