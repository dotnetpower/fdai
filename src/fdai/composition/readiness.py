"""Application wiring for one operational-readiness review."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.core.deploy_preflight import PreflightAnalyzer
from fdai.core.readiness import (
    OwnershipTransfer,
    ReadinessReport,
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
