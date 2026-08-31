"""Transport-neutral HIL callback decision service with two-phase audit.

Every human approval callback - the signed internal Slack/relay callback and
the Microsoft Teams Bot activity receiver - resolves through this one service.
The service owns context binding, expiry, current server-side authority,
self-approval refusal, workflow role checks, durable recording, and outbox
delivery. A transport contributes only *normalized* fields; it never
contributes authority.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from fdai_operator_service.families.iam.contracts import (
    HilApprovalDecision,
    HilDecisionCommand,
    HilDecisionOutbox,
    HilDecisionOutboxRequest,
    HilDecisionReceipt,
    HilDecisionRegistry,
)
from fdai_operator_service.families.iam.errors import IamFamilyError
from fdai_operator_service.families.iam.hil_callback_audit import (
    HilCallbackAuditPhase,
    HilCallbackAuditRecord,
    HilCallbackAuditWriter,
    HilCallbackOutcome,
    actor_identity_reference,
)
from fdai_operator_service.families.iam.hil_callback_authority import (
    HilCallbackActor,
    HilCallbackAuthority,
    HilCallbackAuthorityError,
    HilCallbackChannel,
    meets_role,
)
from fdai_operator_service.families.iam.hil_callback_context import (
    HilCallbackContextReader,
)
from fdai_operator_service.families.iam.http import error_response, family_error
from starlette.responses import JSONResponse, Response


@dataclass(frozen=True, slots=True)
class HilCallbackAttempt:
    """Audit-safe routing hints known before any field is trusted."""

    callback_id: str
    approval_id: str
    channel_hint: str = "unknown"
    actor_hint: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedHilDecision:
    """Server-normalized callback fields awaiting authority resolution.

    ``provider_actor_id`` and ``audience`` MUST be derived by the transport
    from an authenticated envelope, never copied from operator-supplied card
    or body content that the transport did not itself authenticate.
    """

    decision: HilApprovalDecision
    justification: str
    channel: HilCallbackChannel
    provider_actor_id: str
    audience: str
    correlation_id: str
    idempotency_key: str
    action_hash: str
    decided_at: datetime
    authorization: str | None


@dataclass(frozen=True, slots=True)
class _ApprovalContext:
    correlation_id: str
    idempotency_key: str
    action_hash: str
    expires_at: datetime | None
    submitter_oid: str
    metadata: Mapping[str, str]
    receipt: HilDecisionReceipt | None


class HilCallbackSession:
    """One audited callback attempt bound to its prepared audit phase."""

    __slots__ = ("_audit", "_attempt", "_clock", "_correlation_id", "_prepared_basis", "context")

    def __init__(
        self,
        *,
        audit: HilCallbackAuditWriter,
        attempt: HilCallbackAttempt,
        clock: Callable[[], datetime],
        correlation_id: str,
        prepared_basis: str,
        context: _ApprovalContext | None,
    ) -> None:
        self._audit = audit
        self._attempt = attempt
        self._clock = clock
        self._correlation_id = correlation_id
        self._prepared_basis = prepared_basis
        self.context = context

    async def finish(
        self,
        response: Response,
        *,
        outcome: HilCallbackOutcome,
        actor: HilCallbackActor | None = None,
        authority_basis: str | None = None,
    ) -> Response:
        """Write the terminal audit phase before returning any response."""
        try:
            await self._audit.append_callback_audit(
                HilCallbackAuditRecord(
                    callback_id=self._attempt.callback_id,
                    phase=HilCallbackAuditPhase.COMPLETED,
                    correlation_id=self._correlation_id,
                    actor_identity_ref=(
                        actor.identity_ref
                        if actor
                        else actor_identity_reference(self._attempt.actor_hint)
                    ),
                    authority_basis=(
                        actor.authority_basis if actor else authority_basis or self._prepared_basis
                    ),
                    outcome=outcome,
                    recorded_at=self._clock(),
                )
            )
        except Exception:  # noqa: BLE001 - terminal audit failure remains fail-closed.
            return error_response(503, "HIL callback completion audit is unavailable")
        return response


@dataclass(frozen=True, slots=True)
class HilCallbackDecisionService:
    """Resolve one normalized human decision under current server authority."""

    registry: HilDecisionRegistry
    outbox: HilDecisionOutbox
    authority: HilCallbackAuthority
    audit: HilCallbackAuditWriter
    context_reader: HilCallbackContextReader
    clock: Callable[[], datetime]

    async def begin(self, attempt: HilCallbackAttempt) -> HilCallbackSession | Response:
        """Load durable context and write the prepared audit intent."""
        try:
            context = await self._approval_context(attempt.approval_id)
        except IamFamilyError as exc:
            return family_error(exc)
        correlation_id = (
            context.correlation_id
            if context is not None
            else "unresolved:" + hashlib.sha256(attempt.approval_id.encode()).hexdigest()
        )
        prepared_basis = f"{attempt.channel_hint}:unverified"
        observed_at = self.clock()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            return error_response(503, "HIL callback clock is unavailable")
        try:
            await self.audit.append_callback_audit(
                HilCallbackAuditRecord(
                    callback_id=attempt.callback_id,
                    phase=HilCallbackAuditPhase.PREPARED,
                    correlation_id=correlation_id,
                    actor_identity_ref=actor_identity_reference(attempt.actor_hint),
                    authority_basis=prepared_basis,
                    outcome=HilCallbackOutcome.PENDING,
                    recorded_at=observed_at,
                )
            )
        except Exception:  # noqa: BLE001 - no callback may proceed without audit intent.
            return error_response(503, "HIL callback audit is unavailable")
        return HilCallbackSession(
            audit=self.audit,
            attempt=attempt,
            clock=self.clock,
            correlation_id=correlation_id,
            prepared_basis=prepared_basis,
            context=context,
        )

    async def decide(
        self,
        session: HilCallbackSession,
        *,
        approval_id: str,
        payload: NormalizedHilDecision,
    ) -> Response:
        """Bind context, re-resolve authority, record, and deliver one decision."""
        context = session.context
        if context is None:
            return await session.finish(
                error_response(404, "no HIL context exists for this approval", kind="not_found"),
                outcome=HilCallbackOutcome.INVALID,
            )
        mismatch = _context_mismatch(payload, context)
        if mismatch is not None:
            return await session.finish(
                error_response(409, mismatch, kind="context_mismatch"),
                outcome=HilCallbackOutcome.INVALID,
            )
        now = self.clock()
        if context.receipt is None and (context.expires_at is None or context.expires_at <= now):
            return await session.finish(
                error_response(410, "HIL approval has expired", kind="approval_expired"),
                outcome=HilCallbackOutcome.EXPIRED,
                authority_basis=f"{payload.channel.value}:expired_context",
            )
        try:
            actor = await self.authority.authenticate(
                authorization=payload.authorization,
                channel=payload.channel,
                provider_actor_id=payload.provider_actor_id,
                audience=payload.audience,
            )
        except HilCallbackAuthorityError as exc:
            return await session.finish(
                error_response(exc.status_code, str(exc), kind=exc.kind),
                outcome=HilCallbackOutcome.INVALID,
                authority_basis=f"{payload.channel.value}:authority_refused",
            )
        if context.submitter_oid and _normalize(context.submitter_oid) == actor.oid:
            return await session.finish(
                error_response(
                    403,
                    "no_self_approval - callback actor equals submitter",
                    kind="self_approval_forbidden",
                ),
                outcome=HilCallbackOutcome.INVALID,
                actor=actor,
            )
        if context.metadata.get("decision_route") == "workflow" and not meets_role(
            actor.roles, context.metadata.get("required_role", "")
        ):
            return await session.finish(
                error_response(
                    403,
                    "approver does not satisfy the workflow approval role",
                    kind="role_forbidden",
                ),
                outcome=HilCallbackOutcome.INVALID,
                actor=actor,
            )
        try:
            receipt = await self._record(context, payload=payload, actor=actor)
        except _AlreadyResolvedError:
            return await session.finish(
                error_response(
                    409,
                    "approval was already resolved by a different decision or actor",
                    kind="already_resolved",
                ),
                outcome=HilCallbackOutcome.INVALID,
                actor=actor,
            )
        except IamFamilyError as exc:
            return await session.finish(
                family_error(exc),
                outcome=HilCallbackOutcome.INVALID,
                actor=actor,
            )
        if not receipt.delivered:
            try:
                await self.outbox.enqueue(HilDecisionOutboxRequest(receipt=receipt))
            except Exception:  # noqa: BLE001 - recorded receipt remains replayable.
                return await session.finish(
                    error_response(
                        503,
                        "decision was recorded; delivery has not been accepted yet and is "
                        "redriven from the durable outbox",
                        kind="decision_publish_failed",
                    ),
                    outcome=_terminal_outcome(payload.decision),
                    actor=actor,
                )
            try:
                receipt = await self.registry.mark_delivered(receipt)
            except IamFamilyError:
                # Broker acceptance already happened; the lease-fenced replay
                # worker re-drives the durable record and marks it delivered.
                receipt = replace(receipt, delivered=False)
        return await session.finish(
            JSONResponse(
                {
                    "approval_id": receipt.approval_id or approval_id,
                    "idempotency_key": receipt.idempotency_key,
                    "correlation_id": context.correlation_id,
                    "decision": receipt.decision.value,
                    "already_recorded": receipt.already_recorded,
                    "receipt_ref": receipt.receipt_ref,
                    "decided_at": receipt.decided_at.astimezone(UTC).isoformat(),
                    "delivered": receipt.delivered,
                }
            ),
            outcome=_terminal_outcome(payload.decision),
            actor=actor,
        )

    async def _record(
        self,
        context: _ApprovalContext,
        *,
        payload: NormalizedHilDecision,
        actor: HilCallbackActor,
    ) -> HilDecisionReceipt:
        receipt = context.receipt
        if receipt is not None:
            if (
                receipt.decision is not payload.decision
                or _normalize(receipt.approver_oid) != actor.oid
                or receipt.idempotency_key != context.idempotency_key
            ):
                raise _AlreadyResolvedError
            return replace(receipt, already_recorded=True)
        return await self.registry.record_decision(
            HilDecisionCommand(
                idempotency_key=context.idempotency_key,
                decision=payload.decision,
                approver_oid=actor.oid,
                justification=payload.justification,
                decided_at=payload.decided_at,
            )
        )

    async def _approval_context(self, approval_id: str) -> _ApprovalContext | None:
        original = await self.context_reader.get_callback_context(approval_id)
        receipt = await self.registry.get_decision_by_approval_id(approval_id)
        if original is None:
            return None
        return _ApprovalContext(
            correlation_id=original.correlation_id,
            idempotency_key=original.idempotency_key,
            action_hash=original.action_hash,
            expires_at=original.expires_at,
            submitter_oid=original.submitter_oid,
            metadata=original.metadata,
            receipt=receipt,
        )


class _AlreadyResolvedError(RuntimeError):
    """A durable receipt conflicts with the replayed decision or actor."""


def _context_mismatch(payload: NormalizedHilDecision, context: _ApprovalContext) -> str | None:
    if payload.correlation_id != context.correlation_id:
        return "callback correlation_id does not match the original approval"
    if payload.idempotency_key != context.idempotency_key:
        return "callback idempotency_key does not match the original approval"
    if not context.action_hash or payload.action_hash != context.action_hash:
        return "callback action_hash does not match the original approval"
    return None


def _terminal_outcome(decision: HilApprovalDecision) -> HilCallbackOutcome:
    return (
        HilCallbackOutcome.ACCEPTED
        if decision is HilApprovalDecision.APPROVE
        else HilCallbackOutcome.REJECTED
    )


def _normalize(value: str) -> str:
    return value.strip().casefold()


__all__ = [
    "HilCallbackAttempt",
    "HilCallbackDecisionService",
    "HilCallbackSession",
    "NormalizedHilDecision",
]
