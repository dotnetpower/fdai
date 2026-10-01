"""Operator-side durable acceptance for ordered-poison-halt clear requests."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fdai_service_contracts.bus_poison_halt_clear import (
    ORDERED_POISON_HALT_CLEAR_TOPIC,
    OrderedPoisonHaltClearRequest,
    ordered_poison_halt_clear_receipt_event,
)
from fdai_service_contracts.operator import OperatorPrincipal, OperatorPrincipalKind, OperatorRole

from fdai_operator_service.operator_request_receipt import OperatorRequestReceiptIssuer


class PoisonHaltProposalStore(Protocol):
    """Durably store one Operator clear request before broker publication."""

    async def append_proposal(
        self,
        *,
        family: str,
        operation: str,
        principal_id: str,
        idempotency_key: str,
        payload: Mapping[str, object],
        accepted_at: datetime | None = None,
    ) -> object: ...

    async def claim_poison_halt_clear_proposal(
        self,
        *,
        idempotency_key: str,
        worker_id: str,
        lease_seconds: int,
    ) -> object | None:
        """Claim one clear proposal before broker publication."""
        ...

    async def mark_poison_halt_clear_claim_published(
        self,
        *,
        key: str,
        claim_id: str,
    ) -> bool:
        """Mark one claimed clear proposal after broker acceptance."""
        ...

    async def release_poison_halt_clear_claim(self, *, key: str, claim_id: str) -> bool:
        """Release one claimed clear proposal after transport failure."""
        ...


class PoisonHaltClearPublisher(Protocol):
    """Publish an accepted clear request to Core."""

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> object: ...


@dataclass(frozen=True, slots=True)
class OrderedPoisonHaltClearAcceptance:
    """Operator acceptance returned to Console/API callers."""

    accepted: bool
    request_id: str
    topic: str


@dataclass(frozen=True, slots=True)
class OrderedPoisonHaltClearService:
    """Authorize an Owner, persist the request, then enqueue it for Core."""

    store: PoisonHaltProposalStore
    publisher: PoisonHaltClearPublisher
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    receipt_issuer: OperatorRequestReceiptIssuer | None = None
    worker_id: str = "operator-poison-halt-clear-inline"
    lease_seconds: int = 120

    async def accept(
        self,
        *,
        principal: OperatorPrincipal,
        idempotency_key: str,
        body: Mapping[str, object],
    ) -> OrderedPoisonHaltClearAcceptance:
        if self.receipt_issuer is None:
            raise RuntimeError("ordered poison halt clear receipt issuer is unavailable")
        if principal.principal_kind is not OperatorPrincipalKind.HUMAN:
            raise PermissionError("ordered poison halt clear requires a human principal")
        if OperatorRole.OWNER not in principal.roles or OperatorRole.BREAK_GLASS in principal.roles:
            raise PermissionError("ordered poison halt clear requires Owner")
        accepted_at = self.clock().astimezone(UTC)
        request = OrderedPoisonHaltClearRequest.model_validate(
            {
                **dict(body),
                "request_id": _request_id(principal.subject_id, idempotency_key),
                "idempotency_key": idempotency_key,
                "requested_at": accepted_at,
                "principal_id": principal.subject_id,
                "principal_kind": principal.principal_kind,
                "principal_roles": tuple(sorted(principal.roles, key=lambda role: role.value)),
            }
        )
        payload = request.model_dump(mode="json")
        payload["operator_request_receipt"] = self.receipt_issuer.issue(
            ordered_poison_halt_clear_receipt_event(payload)
        ).model_dump(mode="json")
        stored = await self.store.append_proposal(
            family="operations",
            operation="bus.ordered-poison-halt.clear",
            principal_id=principal.subject_id,
            idempotency_key=idempotency_key,
            payload=payload,
            accepted_at=accepted_at,
        )
        if _stored_dispatch_status(stored) != "published":
            claim = await self.store.claim_poison_halt_clear_proposal(
                idempotency_key=idempotency_key,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            if claim is None:
                return OrderedPoisonHaltClearAcceptance(
                    accepted=True,
                    request_id=request.request_id,
                    topic=ORDERED_POISON_HALT_CLEAR_TOPIC,
                )
            claim_key = _claim_key(claim)
            claim_id = _claim_id(claim)
            stored_payload = _claim_payload(claim)
            try:
                await self.publisher.publish(
                    ORDERED_POISON_HALT_CLEAR_TOPIC,
                    request.idempotency_key,
                    stored_payload,
                )
            except Exception:
                await self.store.release_poison_halt_clear_claim(
                    key=claim_key,
                    claim_id=claim_id,
                )
                raise
            marked = await self.store.mark_poison_halt_clear_claim_published(
                key=claim_key,
                claim_id=claim_id,
            )
            if not marked:
                raise RuntimeError("ordered poison halt clear publication state was not recorded")
        return OrderedPoisonHaltClearAcceptance(
            accepted=True,
            request_id=request.request_id,
            topic=ORDERED_POISON_HALT_CLEAR_TOPIC,
        )


def _request_id(principal_id: str, idempotency_key: str) -> str:
    digest = hashlib.sha256(f"{principal_id}\0{idempotency_key}".encode()).hexdigest()
    return f"ordered-poison-halt-clear:{digest}"


def _stored_dispatch_status(stored: object) -> str:
    record = getattr(stored, "record", None)
    if not isinstance(record, Mapping):
        return ""
    status = record.get("dispatch_status")
    return status if isinstance(status, str) else ""


def _claim_key(claim: object) -> str:
    key = getattr(claim, "key", None)
    if not isinstance(key, str) or not key:
        raise RuntimeError("ordered poison halt clear claim is malformed")
    return key


def _claim_id(claim: object) -> str:
    claim_id = getattr(claim, "claim_id", None)
    if not isinstance(claim_id, str) or not claim_id:
        raise RuntimeError("ordered poison halt clear claim is malformed")
    return claim_id


def _claim_payload(claim: object) -> Mapping[str, object]:
    payload = getattr(claim, "payload", None)
    if not isinstance(payload, Mapping):
        raise RuntimeError("ordered poison halt clear claim is malformed")
    return payload


__all__ = [
    "OrderedPoisonHaltClearAcceptance",
    "OrderedPoisonHaltClearService",
    "PoisonHaltClearPublisher",
    "PoisonHaltProposalStore",
]
