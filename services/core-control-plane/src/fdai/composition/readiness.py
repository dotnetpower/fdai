"""Application wiring for one operational-readiness review."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fdai.core.deploy_preflight import PreflightAnalyzer
from fdai.core.readiness import (
    HandoffApproval,
    OwnershipTransfer,
    ReadinessReport,
    RemediationProposal,
    SelfApprovalError,
    build_remediation_proposals,
    compose_readiness_report,
    evaluate_best_practices,
)
from fdai.shared.contracts.models import (
    BestPractice,
    Mode,
    RequirementKind,
    RequirementOutcome,
    RequirementStatus,
)
from fdai.shared.providers.feasibility_probe import PreflightTarget, ProbeFinding
from fdai.shared.providers.projection import Finding, Severity
from fdai.shared.providers.readiness import (
    ChecklistEvidenceProvider,
    PostureAssessmentProvider,
    ReadinessReportPublisher,
    RemediationProposalPublisher,
)
from fdai.shared.providers.state_store import StateStore


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _default_target(signal: OwnershipTransfer) -> PreflightTarget:
    return PreflightTarget(scope=signal.scope)


def _identity(signal: OwnershipTransfer) -> tuple[str, str]:
    material = "|".join(
        (
            signal.correlation_id or "",
            signal.scope,
            signal.submitter,
            signal.target_environment,
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    event_id = signal.correlation_id or f"ownership-transfer-{digest[:16]}"
    return event_id, f"orr:{digest}"


@dataclass(frozen=True, slots=True)
class OperationalReadinessService:
    """Run posture and preflight checks, audit the verdict, then publish it."""

    posture: PostureAssessmentProvider
    preflight: PreflightAnalyzer
    publisher: ReadinessReportPublisher
    state_store: StateStore
    mode: Mode = Mode.SHADOW
    blocking_min_severity: Severity = "high"
    clock: Callable[[], str] = _utc_now_iso
    target_factory: Callable[[OwnershipTransfer], PreflightTarget] = _default_target
    best_practices: Sequence[BestPractice] = ()
    checklist_evidence: ChecklistEvidenceProvider | None = None
    remediation_publisher: RemediationProposalPublisher | None = None
    remediation_levers: Mapping[str, str] = field(default_factory=dict)

    async def review(self, signal: OwnershipTransfer) -> ReadinessReport:
        """Run one fail-closed review bound to ``signal``."""

        generated_at = self.clock()
        event_id, idempotency_key = _identity(signal)
        try:
            checklist_task: asyncio.Task[Sequence[RequirementOutcome]] | None = None
            async with asyncio.TaskGroup() as group:
                posture_task = group.create_task(self.posture.findings_for_scope(signal.scope))
                preflight_task = group.create_task(
                    self.preflight.analyze(self.target_factory(signal))
                )
                if self.checklist_evidence is not None:
                    checklist_task = group.create_task(
                        self.checklist_evidence.outcomes_for_scope(signal.scope)
                    )
            if self.best_practices and checklist_task is None:
                raise RuntimeError("best-practice controls require a checklist evidence provider")
            posture_findings = tuple(posture_task.result())
            preflight_report = preflight_task.result()
            provided_outcomes = tuple(checklist_task.result()) if checklist_task is not None else ()
            outcomes = _merge_failure_outcomes(
                controls=self.best_practices,
                outcomes=provided_outcomes,
                posture_findings=posture_findings,
                preflight_findings=preflight_report.findings,
            )
            evaluated_at = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            checklist_results = evaluate_best_practices(
                tuple(self.best_practices),
                outcomes,
                evaluated_at=evaluated_at,
            )
            report = compose_readiness_report(
                signal=signal,
                posture_findings=posture_findings,
                preflight_findings=preflight_report.findings,
                mode=self.mode,
                generated_at=generated_at,
                blocking_min_severity=self.blocking_min_severity,
                checklist_results=checklist_results,
            )
        except Exception as exc:
            await self.state_store.append_audit_entry(
                self._audit_entry(
                    signal=signal,
                    event_id=event_id,
                    idempotency_key=idempotency_key,
                    timestamp=generated_at,
                    decision="abstain",
                    outcome="assessment_failed",
                    detail={"error_type": type(exc).__name__},
                )
            )
            raise

        await self.state_store.append_audit_entry(
            self._audit_entry(
                signal=signal,
                event_id=event_id,
                idempotency_key=idempotency_key,
                timestamp=generated_at,
                decision=report.verdict.value,
                outcome="reviewed",
                detail={
                    "blocks_handoff": report.blocks_handoff,
                    "finding_count": len(report.findings),
                },
            )
        )
        try:
            await self.publisher.publish_readiness_report(report.to_dict())
        except Exception as exc:
            await self.state_store.append_audit_entry(
                self._audit_entry(
                    signal=signal,
                    event_id=event_id,
                    idempotency_key=f"{idempotency_key}:delivery",
                    timestamp=self.clock(),
                    decision="abstain",
                    outcome="delivery_failed",
                    detail={"error_type": type(exc).__name__},
                )
            )
            raise
        return report

    async def propose_remediations(
        self,
        *,
        signal: OwnershipTransfer,
        report: ReadinessReport,
        approval: HandoffApproval,
    ) -> tuple[RemediationProposal, ...]:
        """Publish the grounded shadow remediations one review can cite.

        The service proposes only. It never calls an executor, never mutates a
        managed resource, and records the distinct approver identity in an
        append-only audit entry before and after delivery. Self-approval, a
        mismatched report, and a missing publisher all fail closed.
        """
        event_id, idempotency_key = _identity(signal)
        timestamp = self.clock()
        if (
            report.scope != signal.scope
            or report.submitter != signal.submitter
            or report.target_environment != signal.target_environment
        ):
            await self._audit_remediation(
                signal=signal,
                event_id=event_id,
                idempotency_key=f"{idempotency_key}:remediation-mismatch",
                timestamp=timestamp,
                decision="abstain",
                outcome="report_signal_mismatch",
                approver=approval.approver,
                detail={},
            )
            raise ValueError("readiness report does not belong to this ownership transfer")

        try:
            proposals = build_remediation_proposals(
                report=report,
                approval=approval,
                remediation_levers=self.remediation_levers,
            )
        except SelfApprovalError:
            await self._audit_remediation(
                signal=signal,
                event_id=event_id,
                idempotency_key=f"{idempotency_key}:remediation-self-approval",
                timestamp=timestamp,
                decision="deny",
                outcome="self_approval_blocked",
                approver=approval.approver,
                detail={},
            )
            raise

        if not proposals:
            await self._audit_remediation(
                signal=signal,
                event_id=event_id,
                idempotency_key=f"{idempotency_key}:remediation-abstain",
                timestamp=timestamp,
                decision="abstain",
                outcome="no_remediation_lever",
                approver=approval.approver,
                detail={"proposal_count": 0},
            )
            return ()

        if self.remediation_publisher is None:
            await self._audit_remediation(
                signal=signal,
                event_id=event_id,
                idempotency_key=f"{idempotency_key}:remediation-unconfigured",
                timestamp=timestamp,
                decision="abstain",
                outcome="remediation_publisher_unconfigured",
                approver=approval.approver,
                detail={"proposal_count": len(proposals)},
            )
            raise RuntimeError("readiness remediation requires a bound proposal publisher")

        action_types = sorted({proposal.action_type for proposal in proposals})
        await self._audit_remediation(
            signal=signal,
            event_id=event_id,
            idempotency_key=f"{idempotency_key}:remediation-proposed",
            timestamp=timestamp,
            decision="propose",
            outcome="remediation_proposed",
            approver=approval.approver,
            detail={"proposal_count": len(proposals), "action_types": action_types},
        )
        for index, proposal in enumerate(proposals):
            try:
                await self.remediation_publisher.publish_remediation_proposal(proposal.to_dict())
            except Exception as exc:
                await self._audit_remediation(
                    signal=signal,
                    event_id=event_id,
                    idempotency_key=f"{proposal.idempotency_key}:delivery-failed",
                    timestamp=self.clock(),
                    decision="abstain",
                    outcome="remediation_delivery_failed",
                    approver=approval.approver,
                    detail={
                        "error_type": type(exc).__name__,
                        "delivered_count": index,
                        "proposal_count": len(proposals),
                    },
                )
                raise
        await self._audit_remediation(
            signal=signal,
            event_id=event_id,
            idempotency_key=f"{idempotency_key}:remediation-delivered",
            timestamp=self.clock(),
            decision="propose",
            outcome="remediation_delivered",
            approver=approval.approver,
            detail={"proposal_count": len(proposals), "action_types": action_types},
        )
        return proposals

    async def _audit_remediation(
        self,
        *,
        signal: OwnershipTransfer,
        event_id: str,
        idempotency_key: str,
        timestamp: str,
        decision: str,
        outcome: str,
        approver: str,
        detail: dict[str, object],
    ) -> None:
        entry = self._audit_entry(
            signal=signal,
            event_id=event_id,
            idempotency_key=idempotency_key,
            timestamp=timestamp,
            decision=decision,
            outcome=outcome,
            detail=detail,
        )
        entry["kind"] = "operational_readiness.remediation"
        # Proposals stay shadow even when the ORR gate itself runs in enforce.
        entry["mode"] = Mode.SHADOW.value
        entry["approver_identity"] = approver
        await self.state_store.append_audit_entry(entry)

    def _audit_entry(
        self,
        *,
        signal: OwnershipTransfer,
        event_id: str,
        idempotency_key: str,
        timestamp: str,
        decision: str,
        outcome: str,
        detail: dict[str, object],
    ) -> dict[str, object]:
        return {
            "kind": "operational_readiness.review",
            "event_id": event_id,
            "correlation_id": signal.correlation_id,
            "tier": "t0",
            "decision": decision,
            "outcome": outcome,
            "idempotency_key": idempotency_key,
            "actor_identity": signal.submitter,
            "timestamp": timestamp,
            "mode": self.mode.value,
            "rollback_reference": None,
            "scope": signal.scope,
            "target_environment": signal.target_environment,
            **detail,
        }


def _merge_failure_outcomes(
    *,
    controls: Sequence[BestPractice],
    outcomes: Sequence[RequirementOutcome],
    posture_findings: Sequence[Finding],
    preflight_findings: Sequence[ProbeFinding],
) -> tuple[RequirementOutcome, ...]:
    merged: dict[tuple[RequirementKind, str], RequirementOutcome] = {}
    for outcome in outcomes:
        key = (outcome.kind, outcome.ref)
        if key in merged:
            raise ValueError(
                f"duplicate requirement outcome for {outcome.kind.value}:{outcome.ref}"
            )
        merged[key] = outcome

    required_rules = {
        requirement.ref
        for control in controls
        for requirement in control.requirements
        if requirement.kind is RequirementKind.RULE
    }
    for posture_finding in posture_findings:
        if posture_finding.rule_id in required_rules:
            merged[(RequirementKind.RULE, posture_finding.rule_id)] = RequirementOutcome(
                kind=RequirementKind.RULE,
                ref=posture_finding.rule_id,
                status=RequirementStatus.FAILED,
                evidence_refs=posture_finding.evidence_refs,
            )

    required_probes = {
        requirement.ref
        for control in controls
        for requirement in control.requirements
        if requirement.kind is RequirementKind.PROBE
    }
    for preflight_finding in preflight_findings:
        if preflight_finding.id in required_probes:
            merged[(RequirementKind.PROBE, preflight_finding.id)] = RequirementOutcome(
                kind=RequirementKind.PROBE,
                ref=preflight_finding.id,
                status=RequirementStatus.FAILED,
                evidence_refs=(preflight_finding.evidence.source,),
            )
    return tuple(merged.values())


__all__ = ["OperationalReadinessService"]
