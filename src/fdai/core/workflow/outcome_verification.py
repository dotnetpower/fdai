"""Durable workflow outcome receipts and exact-match verification."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from fdai.shared.contracts.models import Action, Mode, ResponseOutcome, ResponseOutcomeLabel
from fdai.shared.providers.state_store import StateStore

from .workflow_runtime import WorkflowVerifiedOutcome

_SUCCESS_OUTCOMES = frozenset({"dispatched", "already_applied", "published", "already_existed"})
_UNKNOWN_OUTCOMES = frozenset({"publish_outcome_unknown"})
_KEY_PREFIX = "workflow:outcome:"


@dataclass(frozen=True, slots=True)
class StateStoreWorkflowOutcomeLedger:
    """Record and verify independently evidenced workflow action outcomes."""

    store: StateStore

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
        return all(record.get(field) == value for field, value in expected.items()) and (
            record.get("evidence_status")
            == ("effect_verified" if outcome == "succeeded" else "terminal_failure")
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


__all__ = ["StateStoreWorkflowOutcomeLedger"]
