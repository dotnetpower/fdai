"""Observed handover health and explicit incomplete scope, without provider or execution calls."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fdai_service_contracts.handover_knowledge import HandoverKnowledgeDecision
from fdai_service_contracts.handover_readiness import (
    HANDOVER_READINESS_KEY,
    HandoverReadinessReport,
)

from fdai.core.human_assignment.model import AssignmentCase, AssignmentState
from fdai.shared.providers.state_store import StateStore

SOURCE_GAPS: tuple[str, ...] = ()
EXTERNAL_BLOCKERS = (
    "current_deployed_identity_and_duty_coverage",
    "github_app_signed_merge_and_restart_drill",
    "current_target_bound_executor_authorization",
    "live_replacement_identity_and_role_readback",
    "nonproduction_membership_rollback_drills",
    "selected_teams_notification_evidence",
    "document_acl_deletion_performance_cohort",
    "exact_plan_human_approved_deployment",
    "independent_promotion_cohorts",
)


@dataclass(frozen=True, slots=True)
class HandoverReadinessPublisher:
    """Sample existing durable records and atomically audit the report; never enact recovery."""

    store: StateStore
    enabled: bool = True
    sample_limit: int = 100
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def publish(self) -> HandoverReadinessReport:
        """Expose partial samples and missing operational proofs, never a green readiness flag."""
        if type(self.sample_limit) is not int or not 1 <= self.sample_limit <= 1000:
            raise ValueError("handover readiness sample limit MUST be in [1, 1000]")
        now = self.clock()
        if now.utcoffset() is None:
            raise ValueError("handover readiness clock MUST include a timezone")
        cases, case_total = await self.store.read_state_page(
            "human_assignment:case:", limit=self.sample_limit
        )
        knowledge, knowledge_total = await self.store.read_state_page(
            "human_assignment:knowledge:Mimir:", limit=self.sample_limit
        )
        states: Counter[str] = Counter()
        dispositions: Counter[str] = Counter()
        case_invalid = knowledge_invalid = 0
        intervals = []
        overdue = False
        for raw in cases:
            try:
                case = AssignmentCase.from_dict(dict(raw))
                if any(receipt.received_at > now for receipt in case.effect_receipts):
                    raise ValueError("assignment observation contains future evidence")
            except (KeyError, TypeError, ValueError):
                case_invalid += 1
                continue
            states[case.state.value] += 1
            if len(case.effect_receipts) == 2:
                times = [receipt.received_at for receipt in case.effect_receipts]
                intervals.append(abs((max(times) - min(times)).total_seconds()))
            if case.state in {
                AssignmentState.IAM_APPLYING,
                AssignmentState.IAM_REVOKED,
                AssignmentState.OWNERSHIP_MERGED,
            }:
                if case.effect_receipts:
                    prerequisite_at = max(receipt.received_at for receipt in case.effect_receipts)
                    overdue |= now - prerequisite_at > timedelta(hours=1)
        for raw in knowledge:
            try:
                decision = HandoverKnowledgeDecision.model_validate(raw.get("decision"))
            except (TypeError, ValueError):
                knowledge_invalid += 1
            else:
                try:
                    decision.notice.require_current(now)
                except ValueError:
                    dispositions["stale"] += 1
                else:
                    dispositions[decision.disposition] += 1
        partial = len(cases) < case_total or len(knowledge) < knowledge_total
        alerts = []
        if case_invalid or knowledge_invalid:
            alerts.append("invalid_lifecycle_evidence")
        if partial:
            alerts.append("partial_lifecycle_scan")
        if overdue:
            alerts.append("convergence_overdue")
        if states["degraded"]:
            alerts.append("assignment_recovery_required")
        if any(dispositions[kind] for kind in ("held", "conflict", "withdrawn", "stale")):
            alerts.append("knowledge_review_required")
        if not self.enabled:
            alerts.append("human_access_disabled")
        for _attempt in range(4):
            current = await self.store.read_state(HANDOVER_READINESS_KEY)
            previous = (
                HandoverReadinessReport.model_validate(current) if current is not None else None
            )
            if previous is not None and previous.observed_at > now:
                raise ValueError("handover readiness clock moved backwards")
            revision = 0 if previous is None else previous.revision
            report = HandoverReadinessReport(
                revision=revision + 1,
                observed_at=now,
                expires_at=now + timedelta(minutes=10),
                enabled=self.enabled,
                sample_limit=self.sample_limit,
                cases_observed=len(cases),
                cases_total=case_total,
                cases_invalid=case_invalid,
                cases_by_state=dict(states),
                knowledge_observed=len(knowledge),
                knowledge_total=knowledge_total,
                knowledge_invalid=knowledge_invalid,
                knowledge_by_disposition=dict(dispositions),
                partial=partial,
                convergence_samples=len(intervals),
                mean_effect_interval_seconds=sum(intervals) / len(intervals) if intervals else None,
                alerts=tuple(alerts),
                source_gaps=SOURCE_GAPS,
                external_blockers=EXTERNAL_BLOCKERS,
            )
            audit = {
                "actor": "handover-readiness-observer",
                "action_kind": "handover.readiness.observed",
                "recorded_at": now.isoformat(),
                "revision": report.revision,
                "mode": "shadow",
                "partial": partial,
                "alerts": alerts,
                "execution_authority": False,
            }
            if current is None:
                applied = await self.store.write_state_with_audit_if_absent(
                    HANDOVER_READINESS_KEY, report.model_dump(mode="json"), audit
                )
            else:
                applied = await self.store.compare_and_set_state_with_audit(
                    HANDOVER_READINESS_KEY,
                    report.model_dump(mode="json"),
                    expected_revision=revision,
                    audit_entry=audit,
                )
            if applied:
                return report
        raise RuntimeError("handover readiness report changed concurrently")


__all__ = ["EXTERNAL_BLOCKERS", "SOURCE_GAPS", "HandoverReadinessPublisher"]
