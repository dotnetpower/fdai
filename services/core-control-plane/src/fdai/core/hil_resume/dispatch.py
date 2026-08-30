"""Executor routing and race-safe resolution persistence for HIL resume."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.core.executor import (
    DirectApiExecutionPort,
    ExecutionResult,
    ExecutorOutcome,
    ShadowExecutor,
)
from fdai.core.executor.direct_api import DirectApiExecutionResult
from fdai.core.executor.tool_call import ToolCallExecutionResult, ToolCallShadowExecutor
from fdai.core.hil_resume.approval_records import park_key as _park_key
from fdai.core.ontology_platform.evidence_conflict import (
    EvidenceConflictCurrentReader,
    current_evidence_conflict_ceiling,
)
from fdai.core.operational_planning import PreDispatchKineticSafetyWriter
from fdai.shared.contracts.models import Action, ExecutionPath, OntologyActionType, Rule
from fdai.shared.providers.hil_channel import HilDecision
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger("fdai.core.hil_resume.coordinator")
_STATUS_PENDING = "pending"


class HilDispatchMixin:
    """Route approved actions and persist one terminal decision with CAS."""

    _action_types_by_name: Mapping[str, OntologyActionType]
    _direct_api_executor: DirectApiExecutionPort | None
    _evidence_conflict_reader: EvidenceConflictCurrentReader | None
    _executor: ShadowExecutor
    _pre_dispatch_kinetic_safety_writer: PreDispatchKineticSafetyWriter | None
    _state_store: StateStore
    _tool_executor: ToolCallShadowExecutor | None

    def _audit_entry(
        self,
        *,
        action_kind: str,
        idempotency_key: str,
        approval_id: str,
        correlation_id: str,
        detail: Mapping[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    async def _dispatch(
        self,
        *,
        action: Action,
        rule: Rule,
        correlation_id: str,
    ) -> ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult:
        action_type = self._action_types_by_name.get(action.action_type)
        if self._evidence_conflict_reader is not None and action_type is not None:
            try:
                _, disposition, conflicts = await current_evidence_conflict_ceiling(
                    self._evidence_conflict_reader,
                    action_type=action_type,
                    target_ref=action.target_resource_ref,
                    evaluated_at=datetime.now(tz=UTC),
                )
            except Exception:  # noqa: BLE001 - unreadable current conflict blocks HIL resume
                return ExecutionResult(
                    action_id=str(action.action_id),
                    outcome=ExecutorOutcome.REJECTED_INVARIANT,
                    mode=action.mode,
                    reason="evidence-conflict current state is unavailable",
                )
            if conflicts:
                return ExecutionResult(
                    action_id=str(action.action_id),
                    outcome=ExecutorOutcome.REJECTED_INVARIANT,
                    mode=action.mode,
                    reason=f"evidence conflict requires shadow-only: {disposition.value}",
                )
        writer = self._pre_dispatch_kinetic_safety_writer
        if writer is not None:
            try:
                await writer.persist(action=action, correlation_id=correlation_id)
            except Exception:  # noqa: BLE001 - kinetic ambiguity blocks every executor
                _LOGGER.warning(
                    "hil_pre_dispatch_kinetic_safety_failed",
                    extra={
                        "action_type": action.action_type,
                        "idempotency_key": action.idempotency_key,
                    },
                    exc_info=True,
                )
                return ExecutionResult(
                    action_id=str(action.action_id),
                    outcome=ExecutorOutcome.REJECTED_INVARIANT,
                    mode=action.mode,
                    reason="pre-dispatch kinetic safety evidence is invalid",
                )
        if self._action_types_by_name:
            if action_type is not None:
                if (
                    self._direct_api_executor is not None
                    and action_type.execution_path is ExecutionPath.DIRECT_API
                ):
                    return await self._direct_api_executor.execute(action=action)
                if (
                    self._tool_executor is not None
                    and action_type.execution_path is ExecutionPath.TOOL_CALL
                ):
                    return await self._tool_executor.execute(action=action)
        return await self._executor.execute(action=action, rule=rule)

    async def _mark_resolved(
        self,
        parked: Mapping[str, Any],
        *,
        decision: HilDecision,
        approver_oid: str,
        action_kind: str,
        detail: Mapping[str, Any],
    ) -> bool:
        immutable = (
            parked.get("request_fingerprint"),
            parked.get("action_hash"),
            parked.get("action"),
        )
        candidate = parked
        approval_id = str(parked["approval_id"])
        for _attempt in range(3):
            revision = candidate.get("revision", 0)
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
                raise ValueError("parked approval revision MUST be a non-negative integer")
            resolved_at = datetime.now(tz=UTC)
            updated = dict(candidate)
            updated["status"] = "resolved"
            updated["decision"] = decision.value
            updated["approver_oid"] = approver_oid
            updated["resolved_at"] = resolved_at.isoformat()
            updated["revision"] = revision + 1
            escalation = updated.get("escalation")
            if isinstance(escalation, Mapping):
                updated["escalation"] = {
                    **dict(escalation),
                    "status": "decided",
                    "terminal_decision": decision.value,
                }
            correlation_id = str(candidate.get("correlation_id") or approval_id)
            idem = str(candidate.get("idempotency_key") or approval_id)
            applied = await self._state_store.compare_and_set_state_with_audit(
                _park_key(approval_id),
                updated,
                expected_revision=revision,
                audit_entry=self._audit_entry(
                    action_kind=action_kind,
                    idempotency_key=f"{idem}:{action_kind}:{revision}",
                    approval_id=approval_id,
                    correlation_id=correlation_id,
                    detail=detail,
                ),
            )
            if applied:
                return True
            latest = await self._state_store.read_state(_park_key(approval_id))
            if latest is None or latest.get("status") != _STATUS_PENDING:
                return False
            if (
                latest.get("request_fingerprint"),
                latest.get("action_hash"),
                latest.get("action"),
            ) != immutable:
                return False
            candidate = latest
        return False


__all__ = ["HilDispatchMixin"]
