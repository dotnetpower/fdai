"""HIL approval round-trip coordinator - park, push, resume.

Closes the gap between the risk gate returning ``hil`` and an approved
action actually running. The control loop never blocks on a human: it
uses the **park & return** model.

.. code-block:: text

    risk-gate -> hil
      -> HilResumeCoordinator.request_approval(action, rule, ...)
           1. park the full Action (+ context) in the StateStore under an
              opaque approval_id, status=pending
           2. push an A1 Adaptive Card via the HilChannel
           3. write a ``hil.requested`` audit entry
      -> ControlLoop.process(...) returns HIL (no blocking)

    ... later, a decision arrives (Teams/Slack callback or a poll) ...

    HilResumeCoordinator.resolve(approval_id, decision, approver_oid)
      - APPROVE -> restore the parked Action and re-dispatch to the executor
      - REJECT  -> record the reason, no execution
      - TIMEOUT -> no execution (fail-closed)
      - idempotent: a second resolve on a consumed park is a no-op

Safety invariants preserved
---------------------------

- **No auto-execute on HIL.** Nothing runs until :meth:`resolve` sees an
  ``APPROVE``; a missing / expired / consumed park never executes.
- **No self-approval.** ``approver_oid == submitter_oid`` is refused
  before any execution (the parked ``submitter_oid`` is the authority).
- **Idempotent.** The park's ``status`` flips to ``resolved`` on the
  first terminal decision; re-delivery of the same decision is a no-op,
  a conflicting decision is refused - re-execution can never happen.
- **Audit on every path.** request, approve+execute, reject, timeout,
  self-approval refusal, and unknown-park all append exactly one audit
  entry.

The coordinator lives in ``core/`` because it is a safety-critical
assembly point. It imports only Protocols from ``fdai.shared.providers``
and the core executor - never a concrete ChatOps / state adapter.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import uuid4

from fdai.core.executor import ExecutionResult, ShadowExecutor
from fdai.core.executor.direct_api import (
    DirectApiExecutionResult,
    DirectApiShadowExecutor,
)
from fdai.core.executor.tool_call import (
    ToolCallExecutionResult,
    ToolCallShadowExecutor,
)
from fdai.core.hil_resume.delegation import (
    DelegationMode,
    DelegationRefusal,
    evaluate_hil_delegation,
)
from fdai.core.oncall import OnCallResolution, OnCallResolver
from fdai.shared.contracts.models import (
    Action,
    ExecutionPath,
    Mode,
    OntologyActionType,
    Rule,
)
from fdai.shared.providers.hil_channel import (
    HilApprovalReceipt,
    HilApprovalRequest,
    HilChannel,
    HilChannelError,
    HilDecision,
)
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger(__name__)

_PARK_PREFIX = "hil_park:"
_STATUS_PENDING = "pending"
_STATUS_RESOLVED = "resolved"


def _park_key(approval_id: str) -> str:
    return f"{_PARK_PREFIX}{approval_id}"


def _on_call_detail(resolution: OnCallResolution | None) -> dict[str, Any] | None:
    """Serialize an on-call resolution for the park record + audit entry.

    ``None`` when no on-call resolver is configured (the coordinator routes by
    role exactly as before). Otherwise a flat, secret-free dict recording who
    was on shift - or why the resolver fell back to role-based routing.
    """
    if resolution is None:
        return None
    return {
        "rotation": resolution.rotation,
        "primary_oid": resolution.primary_oid,
        "secondary_oid": resolution.secondary_oid,
        "from_schedule": resolution.from_schedule,
        "fallback_reason": resolution.fallback_reason,
    }


class RequestOutcome(StrEnum):
    """Result of :meth:`HilResumeCoordinator.request_approval`."""

    PARKED = "parked"
    """Action parked and the approval card dispatched."""

    PARKED_DISPATCH_FAILED = "parked_dispatch_failed"
    """Action parked but the HilChannel push failed. The action stays
    pending (fail-toward-safety); a re-drive or a fallback channel can
    still deliver the card. Never auto-executes."""


class ResolveOutcome(StrEnum):
    """Terminal result of :meth:`HilResumeCoordinator.resolve`."""

    EXECUTED = "executed"
    """APPROVE -> the parked action was re-dispatched to the executor."""

    EXECUTE_FAILED = "execute_failed"
    """APPROVE accepted but the executor reported a failure. The park is
    still marked resolved so a retry does not double-apply; the audit
    entry records the failure."""

    REJECTED = "rejected"
    """REJECT -> the reason was recorded, no execution."""

    TIMED_OUT = "timed_out"
    """TIMEOUT -> fail-closed no-op."""

    ALREADY_RESOLVED = "already_resolved"
    """The park already reached a terminal state; idempotent no-op."""

    NOT_FOUND = "not_found"
    """No park for this approval_id (unknown / expired). Fail-safe no-op."""

    SELF_APPROVAL_REFUSED = "self_approval_refused"
    """approver_oid == submitter_oid; refused before any execution."""

    MISSING_CAPABILITY = "missing_capability"
    """The approver lacks the HIL-approval capability; refused before any
    execution (role-scoped queue, but still capability-gated)."""

    CONFLICTING_DECISION = "conflicting_decision"
    """A different terminal decision was already recorded; refused."""


@dataclass(frozen=True, slots=True)
class RequestApprovalResult:
    outcome: RequestOutcome
    approval_id: str
    receipt: HilApprovalReceipt | None = None


@dataclass(frozen=True, slots=True)
class ResolveResult:
    outcome: ResolveOutcome
    approval_id: str
    execution_result: (
        ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult | None
    ) = None
    reason: str | None = None
    delegated: bool = False
    """True when an authorized operator approved on the assignee's behalf."""
    assignee_oid: str | None = None
    """The operator the park was surfaced to, when recorded."""


