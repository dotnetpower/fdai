"""Resolve workflow gate references against authoritative evidence providers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.workflow.workflow_runtime import (
    WorkflowContextualGuardEvaluator,
    WorkflowGuardEvaluator,
)
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceAdmissionProvider,
    assess_decision_evidence_admission,
)

CHANGE_WINDOW_GATE_REF = "change-window.active"
WORKFLOW_GATE_EVIDENCE_PURPOSE = "workflow-gate"


class ChangeWindowGateEvidence(Protocol):
    async def is_active(self, *, target_ref: str, at: datetime) -> bool: ...


@dataclass(frozen=True, slots=True)
class ChangeWindowWorkflowGuardEvaluator:
    """Evaluate ChangeWindow gates and delegate unrelated gate references.

    A satisfied gate is a positive decision boundary, so an open gate additionally
    requires a current shared decision-critical evidence admission bound to that
    exact gate reference and Process lineage. An unbound provider or a mismatched
    admission fails closed and keeps the gate shut.
    """

    change_windows: ChangeWindowGateEvidence
    fallback: WorkflowGuardEvaluator | None = None
    decision_evidence_provider: DecisionEvidenceAdmissionProvider | None = None

    async def evaluate_context(
        self,
        *,
        rule_id: str,
        step_id: str,
        process_id: str,
        target_resource_id: str,
        at: datetime,
    ) -> bool:
        if rule_id == CHANGE_WINDOW_GATE_REF:
            satisfied = await self.change_windows.is_active(
                target_ref=target_resource_id,
                at=at,
            )
        elif self.fallback is None:
            return False
        else:
            satisfied = await self.fallback.evaluate(
                rule_id=rule_id,
                step_id=step_id,
                process_id=process_id,
            )
        if satisfied is not True:
            return False
        return not await self._admission_rejection_reasons(
            rule_id=rule_id,
            step_id=step_id,
            process_id=process_id,
            target_resource_id=target_resource_id,
            at=at,
        )

    async def _admission_rejection_reasons(
        self,
        *,
        rule_id: str,
        step_id: str,
        process_id: str,
        target_resource_id: str,
        at: datetime,
    ) -> tuple[str, ...]:
        """Return why the shared admission cannot open this satisfied gate."""

        return await workflow_gate_admission_rejection_reasons(
            self.decision_evidence_provider,
            rule_id=rule_id,
            step_id=step_id,
            process_id=process_id,
            target_resource_id=target_resource_id,
            at=at,
        )


@dataclass(frozen=True, slots=True)
class AdmittedWorkflowGuardEvaluator:
    """Require the shared admission for any positive workflow guard outcome.

    Wrap every deployed contextual guard evaluator with this adapter so no gate
    can open on a delegate's word alone. The wrapped evaluator may still block on
    its own terms. When it permits the step, the gate opens only for a current
    shared decision-critical evidence admission bound to that exact gate
    reference and Process lineage. An unbound provider or a mismatched admission
    fails closed and keeps the gate shut.
    """

    inner: WorkflowContextualGuardEvaluator | WorkflowGuardEvaluator
    decision_evidence_provider: DecisionEvidenceAdmissionProvider | None = None

    async def evaluate_context(
        self,
        *,
        rule_id: str,
        step_id: str,
        process_id: str,
        target_resource_id: str,
        at: datetime,
    ) -> bool:
        inner = self.inner
        if isinstance(inner, WorkflowContextualGuardEvaluator):
            satisfied = await inner.evaluate_context(
                rule_id=rule_id,
                step_id=step_id,
                process_id=process_id,
                target_resource_id=target_resource_id,
                at=at,
            )
        else:
            satisfied = await inner.evaluate(
                rule_id=rule_id,
                step_id=step_id,
                process_id=process_id,
            )
        if satisfied is not True:
            return False
        reasons = await workflow_gate_admission_rejection_reasons(
            self.decision_evidence_provider,
            rule_id=rule_id,
            step_id=step_id,
            process_id=process_id,
            target_resource_id=target_resource_id,
            at=at,
        )
        if reasons:
            return False
        return True


async def workflow_gate_admission_rejection_reasons(
    provider: DecisionEvidenceAdmissionProvider | None,
    *,
    rule_id: str,
    step_id: str,
    process_id: str,
    target_resource_id: str,
    at: datetime,
) -> tuple[str, ...]:
    """Return why the shared admission cannot open one satisfied workflow gate."""

    evidence_digest = workflow_gate_evidence_digest(
        rule_id=rule_id,
        step_id=step_id,
        process_id=process_id,
        target_resource_id=target_resource_id,
        at=at,
    )
    scope_digest = workflow_gate_scope_digest(
        step_id=step_id,
        process_id=process_id,
        target_resource_id=target_resource_id,
    )
    admission: DecisionEvidenceAdmission | None = None
    if provider is not None:
        admission = await provider.admit(
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=WORKFLOW_GATE_EVIDENCE_PURPOSE,
            source_revision=rule_id,
        )
    if admission is None:
        return ("decision_evidence_admission_missing",)
    return tuple(
        f"decision_evidence_{reason.value}"
        for reason in assess_decision_evidence_admission(
            admission,
            expected_evidence_digest=evidence_digest,
            expected_scope_digest=scope_digest,
            expected_purpose_id=WORKFLOW_GATE_EVIDENCE_PURPOSE,
            expected_source_revision=rule_id,
            evaluated_at=at,
        )
    )


def workflow_gate_evidence_digest(
    *,
    rule_id: str,
    step_id: str,
    process_id: str,
    target_resource_id: str,
    at: datetime,
) -> str:
    """Return the exact evaluated gate observation digest."""

    return content_digest(
        {
            "at": at.isoformat(),
            "process_id": process_id,
            "rule_id": rule_id,
            "step_id": step_id,
            "target_resource_id": target_resource_id,
        }
    )


def workflow_gate_scope_digest(
    *,
    step_id: str,
    process_id: str,
    target_resource_id: str,
) -> str:
    """Return the exact Process, step, and target scope of one gate decision."""

    return content_digest(
        {
            "process_id": process_id,
            "step_id": step_id,
            "target_resource_id": target_resource_id,
        }
    )


__all__ = [
    "CHANGE_WINDOW_GATE_REF",
    "WORKFLOW_GATE_EVIDENCE_PURPOSE",
    "AdmittedWorkflowGuardEvaluator",
    "ChangeWindowWorkflowGuardEvaluator",
    "workflow_gate_admission_rejection_reasons",
    "workflow_gate_evidence_digest",
    "workflow_gate_scope_digest",
]
