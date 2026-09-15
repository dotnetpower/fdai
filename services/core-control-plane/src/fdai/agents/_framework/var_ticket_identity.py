"""Identity and durable key helpers for Var approval tickets."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from fdai.agents._framework.action_run_identity import (
    action_run_identity_digest,
    is_action_run_identity,
)

APPROVAL_STATE_PREFIX = "pantheon/var/approval"


class _IdentityStore(Protocol):
    async def write_state_if_absent(self, key: str, value: dict[str, Any]) -> bool: ...

    async def read_state(self, key: str) -> Mapping[str, Any] | None: ...


class _LocalIdentityStore(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...


@dataclass
class PendingHilTicket:
    """One action or document approval awaiting distinct human principals."""

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


def approval_state_key(
    correlation_id: str,
    suffix: str,
    action_run_identity: str | None,
) -> str:
    """Scope one durable approval row to correlation and immutable run identity."""

    correlation_digest = hashlib.sha256(correlation_id.encode("utf-8")).hexdigest()
    if action_run_identity is None:
        identity_scope = "non-action"
    elif is_action_run_identity(action_run_identity):
        identity_scope = action_run_identity[7:]
    else:
        raise ValueError("approval ActionRun identity is malformed")
    return f"{APPROVAL_STATE_PREFIX}/{correlation_digest}/{identity_scope}/{suffix}"


def approval_cache_key(
    correlation_id: str,
    action_run_identity: str | None,
) -> tuple[str, str]:
    """Return the process-local key matching the durable identity scope."""

    return correlation_id, action_run_identity or "non-action"


async def claim_action_correlation_identity(
    store: _IdentityStore | None,
    local: _LocalIdentityStore,
    correlation_id: str,
    action_run_identity: str,
) -> bool:
    """Claim one immutable action identity for a correlation across restart."""

    prior_identity = local.get(correlation_id)
    if prior_identity is not None and prior_identity != action_run_identity:
        return False
    if store is None:
        local.set(correlation_id, action_run_identity)
        return True
    correlation_digest = hashlib.sha256(correlation_id.encode("utf-8")).hexdigest()
    key = f"{APPROVAL_STATE_PREFIX}/{correlation_digest}/action-identity"
    claim = {
        "correlation_id": correlation_id,
        "action_run_identity": action_run_identity,
    }
    if await store.write_state_if_absent(key, claim):
        local.set(correlation_id, action_run_identity)
        return True
    stored = await store.read_state(key)
    if stored is None:
        raise RuntimeError("approval ActionRun identity claim disappeared")
    if stored == claim:
        local.set(correlation_id, action_run_identity)
        return True
    if set(stored) != set(claim):
        raise RuntimeError("stored approval ActionRun identity claim is malformed")
    return False


def remove_pending_ticket(
    pending: dict[str, PendingHilTicket],
    correlation_id: str,
    action_run_identity: str | None,
) -> None:
    """Remove only the pending ticket completed by this exact approval."""

    ticket = pending.get(correlation_id)
    if ticket is not None and ticket.action_run_identity == action_run_identity:
        del pending[correlation_id]


def approval_action_identity(approval: Mapping[str, Any]) -> str | None:
    """Validate and return the ActionRun identity carried by a final approval."""

    identity = approval.get("action_run_identity")
    if approval.get("kind") == "action":
        if (
            not is_action_run_identity(identity)
            or not isinstance(approval.get("action_idempotency_key"), str)
            or not approval["action_idempotency_key"]
            or not isinstance(approval.get("rollback_contract"), str)
            or not approval["rollback_contract"]
        ):
            raise RuntimeError("stored action approval identity is malformed")
        return str(identity)
    if identity is not None:
        raise RuntimeError("non-action approval cannot carry an ActionRun identity")
    return None


def ticket_from_identity(identity: Mapping[str, Any]) -> PendingHilTicket:
    """Rehydrate one validated approval ticket from its durable identity."""

    correlation_id = identity.get("correlation_id")
    action_type = identity.get("action_type")
    quorum_required = identity.get("quorum_required")
    params = identity.get("params")
    decision_case = identity.get("decision_case")
    if (
        not isinstance(correlation_id, str)
        or not correlation_id
        or not isinstance(action_type, str)
        or not action_type
        or not isinstance(quorum_required, int)
        or isinstance(quorum_required, bool)
        or quorum_required < 1
        or not isinstance(params, Mapping)
        or decision_case is not None
        and not isinstance(decision_case, Mapping)
    ):
        raise RuntimeError("stored approval ticket identity is malformed")
    optional_strings = {
        field_name: identity.get(field_name)
        for field_name in (
            "action_id",
            "resource_id",
            "initiator_principal",
            "document_id",
            "upload_id",
            "stage",
        )
    }
    if any(value is not None and not isinstance(value, str) for value in optional_strings.values()):
        raise RuntimeError("stored approval ticket identity is malformed")
    kind = identity.get("kind")
    idempotency_key = identity.get("idempotency_key")
    rollback_contract = identity.get("rollback_contract")
    action_run_identity = identity.get("action_run_identity")
    if (
        not isinstance(kind, str)
        or not isinstance(idempotency_key, str)
        or not isinstance(rollback_contract, str)
        or not rollback_contract
        or (kind == "action" and not is_action_run_identity(action_run_identity))
        or (kind != "action" and action_run_identity is not None)
    ):
        raise RuntimeError("stored approval ticket identity is malformed")
    return PendingHilTicket(
        correlation_id=correlation_id,
        action_id=optional_strings["action_id"],
        action_type=action_type,
        resource_id=optional_strings["resource_id"],
        quorum_required=quorum_required,
        action_run_identity=(str(action_run_identity) if action_run_identity is not None else None),
        initiator_principal=optional_strings["initiator_principal"],
        params=dict(params),
        kind=kind,
        document_id=optional_strings["document_id"],
        upload_id=optional_strings["upload_id"],
        stage=optional_strings["stage"],
        idempotency_key=idempotency_key,
        rollback_contract=rollback_contract,
        decision_case=dict(decision_case) if decision_case is not None else None,
    )


def ticket_identity(ticket: PendingHilTicket) -> dict[str, Any]:
    """Return the immutable durable identity for one pending ticket."""

    return {
        "correlation_id": ticket.correlation_id,
        "action_id": ticket.action_id,
        "action_type": ticket.action_type,
        "action_run_identity": ticket.action_run_identity,
        "resource_id": ticket.resource_id,
        "quorum_required": ticket.quorum_required,
        "initiator_principal": ticket.initiator_principal,
        "kind": ticket.kind,
        "document_id": ticket.document_id,
        "upload_id": ticket.upload_id,
        "stage": ticket.stage,
        "idempotency_key": ticket.idempotency_key,
        "rollback_contract": ticket.rollback_contract,
        "params": ticket.params,
        "decision_case": ticket.decision_case,
    }


__all__ = [
    "APPROVAL_STATE_PREFIX",
    "PendingHilTicket",
    "approval_action_identity",
    "approval_cache_key",
    "approval_state_key",
    "claim_action_correlation_identity",
    "remove_pending_ticket",
    "ticket_from_identity",
    "ticket_identity",
]