class HilResumeCoordinator:
    """Parks HIL-routed actions and resumes them on an approval decision."""

    def __init__(
        self,
        *,
        state_store: StateStore,
        executor: ShadowExecutor,
        hil_channel: HilChannel | None,
        rules_by_id: Mapping[str, Rule],
        direct_api_executor: DirectApiShadowExecutor | None = None,
        tool_executor: ToolCallShadowExecutor | None = None,
        action_types_by_name: Mapping[str, OntologyActionType] | None = None,
        actor: str = "fdai.core.hil_resume",
        on_call_resolver: OnCallResolver | None = None,
        on_call_rotation: str | None = None,
        pending_index_writer: Callable[[StateStore, str], Awaitable[None]] | None = None,
    ) -> None:
        self._state_store = state_store
        self._executor = executor
        self._hil_channel = hil_channel
        self._rules_by_id = dict(rules_by_id)
        self._direct_api_executor = direct_api_executor
        self._tool_executor = tool_executor
        self._action_types_by_name = (
            dict(action_types_by_name) if action_types_by_name is not None else {}
        )
        self._actor = actor
        self._on_call_resolver = on_call_resolver
        self._on_call_rotation = on_call_rotation
        self._pending_index_writer = pending_index_writer

    async def _resolve_on_call(self) -> OnCallResolution | None:
        """Resolve the current on-call responder, or ``None`` when unconfigured.

        Fail-safe by construction: :class:`OnCallResolver` never raises, so a
        schedule-provider outage degrades to a role-based fallback recorded on
        the resolution - it never blocks parking a HIL request.
        """
        if self._on_call_resolver is None or self._on_call_rotation is None:
            return None
        return await self._on_call_resolver.resolve(
            rotation=self._on_call_rotation, at=datetime.now(tz=UTC)
        )

    # ------------------------------------------------------------------
    # request (park + push)
    # ------------------------------------------------------------------

    async def request_approval(
        self,
        *,
        action: Action,
        rule: Rule,
        submitter_oid: str,
        correlation_id: str,
        reasons: Sequence[str] = (),
        blast_radius_summary: str = "",
        ttl_seconds: int = 1800,
        approval_id: str | None = None,
        assignee_oid: str | None = None,
    ) -> RequestApprovalResult:
        """Park ``action`` and push an A1 approval card.

        The park is written BEFORE the push so a dispatch failure never
        loses the pending action - it stays recoverable and fail-closed
        (no execution until an explicit APPROVE).

        ``assignee_oid`` records the operator the item was surfaced to. When
        omitted, it defaults to the resolved on-call primary (if any). A blank
        assignee makes the item purely role-scoped: any authorized approver
        resolves it directly. A recorded assignee lets :meth:`resolve`
        distinguish a direct approval from a **delegated** one for the audit.
        """
        if not submitter_oid.strip():
            # The parked submitter is the no-self-approval authority. A
            # blank submitter would make the resolve-time self-approval
            # check unverifiable (submitter == approver could not be
            # proven), so refuse to park at all - fail closed.
            raise ValueError(
                "submitter_oid MUST be non-empty - it is the no-self-approval authority"
            )
        aid = approval_id or uuid4().hex
        on_call = await self._resolve_on_call()
        resolved_assignee = (assignee_oid or "").strip() or (
            on_call.primary_oid if on_call is not None else None
        )
        parked_at = datetime.now(tz=UTC)
        parked = {
            "status": _STATUS_PENDING,
            "approval_id": aid,
            "action": action.model_dump(mode="json"),
            "rule_id": rule.id,
            "rule": rule.model_dump(mode="json"),
            "action_type": action.action_type,
            "submitter_oid": submitter_oid,
            "assignee_oid": resolved_assignee,
            "correlation_id": correlation_id,
            "idempotency_key": action.idempotency_key,
            "parked_at": parked_at.isoformat(),
            "approval_context": {
                "reasons": list(reasons),
                "blast_radius_summary": blast_radius_summary,
                "ttl_seconds": ttl_seconds,
                "expires_at": (parked_at + timedelta(seconds=ttl_seconds)).isoformat(),
            },
            "on_call": _on_call_detail(on_call),
        }
        await self._state_store.write_state(_park_key(aid), parked)
        if self._pending_index_writer is not None:
            await self._pending_index_writer(self._state_store, aid)
        await self._audit(
            action_kind="hil.requested",
            idempotency_key=f"{action.idempotency_key}:hil_request",
            approval_id=aid,
            correlation_id=correlation_id,
            detail={
                "action_type": action.action_type,
                "rule_id": rule.id,
                "severity": rule.severity.value,
                "category": rule.category.value,
                "submitter_oid": submitter_oid,
                "assignee_oid": resolved_assignee,
                "on_call": _on_call_detail(on_call),
            },
        )

        request = HilApprovalRequest(
            approval_id=aid,
            correlation_id=correlation_id,
            action_id=str(action.action_id),
            action_type=action.action_type,
            rule_ids=tuple(action.citing_rules),
            target_resource_ref=action.target_resource_ref,
            blast_radius_summary=blast_radius_summary,
            reasons=tuple(reasons),
            ttl_seconds=ttl_seconds,
        )
        if self._hil_channel is None:
            await self._audit(
                action_kind="hil.request.dispatch_unavailable",
                idempotency_key=f"{action.idempotency_key}:hil_dispatch_unavailable",
                approval_id=aid,
                correlation_id=correlation_id,
                detail={"action_type": action.action_type},
            )
            return RequestApprovalResult(
                outcome=RequestOutcome.PARKED_DISPATCH_FAILED,
                approval_id=aid,
            )
        try:
            receipt = await self._hil_channel.send(request)
        except HilChannelError:
            _LOGGER.warning(
                "hil_request_dispatch_failed",
                extra={"approval_id": aid, "correlation_id": correlation_id},
                exc_info=True,
            )
            await self._audit(
                action_kind="hil.request.dispatch_failed",
                idempotency_key=f"{action.idempotency_key}:hil_dispatch_failed",
                approval_id=aid,
                correlation_id=correlation_id,
                detail={"action_type": action.action_type},
            )
            return RequestApprovalResult(
                outcome=RequestOutcome.PARKED_DISPATCH_FAILED,
                approval_id=aid,
            )
        return RequestApprovalResult(
            outcome=RequestOutcome.PARKED,
            approval_id=aid,
            receipt=receipt,
        )

    # ------------------------------------------------------------------
    # resolve (approve -> execute | reject | timeout)
    # ------------------------------------------------------------------

    async def resolve(
        self,
        *,
        approval_id: str,
        decision: HilDecision,
        approver_oid: str,
        reason: str = "",
        approver_can_approve_hil: bool = True,
    ) -> ResolveResult:
        """Apply a terminal decision to a parked action.

        Fail-safe: an unknown / already-resolved / self-approved park
        never executes. Only an ``APPROVE`` on a still-pending park
        re-dispatches the action to the executor.

        ``approver_can_approve_hil`` is the caller's RBAC verdict for
        ``Capability.APPROVE_RUNTIME_HIL`` (the read-API HIL callback fills it
        from the operator's roles). The delegation gate refuses an approver
        who lacks it, and - when the park carries a different ``assignee_oid``
        than the approver - records the approval as **delegated** so the audit
        shows both the actual approver and the original assignee.
        """
        parked = await self._state_store.read_state(_park_key(approval_id))
        if parked is None:
            _LOGGER.warning("hil_resolve_unknown_park", extra={"approval_id": approval_id})
            await self._audit(
                action_kind="hil.resolve.not_found",
                idempotency_key=f"{approval_id}:hil_resolve_not_found",
                approval_id=approval_id,
                correlation_id=approval_id,
                detail={"decision": decision.value},
            )
            return ResolveResult(outcome=ResolveOutcome.NOT_FOUND, approval_id=approval_id)

        correlation_id = str(parked.get("correlation_id") or approval_id)
        idem = str(parked.get("idempotency_key") or approval_id)
        assignee_oid = str(parked.get("assignee_oid") or "").strip() or None

        if parked.get("status") == _STATUS_RESOLVED:
            prior = str(parked.get("decision") or "")
            if prior and prior != decision.value:
                await self._audit(
                    action_kind="hil.resolve.conflict",
                    idempotency_key=f"{idem}:hil_resolve_conflict",
                    approval_id=approval_id,
                    correlation_id=correlation_id,
                    detail={"prior_decision": prior, "attempted": decision.value},
                )
                return ResolveResult(
                    outcome=ResolveOutcome.CONFLICTING_DECISION,
                    approval_id=approval_id,
                    reason=f"already resolved as {prior}",
                )
            return ResolveResult(outcome=ResolveOutcome.ALREADY_RESOLVED, approval_id=approval_id)

        submitter_oid = str(parked.get("submitter_oid") or "").strip()
        delegation = None
        if decision is HilDecision.APPROVE:
            # Delegation gate: no self-approval, a verifiable+distinct approver,
            # and the HIL-approval capability. Fail closed on any refusal. A
            # single pure function shared with the read-API callback so the
            # rule never drifts between entry points.
            delegation = evaluate_hil_delegation(
                approver_oid=approver_oid,
                submitter_oid=submitter_oid,
                approver_can_approve_hil=approver_can_approve_hil,
                assignee_oid=assignee_oid,
            )
            if not delegation.allowed:
                if delegation.refusal is DelegationRefusal.MISSING_CAPABILITY:
                    await self._audit(
                        action_kind="hil.resolve.capability_refused",
                        idempotency_key=f"{idem}:hil_capability_refused",
                        approval_id=approval_id,
                        correlation_id=correlation_id,
                        detail={
                            "approver_oid": approver_oid,
                            "assignee_oid": assignee_oid,
                            "reason": DelegationRefusal.MISSING_CAPABILITY.value,
                        },
                    )
                    return ResolveResult(
                        outcome=ResolveOutcome.MISSING_CAPABILITY,
                        approval_id=approval_id,
                        assignee_oid=assignee_oid,
                    )
                await self._audit(
                    action_kind="hil.resolve.self_approval_refused",
                    idempotency_key=f"{idem}:hil_self_approval",
                    approval_id=approval_id,
                    correlation_id=correlation_id,
                    detail={
                        "approver_oid": approver_oid,
                        "reason": (
                            delegation.refusal.value
                            if delegation.refusal is not None
                            else "self_approval"
                        ),
                    },
                )
                return ResolveResult(
                    outcome=ResolveOutcome.SELF_APPROVAL_REFUSED, approval_id=approval_id
                )

        if decision is HilDecision.REJECT:
            await self._mark_resolved(parked, decision=decision, approver_oid=approver_oid)
            await self._audit(
                action_kind="hil.rejected",
                idempotency_key=f"{idem}:hil_rejected",
                approval_id=approval_id,
                correlation_id=correlation_id,
                detail={"approver_oid": approver_oid, "reason": reason},
            )
            return ResolveResult(
                outcome=ResolveOutcome.REJECTED, approval_id=approval_id, reason=reason
            )

        if decision is HilDecision.TIMEOUT:
            await self._mark_resolved(parked, decision=decision, approver_oid=approver_oid)
            await self._audit(
                action_kind="hil.timeout",
                idempotency_key=f"{idem}:hil_timeout",
                approval_id=approval_id,
                correlation_id=correlation_id,
                detail={},
            )
            return ResolveResult(outcome=ResolveOutcome.TIMED_OUT, approval_id=approval_id)

        # decision is APPROVE and the delegation gate allowed it -> re-dispatch.
        is_delegated = delegation is not None and delegation.is_delegated
        action = Action.model_validate(parked["action"])
        rule = self._rules_by_id.get(str(parked.get("rule_id") or ""))
        if rule is None and isinstance(parked.get("rule"), dict):
            rule = Rule.model_validate(parked["rule"])
        # Mark resolved BEFORE executing so a concurrent duplicate decision
        # cannot double-apply; the executor is itself idempotent by
        # idempotency_key, this is defense in depth.
        await self._mark_resolved(parked, decision=decision, approver_oid=approver_oid)
        if rule is None:
            _LOGGER.error(
                "hil_resolve_rule_missing",
                extra={"approval_id": approval_id, "rule_id": parked.get("rule_id")},
            )
            await self._audit(
                action_kind="hil.approved.execute_failed",
                idempotency_key=f"{idem}:hil_execute_failed",
                approval_id=approval_id,
                correlation_id=correlation_id,
                detail={"reason": "rule_not_in_catalog"},
            )
            return ResolveResult(
                outcome=ResolveOutcome.EXECUTE_FAILED,
                approval_id=approval_id,
                reason="rule_not_in_catalog",
                delegated=is_delegated,
                assignee_oid=assignee_oid,
            )

        result = await self._dispatch(action=action, rule=rule)
        succeeded = _is_success(result)
        delegation_mode = (
            delegation.mode.value
            if delegation is not None and delegation.mode is not None
            else DelegationMode.ROLE_SCOPED.value
        )
        await self._audit(
            action_kind="hil.approved.executed" if succeeded else "hil.approved.execute_failed",
            idempotency_key=f"{idem}:hil_executed",
            approval_id=approval_id,
            correlation_id=correlation_id,
            detail={
                "approver_oid": approver_oid,
                "assignee_oid": assignee_oid,
                "delegated": is_delegated,
                "delegation_mode": delegation_mode,
                "action_type": action.action_type,
                "mode": Mode.SHADOW.value,
            },
        )
        return ResolveResult(
            outcome=ResolveOutcome.EXECUTED if succeeded else ResolveOutcome.EXECUTE_FAILED,
            approval_id=approval_id,
            execution_result=result,
            delegated=is_delegated,
            assignee_oid=assignee_oid,
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    async def _dispatch(
        self, *, action: Action, rule: Rule
    ) -> ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult:
        if self._action_types_by_name:
            action_type = self._action_types_by_name.get(action.action_type)
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
    ) -> None:
        updated = dict(parked)
        updated["status"] = _STATUS_RESOLVED
        updated["decision"] = decision.value
        updated["approver_oid"] = approver_oid
        updated["resolved_at"] = datetime.now(tz=UTC).isoformat()
        await self._state_store.write_state(_park_key(str(parked["approval_id"])), updated)

    async def _audit(
        self,
        *,
        action_kind: str,
        idempotency_key: str,
        approval_id: str,
        correlation_id: str,
        detail: Mapping[str, Any],
    ) -> None:
        await self._state_store.append_audit_entry(
            {
                "actor": self._actor,
                "action_kind": action_kind,
                "mode": Mode.SHADOW.value,
                "idempotency_key": idempotency_key,
                "approval_id": approval_id,
                "correlation_id": correlation_id,
                "recorded_at": datetime.now(tz=UTC).isoformat(),
                **dict(detail),
            }
        )


def _is_success(
    result: ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult,
) -> bool:
    """Success check aligned with the control loop's ``_is_execution_success``."""
    from fdai.core.executor import ExecutorOutcome
    from fdai.core.executor.direct_api import DirectApiExecutionOutcome
    from fdai.core.executor.tool_call import ToolCallExecutionOutcome

    outcome = getattr(result, "outcome", None)
    return outcome in (
        ExecutorOutcome.PUBLISHED,
        ExecutorOutcome.ALREADY_EXISTED,
        DirectApiExecutionOutcome.DISPATCHED,
        DirectApiExecutionOutcome.ALREADY_APPLIED,
        ToolCallExecutionOutcome.DISPATCHED,
        ToolCallExecutionOutcome.ALREADY_APPLIED,
    )


__all__ = [
    "HilResumeCoordinator",
    "RequestApprovalResult",
    "RequestOutcome",
    "ResolveOutcome",
    "ResolveResult",
]
