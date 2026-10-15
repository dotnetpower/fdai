"""ORR remediation bridging: distinct approval, audit, and no execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from fdai.composition.readiness import OperationalReadinessService
from fdai.core.deploy_preflight import PreflightAnalyzer
from fdai.core.readiness import (
    HandoffApproval,
    HandoffVerdict,
    OwnershipTransfer,
    ReadinessReport,
    SelfApprovalError,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.projection import Finding, ResourceRef
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_RULE_ID = "managed-identity.role-assignment.no-wildcard-action"
_LEVERS = {_RULE_ID: "remediate.right-size-role"}


class _Posture:
    def __init__(self, findings: Sequence[Finding] = ()) -> None:
        self._findings = tuple(findings)

    async def findings_for_scope(self, scope: str) -> Sequence[Finding]:
        assert scope
        return self._findings


class _ReportPublisher:
    def __init__(self) -> None:
        self.reports: list[Mapping[str, Any]] = []

    async def publish_readiness_report(self, report: Mapping[str, Any]) -> None:
        self.reports.append(report)


class _ProposalPublisher:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.proposals: list[Mapping[str, Any]] = []
        self._error = error

    async def publish_remediation_proposal(self, proposal: Mapping[str, Any]) -> None:
        if self._error is not None:
            raise self._error
        self.proposals.append(proposal)


def _finding() -> Finding:
    return Finding(
        rule_id=_RULE_ID,
        resource=ResourceRef(resource_type="managed_identity", ref="id-workload"),
        severity="critical",
        reason="role grants a wildcard action",
    )


def _signal() -> OwnershipTransfer:
    return OwnershipTransfer(
        scope="rg-example",
        submitter="submitter@example.com",
        target_environment="prod",
        correlation_id="corr-orr-remediation",
    )


def _approval(approver: str = "approver@example.com") -> HandoffApproval:
    return HandoffApproval(approver=approver, decided_at="2026-08-16T00:05:00+00:00")


def _service(
    *,
    proposal_publisher: _ProposalPublisher | None = None,
    levers: Mapping[str, str] | None = None,
    findings: Sequence[Finding] = (),
    mode: Mode = Mode.ENFORCE,
) -> tuple[OperationalReadinessService, InMemoryStateStore, _ProposalPublisher | None]:
    store = InMemoryStateStore()
    service = OperationalReadinessService(
        posture=_Posture(findings),
        preflight=PreflightAnalyzer((), mode=mode, clock=lambda: "ignored"),
        publisher=_ReportPublisher(),
        state_store=store,
        mode=mode,
        clock=lambda: "2026-08-16T00:00:00+00:00",
        remediation_publisher=proposal_publisher,
        remediation_levers=dict(levers if levers is not None else _LEVERS),
    )
    return service, store, proposal_publisher


def _audits(store: InMemoryStateStore) -> list[Mapping[str, Any]]:
    return [record["entry"] for record in store.audit_entries]


def _remediation_audits(store: InMemoryStateStore) -> list[Mapping[str, Any]]:
    return [
        entry for entry in _audits(store) if entry["kind"] == "operational_readiness.remediation"
    ]


async def test_grounded_proposal_is_published_with_two_phase_audit() -> None:
    publisher = _ProposalPublisher()
    service, store, _ = _service(proposal_publisher=publisher, findings=(_finding(),))

    report = await service.review(_signal())
    proposals = await service.propose_remediations(
        signal=_signal(), report=report, approval=_approval()
    )

    assert report.verdict is HandoffVerdict.BLOCKED
    assert [proposal.action_type for proposal in proposals] == ["remediate.right-size-role"]
    assert publisher.proposals == [proposals[0].to_dict()]
    audits = _remediation_audits(store)
    assert [entry["outcome"] for entry in audits] == [
        "remediation_proposed",
        "remediation_delivered",
    ]
    assert {entry["approver_identity"] for entry in audits} == {"approver@example.com"}
    # The ORR gate runs in enforce, but its proposals stay shadow.
    assert {entry["mode"] for entry in audits} == {"shadow"}
    assert await store.verify_chain() is True


async def test_self_approval_is_denied_audited_and_publishes_nothing() -> None:
    publisher = _ProposalPublisher()
    service, store, _ = _service(proposal_publisher=publisher, findings=(_finding(),))
    report = await service.review(_signal())

    with pytest.raises(SelfApprovalError):
        await service.propose_remediations(
            signal=_signal(),
            report=report,
            approval=_approval("submitter@example.com"),
        )

    assert publisher.proposals == []
    audit = _remediation_audits(store)[0]
    assert audit["decision"] == "deny"
    assert audit["outcome"] == "self_approval_blocked"
    assert audit["approver_identity"] == "submitter@example.com"


async def test_ungrounded_review_abstains_instead_of_proposing() -> None:
    publisher = _ProposalPublisher()
    service, store, _ = _service(proposal_publisher=publisher, findings=(_finding(),), levers={})
    report = await service.review(_signal())

    proposals = await service.propose_remediations(
        signal=_signal(), report=report, approval=_approval()
    )

    assert proposals == ()
    assert publisher.proposals == []
    audit = _remediation_audits(store)[0]
    assert audit["decision"] == "abstain"
    assert audit["outcome"] == "no_remediation_lever"


async def test_missing_publisher_fails_closed_after_audit() -> None:
    service, store, _ = _service(proposal_publisher=None, findings=(_finding(),))
    report = await service.review(_signal())

    with pytest.raises(RuntimeError, match="bound proposal publisher"):
        await service.propose_remediations(signal=_signal(), report=report, approval=_approval())

    audit = _remediation_audits(store)[0]
    assert audit["outcome"] == "remediation_publisher_unconfigured"
    assert audit["decision"] == "abstain"


async def test_delivery_failure_is_audited_and_propagated() -> None:
    publisher = _ProposalPublisher(error=RuntimeError("bus unavailable"))
    service, store, _ = _service(proposal_publisher=publisher, findings=(_finding(),))
    report = await service.review(_signal())

    with pytest.raises(RuntimeError, match="bus unavailable"):
        await service.propose_remediations(signal=_signal(), report=report, approval=_approval())

    audits = _remediation_audits(store)
    assert [entry["outcome"] for entry in audits] == [
        "remediation_proposed",
        "remediation_delivery_failed",
    ]
    assert audits[-1]["error_type"] == "RuntimeError"
    assert audits[-1]["delivered_count"] == 0


async def test_report_from_another_transfer_is_refused() -> None:
    publisher = _ProposalPublisher()
    service, store, _ = _service(proposal_publisher=publisher, findings=(_finding(),))
    foreign = ReadinessReport(
        scope="rg-other",
        submitter="submitter@example.com",
        target_environment="prod",
        generated_at="2026-08-16T00:00:00+00:00",
        mode=Mode.SHADOW,
        verdict=HandoffVerdict.CLEAR,
        findings=(),
    )

    with pytest.raises(ValueError, match="does not belong to this ownership transfer"):
        await service.propose_remediations(signal=_signal(), report=foreign, approval=_approval())

    assert publisher.proposals == []
    assert _remediation_audits(store)[0]["outcome"] == "report_signal_mismatch"


async def test_repeated_proposal_pass_reuses_the_same_idempotency_key() -> None:
    publisher = _ProposalPublisher()
    service, _, _ = _service(proposal_publisher=publisher, findings=(_finding(),))
    report = await service.review(_signal())

    first = await service.propose_remediations(
        signal=_signal(), report=report, approval=_approval()
    )
    second = await service.propose_remediations(
        signal=_signal(), report=report, approval=_approval("other@example.com")
    )

    assert first[0].idempotency_key == second[0].idempotency_key
