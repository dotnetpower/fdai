"""Durable, CAS-serialized HIL decision claims for Var."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai_service_contracts.test_context import TestContextCommand

from fdai.agents._framework.action_run_identity import (
    action_run_identity_digest,
    is_action_run_identity,
)
from fdai.agents._framework.bus import PantheonBus
from fdai.core.operational_context.test_context_commands import TestContextCommandHandler
from fdai.shared.providers.state_store import StateStore

_MAX_CAS_ATTEMPTS = 16
_TERMINAL_DISPOSITIONS = frozenset({"approved", "rejected"})


class TestContextReviewMixin:
    """Var-owned independent test-context review without action approval authority."""

    bus: PantheonBus | None
    _test_context_commands: TestContextCommandHandler | None = None

    def bind_test_context_commands(self, handler: TestContextCommandHandler) -> None:
        """Bind one independent context reviewer before accepting normalized commands."""
        if self._test_context_commands is not None:
            raise RuntimeError("Var context command handler is already bound")
        self._test_context_commands = handler

    async def _test_context_review_message(
        self, topic: str, payload: dict[str, Any], record_behavior: Callable[[str], None]
    ) -> bool:
        if topic != "object.event" or payload.get("event_type") != "test_context.command.v1":
            return False
        if payload.get("producer_principal") != "Huginn":
            raise PermissionError("context review requires normalized authenticated ingress")
        command = payload.get("attributes")
        if not isinstance(command, dict):
            raise ValueError("test context review command is malformed")
        typed_command = TestContextCommand.model_validate(command)
        if typed_command.request.operation == "propose":
            return True
        if self._test_context_commands is None or self.bus is None:
            raise RuntimeError("Var test context dependencies are unavailable")
        async with asyncio.timeout(5):
            verified = await self._test_context_commands.review(command)
            await self.bus.publish(
                "Var",
                "object.approval",
                {
                    "kind": "test_context_review",
                    "state": "review_recorded",
                    "correlation_id": verified.idempotency_key,
                    "idempotency_key": "context-review:" + verified.idempotency_key,
                    "command": verified.model_dump(mode="json"),
                    "execution_authority": False,
                },
            )
        record_behavior("test_context:review_published")
        return True


@dataclass
class PendingHilTicket:
    """Var-owned pending decision data; fields and defaults preserve the public ticket contract."""

    correlation_id: str
    action_type: str
    resource_id: str | None
    quorum_required: int
    action_id: str | None = None
    action_run_identity: str | None = None
    initiator_principal: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    kind: str = "action"
    document_id: str | None = None
    upload_id: str | None = None
    stage: str | None = None
    idempotency_key: str = ""
    rollback_contract: str = "state_forward_only"
    decision_case: dict[str, Any] | None = None
    approvers: list[str] = field(default_factory=list)
    rejected: bool = False

    def __post_init__(self) -> None:
        if self.kind != "action":
            return
        if not self.idempotency_key:
            self.idempotency_key = self.correlation_id
        if self.action_run_identity is None:
            self.action_run_identity = action_run_identity_digest(
                {
                    "correlation_id": self.correlation_id,
                    "action_id": self.action_id,
                    "action_type": self.action_type,
                    "resource_id": self.resource_id,
                    "action_idempotency_key": self.idempotency_key,
                    "params": self.params,
                    "quorum_required": self.quorum_required,
                    "initiator_principal": self.initiator_principal,
                    "rollback_contract": self.rollback_contract,
                    "verdict": "hil",
                    "workflow_action": None,
                }
            )
        elif not is_action_run_identity(self.action_run_identity):
            raise ValueError("pending HIL ticket ActionRun identity is malformed")


@dataclass(frozen=True, slots=True)
class PendingShadowReview:
    """One Saga-authenticated shadow outcome awaiting a human comparison."""

    correlation_id: str
    action_type: str
    observed_at: str
    policy_escape: bool
    initiator_principal: str | None


@dataclass(frozen=True, slots=True)
class ApprovalDecisionState:
    """Validated durable decision aggregate for one HIL ticket."""

    revision: int
    disposition: str
    approved_principals: tuple[str, ...]
    ticket_identity: dict[str, Any]

    @property
    def rejected(self) -> bool:
        return self.disposition == "rejected"

    @property
    def terminal(self) -> bool:
        return self.disposition in _TERMINAL_DISPOSITIONS


class ApprovalTicket(Protocol):
    correlation_id: str
    action_id: str | None
    action_type: str
    action_run_identity: str | None
    resource_id: str | None
    quorum_required: int
    approvers: list[str]
    kind: str
    stage: str | None
    document_id: str | None
    upload_id: str | None
    idempotency_key: str
    rollback_contract: str
    decision_case: dict[str, Any] | None
    params: dict[str, Any]


class VarDecisionJournal:
    """Atomically combine immutable per-principal decisions across replicas."""

    def __init__(self, store: StateStore, *, state_prefix: str) -> None:
        self._store = store
        self._state_prefix = state_prefix

    async def record(
        self,
        *,
        state_key: str,
        correlation_id: str,
        action_type: str,
        quorum_required: int,
        ticket_identity: Mapping[str, Any],
        principal: str,
        decision: str,
    ) -> ApprovalDecisionState:
        """Record one decision and return the linearized aggregate state."""
        if decision not in _TERMINAL_DISPOSITIONS:
            raise ValueError("approval decision MUST be approved or rejected")
        ticket_digest = _ticket_digest(ticket_identity)
        claim_id = hashlib.sha256(principal.encode("utf-8")).hexdigest()
        claim = {
            "principal": principal,
            "decision": decision,
            "receipt_ref": _decision_receipt_ref(
                ticket_digest=ticket_digest,
                principal=principal,
                decision=decision,
            ),
        }
        for _attempt in range(_MAX_CAS_ATTEMPTS):
            stored = await self._store.read_state(state_key)
            if stored is None:
                claims = {claim_id: claim}
                value = _decision_state(
                    revision=1,
                    correlation_id=correlation_id,
                    action_type=action_type,
                    quorum_required=quorum_required,
                    ticket_digest=ticket_digest,
                    ticket_identity=ticket_identity,
                    claims=claims,
                )
                created = await self._store.write_state_with_audit_if_absent(
                    state_key,
                    value,
                    _decision_audit_entry(
                        correlation_id=correlation_id,
                        action_type=action_type,
                        ticket_digest=ticket_digest,
                        claim_id=claim_id,
                        decision=decision,
                        revision=1,
                    ),
                )
                if created:
                    return _parse_decision_state(
                        value,
                        correlation_id=correlation_id,
                        action_type=action_type,
                        quorum_required=quorum_required,
                        ticket_digest=ticket_digest,
                        ticket_identity=ticket_identity,
                    )[0]
                continue

            current, claims = _parse_decision_state(
                stored,
                correlation_id=correlation_id,
                action_type=action_type,
                quorum_required=quorum_required,
                ticket_digest=ticket_digest,
                ticket_identity=ticket_identity,
            )
            prior = claims.get(claim_id)
            if prior is not None:
                if prior != claim:
                    raise ValueError("approval principal cannot replace an existing decision")
                return current
            if current.terminal:
                return current

            next_revision = current.revision + 1
            next_claims = {**claims, claim_id: claim}
            value = _decision_state(
                revision=next_revision,
                correlation_id=correlation_id,
                action_type=action_type,
                quorum_required=quorum_required,
                ticket_digest=ticket_digest,
                ticket_identity=ticket_identity,
                claims=next_claims,
            )
            advanced = await self._store.compare_and_set_state_with_audit(
                state_key,
                value,
                expected_revision=current.revision,
                audit_entry=_decision_audit_entry(
                    correlation_id=correlation_id,
                    action_type=action_type,
                    ticket_digest=ticket_digest,
                    claim_id=claim_id,
                    decision=decision,
                    revision=next_revision,
                ),
            )
            if advanced:
                return _parse_decision_state(
                    value,
                    correlation_id=correlation_id,
                    action_type=action_type,
                    quorum_required=quorum_required,
                    ticket_digest=ticket_digest,
                    ticket_identity=ticket_identity,
                )[0]
        raise RuntimeError("approval decision CAS retry limit exceeded")

    async def next_pending_finalization(self) -> ApprovalDecisionState | None:
        """Return one terminal decision whose final payload is not checkpointed."""
        stored = await self._store.find_state(
            f"{self._state_prefix}/",
            field="finalization_status",
            value="pending",
        )
        if stored is None:
            return None
        ticket_identity = _stored_ticket_identity(stored)
        return _parse_decision_state(
            stored,
            correlation_id=str(ticket_identity["correlation_id"]),
            action_type=str(ticket_identity["action_type"]),
            quorum_required=int(ticket_identity["quorum_required"]),
            ticket_digest=_ticket_digest(ticket_identity),
            ticket_identity=ticket_identity,
        )[0]

    async def mark_finalized(
        self,
        *,
        state_key: str,
        ticket_identity: Mapping[str, Any],
    ) -> None:
        """Advance one terminal decision after its final payload is durable."""
        ticket_digest = _ticket_digest(ticket_identity)
        for _attempt in range(_MAX_CAS_ATTEMPTS):
            stored = await self._store.read_state(state_key)
            if stored is None:
                raise RuntimeError("approval decision state disappeared")
            current, claims = _parse_decision_state(
                stored,
                correlation_id=str(ticket_identity["correlation_id"]),
                action_type=str(ticket_identity["action_type"]),
                quorum_required=int(ticket_identity["quorum_required"]),
                ticket_digest=ticket_digest,
                ticket_identity=ticket_identity,
            )
            if not current.terminal:
                raise RuntimeError("approval decision is not terminal")
            if stored.get("finalization_status") == "complete":
                return
            next_revision = current.revision + 1
            value = _decision_state(
                revision=next_revision,
                correlation_id=str(ticket_identity["correlation_id"]),
                action_type=str(ticket_identity["action_type"]),
                quorum_required=int(ticket_identity["quorum_required"]),
                ticket_digest=ticket_digest,
                ticket_identity=ticket_identity,
                claims=claims,
                finalization_status="complete",
            )
            advanced = await self._store.compare_and_set_state_with_audit(
                state_key,
                value,
                expected_revision=current.revision,
                audit_entry={
                    "actor": "Var",
                    "action_kind": "approval.finalized",
                    "correlation_id": str(ticket_identity["correlation_id"]),
                    "ticket_digest": ticket_digest,
                    "revision": next_revision,
                    "recorded_at": datetime.now(tz=UTC).isoformat(),
                },
            )
            if advanced:
                return
        raise RuntimeError("approval finalization CAS retry limit exceeded")


def _decision_state(
    *,
    revision: int,
    correlation_id: str,
    action_type: str,
    quorum_required: int,
    ticket_digest: str,
    ticket_identity: Mapping[str, Any],
    claims: Mapping[str, Mapping[str, str]],
    finalization_status: str | None = None,
) -> dict[str, Any]:
    approved = sum(claim["decision"] == "approved" for claim in claims.values())
    rejected = any(claim["decision"] == "rejected" for claim in claims.values())
    disposition = (
        "rejected" if rejected else "approved" if approved >= quorum_required else "pending"
    )
    expected_finalization = "not_ready" if disposition == "pending" else "pending"
    resolved_finalization = finalization_status or expected_finalization
    if (
        disposition == "pending"
        and resolved_finalization != "not_ready"
        or disposition in _TERMINAL_DISPOSITIONS
        and resolved_finalization not in {"pending", "complete"}
    ):
        raise ValueError("approval finalization status conflicts with disposition")
    return {
        "schema_version": "1.0.0",
        "revision": revision,
        "correlation_id": correlation_id,
        "action_type": action_type,
        "quorum_required": quorum_required,
        "ticket_digest": ticket_digest,
        "ticket_identity": _canonical_ticket_identity(ticket_identity),
        "decision_claims": {claim_id: dict(claim) for claim_id, claim in sorted(claims.items())},
        "disposition": disposition,
        "finalization_status": resolved_finalization,
    }


def _parse_decision_state(
    value: Mapping[str, Any],
    *,
    correlation_id: str,
    action_type: str,
    quorum_required: int,
    ticket_digest: str,
    ticket_identity: Mapping[str, Any],
) -> tuple[ApprovalDecisionState, dict[str, dict[str, str]]]:
    revision = value.get("revision")
    claims_raw = value.get("decision_claims")
    if (
        value.get("schema_version") != "1.0.0"
        or not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 1
        or value.get("correlation_id") != correlation_id
        or value.get("action_type") != action_type
        or value.get("quorum_required") != quorum_required
        or value.get("ticket_digest") != ticket_digest
        or value.get("ticket_identity") != _canonical_ticket_identity(ticket_identity)
        or not isinstance(claims_raw, Mapping)
        or not claims_raw
    ):
        raise ValueError("stored approval decision state conflicts with its ticket")

    claims: dict[str, dict[str, str]] = {}
    principals: set[str] = set()
    for claim_id, raw_claim in claims_raw.items():
        if not isinstance(claim_id, str) or not isinstance(raw_claim, Mapping):
            raise RuntimeError("stored approval decision claim is malformed")
        principal = raw_claim.get("principal")
        decision = raw_claim.get("decision")
        receipt_ref = raw_claim.get("receipt_ref")
        if (
            not isinstance(principal, str)
            or not principal
            or principal != principal.strip().casefold()
            or hashlib.sha256(principal.encode("utf-8")).hexdigest() != claim_id
            or decision not in _TERMINAL_DISPOSITIONS
            or receipt_ref
            != _decision_receipt_ref(
                ticket_digest=ticket_digest,
                principal=principal,
                decision=str(decision),
            )
            or principal in principals
        ):
            raise RuntimeError("stored approval decision claim is malformed")
        principals.add(principal)
        claims[claim_id] = {
            "principal": principal,
            "decision": str(decision),
            "receipt_ref": str(receipt_ref),
        }

    canonical = _decision_state(
        revision=revision,
        correlation_id=correlation_id,
        action_type=action_type,
        quorum_required=quorum_required,
        ticket_digest=ticket_digest,
        ticket_identity=ticket_identity,
        claims=claims,
        finalization_status=str(value.get("finalization_status") or ""),
    )
    if dict(value) != canonical:
        raise RuntimeError("stored approval decision aggregate is malformed")
    approved_principals = tuple(
        sorted(claim["principal"] for claim in claims.values() if claim["decision"] == "approved")
    )
    return (
        ApprovalDecisionState(
            revision=revision,
            disposition=str(canonical["disposition"]),
            approved_principals=approved_principals,
            ticket_identity=deepcopy(dict(ticket_identity)),
        ),
        claims,
    )


def _ticket_digest(ticket_identity: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        ticket_identity,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _canonical_ticket_identity(
    ticket_identity: Mapping[str, Any],
) -> dict[str, Any]:
    encoded = json.dumps(
        ticket_identity,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    loaded = json.loads(encoded)
    if not isinstance(loaded, dict):
        raise ValueError("approval ticket identity MUST be an object")
    return loaded


def _stored_ticket_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    stored = value.get("ticket_identity")
    if not isinstance(stored, Mapping):
        raise RuntimeError("stored approval ticket identity is malformed")
    return _canonical_ticket_identity(stored)


def _decision_receipt_ref(
    *,
    ticket_digest: str,
    principal: str,
    decision: str,
) -> str:
    encoded = f"{ticket_digest}\x00{principal}\x00{decision}".encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _decision_audit_entry(
    *,
    correlation_id: str,
    action_type: str,
    ticket_digest: str,
    claim_id: str,
    decision: str,
    revision: int,
) -> dict[str, Any]:
    return {
        "actor": "Var",
        "action_kind": "approval.decision_recorded",
        "correlation_id": correlation_id,
        "action_type": action_type,
        "ticket_digest": ticket_digest,
        "approver_digest": f"sha256:{claim_id}",
        "decision": decision,
        "revision": revision,
        "recorded_at": datetime.now(tz=UTC).isoformat(),
    }


def approval_for_ticket(
    ticket: ApprovalTicket,
    *,
    state: str,
    approvers: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Build one deterministic final approval from a validated ticket."""
    approval: dict[str, Any] = {
        "producer_principal": "Var",
        "kind": ticket.kind,
        "correlation_id": ticket.correlation_id,
        "idempotency_key": (ticket.idempotency_key or f"{ticket.correlation_id}:hil_pending"),
        "action_id": ticket.action_id,
        "action_type": ticket.action_type,
        "action_run_identity": ticket.action_run_identity,
        "action_idempotency_key": ticket.idempotency_key,
        "resource_id": ticket.resource_id,
        "rollback_contract": ticket.rollback_contract,
        "state": state,
        "approvers": list(approvers if approvers is not None else ticket.approvers),
        "decision_case": ticket.decision_case,
        "params": dict(ticket.params),
    }
    if ticket.kind == "document_ingestion":
        approval.update(
            {
                "stage": ticket.stage,
                "document_id": ticket.document_id,
                "upload_id": ticket.upload_id,
            }
        )
    return approval


def final_approval_record(
    approval: Mapping[str, Any],
    *,
    publication_status: str,
    revision: int,
) -> dict[str, Any]:
    """Wrap a final approval with durable outbox state."""
    return {
        "schema_version": "1.0.0",
        "record_kind": "final_approval",
        "revision": revision,
        "correlation_id": str(approval["correlation_id"]),
        "publication_status": publication_status,
        "approval": deepcopy(dict(approval)),
    }


__all__ = [
    "ApprovalDecisionState",
    "VarDecisionJournal",
    "approval_for_ticket",
    "final_approval_record",
]
