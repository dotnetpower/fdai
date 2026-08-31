"""Durable workflow outcome receipts and exact-match verification."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fdai_service_contracts.ontology_query import content_digest

from fdai.shared.contracts.models import Action, Mode, ResponseOutcome, ResponseOutcomeLabel
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceAdmissionProvider,
    assess_decision_evidence_admission,
)
from fdai.shared.providers.state_store import StateStore

from .workflow_runtime import WorkflowVerifiedOutcome

WORKFLOW_OUTCOME_EVIDENCE_PURPOSE = "workflow-outcome"
_SUCCESS_OUTCOMES = frozenset({"dispatched", "already_applied", "published", "already_existed"})
_UNKNOWN_OUTCOMES = frozenset({"publish_outcome_unknown"})
_KEY_PREFIX = "workflow:outcome:"


def _default_clock() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True, slots=True)
class StateStoreWorkflowOutcomeLedger:
    """Record and verify independently evidenced workflow action outcomes.

    Recording is a durable observation and needs no admission. Accepting a durable
    receipt as a positive workflow outcome additionally requires a current shared
    decision-critical evidence admission bound to that exact record and Process
    lineage. An unbound provider or a mismatched admission fails closed: `verify`
    returns `False` and `resolve` raises instead of returning a verified outcome.
    """

    store: StateStore
    decision_evidence_provider: DecisionEvidenceAdmissionProvider | None = None
    clock: Callable[[], datetime] = field(default=_default_clock)

    async def record(
        self,
        *,
        action: Action,
        execution_outcome: str,
        execution_receipt_ref: str | None,
        response_outcome: ResponseOutcome,
    ) -> str | None:
        lineage = action.workflow_action
        if lineage is None:
            return None
        if action.mode is not Mode.ENFORCE or response_outcome.execution_mode is not Mode.ENFORCE:
            return None
        if (
            response_outcome.action_id != action.action_id
            or response_outcome.event_id != action.event_id
            or response_outcome.execution_outcome != execution_outcome
        ):
            raise ValueError("response outcome does not match the workflow Action")
        outcome = _classify_outcome(
            execution_outcome=execution_outcome,
            response_outcome=response_outcome,
        )
        if outcome is None:
            return None
        evidence_status = "effect_verified" if outcome == "succeeded" else "terminal_failure"
        receipt_payload: dict[str, object] = {
            "process_id": lineage.process_id,
            "step_id": lineage.step_id,
            "proposal_ref": lineage.proposal_ref,
            "action_id": str(action.action_id),
            "outcome": outcome,
            "evidence_status": evidence_status,
            "execution_outcome": execution_outcome,
            "execution_receipt_ref": execution_receipt_ref,
            "response_outcome_id": str(response_outcome.outcome_id),
        }
        receipt_ref = f"workflow-outcome:{_digest(receipt_payload)}"
        record = {**receipt_payload, "receipt_ref": receipt_ref}
        key = _state_key(lineage.proposal_ref)
        created = await self.store.write_state_with_audit_if_absent(
            key,
            record,
            {
                "actor": "fdai.core.workflow.outcome_verification",
                "action_kind": "workflow.action_outcome.recorded",
                **record,
            },
        )
        if not created:
            existing = await self.store.read_state(key)
            if existing != record:
                raise RuntimeError("workflow proposal outcome conflicts with its durable receipt")
        return receipt_ref

    async def verify(
        self,
        *,
        process_id: str,
        step_id: str,
        proposal_ref: str,
        outcome: str,
        receipt_ref: str,
    ) -> bool:
        if outcome not in {"succeeded", "failed"}:
            return False
        record = await self.store.read_state(_state_key(proposal_ref))
        if record is None:
            return False
        expected = {
            "process_id": process_id,
            "step_id": step_id,
            "proposal_ref": proposal_ref,
            "outcome": outcome,
            "receipt_ref": receipt_ref,
        }
        matched = all(record.get(name) == value for name, value in expected.items()) and (
            record.get("evidence_status")
            == ("effect_verified" if outcome == "succeeded" else "terminal_failure")
        )
        if not matched:
            return False
        return not await self._admission_rejection_reasons(record)

    async def _admission_rejection_reasons(self, record: Mapping[str, object]) -> tuple[str, ...]:
        """Return why the shared admission cannot admit this durable receipt."""

        evidence_digest = workflow_outcome_evidence_digest(record)
        scope_digest = workflow_outcome_scope_digest(record)
        source_revision = _text(record, "receipt_ref")
        admission: DecisionEvidenceAdmission | None = None
        if self.decision_evidence_provider is not None:
            admission = await self.decision_evidence_provider.admit(
                evidence_digest=evidence_digest,
                scope_digest=scope_digest,
                purpose_id=WORKFLOW_OUTCOME_EVIDENCE_PURPOSE,
                source_revision=source_revision,
            )
        if admission is None:
            return ("decision_evidence_admission_missing",)
        return tuple(
            f"decision_evidence_{reason.value}"
            for reason in assess_decision_evidence_admission(
                admission,
                expected_evidence_digest=evidence_digest,
                expected_scope_digest=scope_digest,
                expected_purpose_id=WORKFLOW_OUTCOME_EVIDENCE_PURPOSE,
                expected_source_revision=source_revision,
                evaluated_at=self.clock(),
            )
        )

    async def resolve(
        self,
        *,
        process_id: str,
        step_id: str,
        proposal_ref: str,
    ) -> WorkflowVerifiedOutcome | None:
        record = await self.store.read_state(_state_key(proposal_ref))
        if record is None:
            return None
        outcome = record.get("outcome")
        receipt_ref = record.get("receipt_ref")
        if not isinstance(outcome, str) or not isinstance(receipt_ref, str):
            raise ValueError("durable workflow outcome receipt is malformed")
        accepted = await self.verify(
            process_id=process_id,
            step_id=step_id,
            proposal_ref=proposal_ref,
            outcome=outcome,
            receipt_ref=receipt_ref,
        )
        if not accepted:
            raise ValueError("durable workflow outcome receipt does not match Process lineage")
        return WorkflowVerifiedOutcome(outcome=outcome, receipt_ref=receipt_ref)


def workflow_outcome_evidence_digest(record: Mapping[str, object]) -> str:
    """Return the exact durable workflow outcome digest without admission fields."""

    return content_digest(
        {
            "action_id": _text(record, "action_id"),
            "evidence_status": _text(record, "evidence_status"),
            "execution_outcome": _text(record, "execution_outcome"),
            "execution_receipt_ref": record.get("execution_receipt_ref"),
            "outcome": _text(record, "outcome"),
            "process_id": _text(record, "process_id"),
            "proposal_ref": _text(record, "proposal_ref"),
            "receipt_ref": _text(record, "receipt_ref"),
            "response_outcome_id": _text(record, "response_outcome_id"),
            "step_id": _text(record, "step_id"),
        }
    )


def workflow_outcome_scope_digest(record: Mapping[str, object]) -> str:
    """Return the exact Process, step, and proposal lineage scope of one receipt."""

    return content_digest(
        {
            "process_id": _text(record, "process_id"),
            "proposal_ref": _text(record, "proposal_ref"),
            "step_id": _text(record, "step_id"),
        }
    )


def _text(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"durable workflow outcome receipt field '{key}' is malformed")
    return value


def _classify_outcome(*, execution_outcome: str, response_outcome: ResponseOutcome) -> str | None:
    if execution_outcome in _SUCCESS_OUTCOMES:
        if response_outcome.label is ResponseOutcomeLabel.VERIFIED:
            return "succeeded"
        return None
    if execution_outcome in _UNKNOWN_OUTCOMES:
        return None
    return "failed"


def _state_key(proposal_ref: str) -> str:
    return f"{_KEY_PREFIX}{hashlib.sha256(proposal_ref.encode()).hexdigest()}"


def _digest(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


__all__ = [
    "WORKFLOW_OUTCOME_EVIDENCE_PURPOSE",
    "StateStoreWorkflowOutcomeLedger",
    "workflow_outcome_evidence_digest",
    "workflow_outcome_scope_digest",
]
