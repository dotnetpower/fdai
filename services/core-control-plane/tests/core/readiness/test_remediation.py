"""Grounded, shadow-only remediation proposals from an ORR review."""

from __future__ import annotations

import pytest
from fdai.core.readiness import (
    HandoffApproval,
    HandoffVerdict,
    ReadinessFinding,
    ReadinessReport,
    RemediationProposal,
    SelfApprovalError,
    build_remediation_proposals,
    remediation_idempotency_key,
)
from fdai.shared.contracts.models import Mode

_LEVERS = {
    "managed-identity.role-assignment.no-wildcard-action": "remediate.right-size-role",
    "BP-RBAC-1": "remediate.right-size-role",
}


def _finding(
    *,
    evidence: str = "managed-identity.role-assignment.no-wildcard-action",
    resource: str = "id-workload",
    severity: str = "critical",
    blocking: bool = True,
    control_id: str | None = None,
    dimension: str | None = "identity_rbac",
) -> ReadinessFinding:
    return ReadinessFinding(
        evidence=evidence,
        severity=severity,
        resource=resource,
        blocking=blocking,
        resolution=None,
        source="assurance_twin",
        dimension=dimension,
        control_id=control_id,
    )


def _report(
    *findings: ReadinessFinding, submitter: str = "submitter@example.com"
) -> ReadinessReport:
    return ReadinessReport(
        scope="rg-example",
        submitter=submitter,
        target_environment="prod",
        generated_at="2026-08-16T00:00:00+00:00",
        mode=Mode.SHADOW,
        verdict=HandoffVerdict.BLOCKED if findings else HandoffVerdict.CLEAR,
        findings=tuple(findings),
    )


def _approval(approver: str = "approver@example.com") -> HandoffApproval:
    return HandoffApproval(approver=approver, decided_at="2026-08-16T00:05:00+00:00")


def test_grounded_finding_yields_one_shadow_proposal() -> None:
    proposals = build_remediation_proposals(
        report=_report(_finding()),
        approval=_approval(),
        remediation_levers=_LEVERS,
    )

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.action_type == "remediate.right-size-role"
    assert proposal.mode is Mode.SHADOW
    assert proposal.submitter == "submitter@example.com"
    assert proposal.approver == "approver@example.com"
    assert proposal.evidence == "managed-identity.role-assignment.no-wildcard-action"
    assert proposal.resource_ref == "id-workload"
    assert proposal.blocking is True


def test_unmapped_finding_produces_no_invented_lever() -> None:
    proposals = build_remediation_proposals(
        report=_report(_finding(evidence="reliability.no-backup")),
        approval=_approval(),
        remediation_levers=_LEVERS,
    )

    assert proposals == ()


def test_control_id_citation_resolves_the_checklist_lever() -> None:
    finding = _finding(evidence="BP-RBAC-1.control", control_id="BP-RBAC-1")

    proposals = build_remediation_proposals(
        report=_report(finding),
        approval=_approval(),
        remediation_levers=_LEVERS,
    )

    assert [proposal.control_id for proposal in proposals] == ["BP-RBAC-1"]


def test_self_approval_is_blocked_before_any_proposal_is_built() -> None:
    with pytest.raises(SelfApprovalError):
        build_remediation_proposals(
            report=_report(_finding()),
            approval=_approval("Submitter@Example.com "),
            remediation_levers=_LEVERS,
        )


def test_identical_findings_collapse_to_one_idempotent_proposal() -> None:
    proposals = build_remediation_proposals(
        report=_report(_finding(), _finding()),
        approval=_approval(),
        remediation_levers=_LEVERS,
    )

    assert len(proposals) == 1
    assert proposals[0].idempotency_key == remediation_idempotency_key(
        scope="rg-example",
        target_environment="prod",
        evidence="managed-identity.role-assignment.no-wildcard-action",
        resource_ref="id-workload",
        action_type="remediate.right-size-role",
    )


def test_distinct_resources_keep_distinct_proposal_identities() -> None:
    proposals = build_remediation_proposals(
        report=_report(_finding(), _finding(resource="id-other")),
        approval=_approval(),
        remediation_levers=_LEVERS,
    )

    keys = {proposal.idempotency_key for proposal in proposals}
    assert len(keys) == 2


def test_non_blocking_finding_keeps_its_truthful_gate_flag() -> None:
    proposals = build_remediation_proposals(
        report=_report(_finding(severity="medium", blocking=False)),
        approval=_approval(),
        remediation_levers=_LEVERS,
    )

    assert [proposal.blocking for proposal in proposals] == [False]


def test_blank_lever_is_rejected_instead_of_proposing_an_empty_action() -> None:
    with pytest.raises(ValueError, match="non-empty ActionType"):
        build_remediation_proposals(
            report=_report(_finding()),
            approval=_approval(),
            remediation_levers={
                "managed-identity.role-assignment.no-wildcard-action": "   ",
            },
        )


def test_proposal_cannot_be_constructed_in_enforce_mode() -> None:
    with pytest.raises(ValueError, match="MUST remain shadow"):
        RemediationProposal(
            action_type="remediate.right-size-role",
            resource_ref="id-workload",
            scope="rg-example",
            target_environment="prod",
            submitter="submitter@example.com",
            approver="approver@example.com",
            approved_at="2026-08-16T00:05:00+00:00",
            evidence="managed-identity.role-assignment.no-wildcard-action",
            severity="critical",
            blocking=True,
            idempotency_key="orr-remediation:abc",
            mode=Mode.ENFORCE,
        )


def test_serialized_proposal_carries_no_executor_identity() -> None:
    proposal = build_remediation_proposals(
        report=_report(_finding()),
        approval=_approval(),
        remediation_levers=_LEVERS,
    )[0]

    payload = proposal.to_dict()
    assert payload["mode"] == "shadow"
    assert payload["kind"] == "operational_readiness.remediation_proposal"
    forbidden = ("executor", "credential", "token", "secret", "client_id", "principal_id")
    assert not [key for key in payload if any(part in key for part in forbidden)]


@pytest.mark.parametrize("approver", ["", "   "])
def test_blank_approver_is_rejected(approver: str) -> None:
    with pytest.raises(ValueError, match="approver MUST be non-empty"):
        HandoffApproval(approver=approver, decided_at="2026-08-16T00:05:00+00:00")


def test_blank_decision_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="decided_at MUST be non-empty"):
        HandoffApproval(approver="approver@example.com", decided_at=" ")
