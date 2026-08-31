"""Durable Operator outbox handoff and lease-fenced replay for HIL decisions.

Every recorded human decision is persisted as an ``iam`` /
``hil.decision.enqueue`` proposal *before* any broker call. Two publishers
consume that one durable record:

* the immediate callback path (:class:`DurableHilDecisionOutboxPublisher`),
  which keeps the operator's HTTP response truthful; and
* the lease-fenced replay drainer (:class:`HilDecisionOutboxDrainer`), which
  redrives a record whose broker call failed, timed out, or never happened
  because the process crashed after the durable write.

Both build the wire payload with :func:`hil_decision_payload` from the same
persisted receipt, so the two paths can never publish conflicting content, and
both mark delivery only after the broker accepted the record.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fdai_operator_service.families.iam.contracts import (
    HilApprovalDecision,
    HilDecisionOutbox,
    HilDecisionOutboxRequest,
    HilDecisionReceipt,
)

_LOGGER = logging.getLogger(__name__)
_DELIVERY_SUFFIX = ":delivery"
HIL_DECISION_ENQUEUE_OPERATION = "hil.decision.enqueue"


def hil_decision_delivery_key(idempotency_key: str) -> str:
    """Return the stable durable-outbox idempotency key for one decision."""
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"hil-decision:{digest}{_DELIVERY_SUFFIX}"


def hil_decision_payload(receipt: HilDecisionReceipt) -> dict[str, object]:
    """Build the single canonical decision payload both publishers emit."""
    return {
        "approval_id": receipt.approval_id,
        "idempotency_key": receipt.idempotency_key,
        "decision": receipt.decision.value,
        "approver_oid": receipt.approver_oid,
        "justification": receipt.justification,
        "decided_at": receipt.decided_at.astimezone(UTC).isoformat(),
        "receipt_ref": receipt.receipt_ref,
    }


def outbox_payload(receipt: HilDecisionReceipt) -> dict[str, object]:
    """Return the durable proposal body persisted before broker publication."""
    return {"receipt": hil_decision_payload(receipt)}


def receipt_from_outbox_payload(payload: Mapping[str, object]) -> HilDecisionReceipt:
    """Rebuild the exact receipt a durable outbox record was written from."""
    raw = payload.get("receipt")
    if not isinstance(raw, Mapping):
        raise ValueError("HIL decision outbox payload is malformed")
    try:
        approval_id = _text(raw, "approval_id")
        idempotency_key = _text(raw, "idempotency_key")
        decision = HilApprovalDecision(_text(raw, "decision"))
        approver_oid = _text(raw, "approver_oid")
        decided_at = datetime.fromisoformat(_text(raw, "decided_at"))
    except (KeyError, ValueError) as exc:
        raise ValueError("HIL decision outbox payload is malformed") from exc
    if decided_at.tzinfo is None or decided_at.utcoffset() is None:
        raise ValueError("HIL decision outbox payload time is not timezone-aware")
    justification = raw.get("justification", "")
    receipt_ref = raw.get("receipt_ref", "")
    if not isinstance(justification, str) or not isinstance(receipt_ref, str):
        raise ValueError("HIL decision outbox payload is malformed")
    return HilDecisionReceipt(
        approval_id=approval_id,
        idempotency_key=idempotency_key,
        decision=decision,
        approver_oid=approver_oid,
        decided_at=decided_at,
        receipt_ref=receipt_ref,
        justification=justification,
    )


class HilDecisionPublisher(Protocol):
    """Publish one bounded mapping after its Operator outbox record is durable."""

    async def publish(
        self,
        topic: str,
        key: str,
        payload: dict[str, object],
    ) -> object: ...


class HilDecisionDeliveryLedger(Protocol):
    """Close the durable outbox record once the broker accepted the decision."""

    async def mark_decision_published(self, idempotency_key: str) -> bool: ...


class HilDecisionDeliveryMarker(Protocol):
    """Persist broker acceptance on the authoritative decision receipt."""

    async def mark_delivered(self, receipt: HilDecisionReceipt) -> HilDecisionReceipt: ...


@dataclass(frozen=True, slots=True)
class DurableHilDecisionOutboxPublisher:
    """Persist first, then publish; broker failure leaves the record retryable."""

    durable: HilDecisionOutbox
    publisher: HilDecisionPublisher
    topic: str
    ledger: HilDecisionDeliveryLedger | None = None
    registry: HilDecisionDeliveryMarker | None = None

    def __post_init__(self) -> None:
        if not self.topic.strip():
            raise ValueError("HIL decision topic MUST be non-empty")

    async def enqueue(self, request: HilDecisionOutboxRequest) -> None:
        """Persist the exact request before waiting for broker acceptance."""
        await self.durable.enqueue(request)
        receipt = request.receipt
        await self.publisher.publish(
            self.topic,
            receipt.approval_id,
            hil_decision_payload(receipt),
        )
        if self.registry is not None:
            await self.registry.mark_delivered(receipt)
        if self.ledger is not None:
            # A failure to close the record only leaves it claimable. The
            # drainer skips an already-delivered receipt, so a later replay
            # never regresses delivered state or emits a different payload.
            await self.ledger.mark_decision_published(receipt.idempotency_key)


class HilDecisionOutboxClaim(Protocol):
    """One leased durable HIL decision outbox record."""

    @property
    def key(self) -> str: ...

    @property
    def claim_id(self) -> str: ...

    @property
    def payload(self) -> Mapping[str, object]: ...


class HilDecisionOutboxStore(Protocol):
    """Lease, close, and release durable HIL decision outbox records."""

    async def claim_hil_decision_proposal(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> HilDecisionOutboxClaim | None: ...

    async def mark_proposal_published(self, *, key: str, claim_id: str) -> bool: ...

    async def mark_proposal_rejected(
        self,
        *,
        key: str,
        claim_id: str,
        reason_code: str,
    ) -> bool: ...

    async def release_proposal_claim(self, *, key: str, claim_id: str) -> bool: ...


class HilDecisionDeliveryRegistry(Protocol):
    """Read and monotonically advance the durable delivery state of a receipt."""

    async def get_decision_by_approval_id(
        self,
        approval_id: str,
    ) -> HilDecisionReceipt | None: ...

    async def mark_delivered(self, receipt: HilDecisionReceipt) -> HilDecisionReceipt: ...


@dataclass(frozen=True, slots=True)
class HilDecisionOutboxDrainer:
    """Lease one durable decision, publish it, and only then mark it delivered."""

    store: HilDecisionOutboxStore
    registry: HilDecisionDeliveryRegistry
    publisher: HilDecisionPublisher
    topic: str
    worker_id: str = "operator-hil-decision-outbox"
    lease_seconds: int = 60

    def __post_init__(self) -> None:
        if not self.topic.strip():
            raise ValueError("HIL decision topic MUST be non-empty")
        if not 1 <= self.lease_seconds <= 300:
            raise ValueError("HIL decision lease_seconds MUST be in [1, 300]")

    async def run_once(self) -> bool:
        """Redrive at most one durable decision under an exclusive lease."""
        claim = await self.store.claim_hil_decision_proposal(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if claim is None:
            return False
        try:
            receipt = receipt_from_outbox_payload(claim.payload)
        except ValueError:
            await self.store.mark_proposal_rejected(
                key=claim.key,
                claim_id=claim.claim_id,
                reason_code="malformed_hil_decision_outbox_record",
            )
            return False
        try:
            recorded = await self.registry.get_decision_by_approval_id(receipt.approval_id)
            if recorded is not None and not _same_decision_identity(recorded, receipt):
                await self.store.mark_proposal_rejected(
                    key=claim.key,
                    claim_id=claim.claim_id,
                    reason_code="conflicting_hil_decision_outbox_record",
                )
                return False
            authoritative = recorded or receipt
            if recorded is not None and recorded.delivered:
                return await self.store.mark_proposal_published(
                    key=claim.key,
                    claim_id=claim.claim_id,
                )
            await self.publisher.publish(
                self.topic,
                authoritative.approval_id,
                hil_decision_payload(authoritative),
            )
            await self.registry.mark_delivered(authoritative)
            published = await self.store.mark_proposal_published(
                key=claim.key,
                claim_id=claim.claim_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - transport or store failure remains retryable
            await self.store.release_proposal_claim(key=claim.key, claim_id=claim.claim_id)
            return False
        return published


def _same_decision_identity(
    recorded: HilDecisionReceipt,
    persisted: HilDecisionReceipt,
) -> bool:
    return (
        recorded.approval_id == persisted.approval_id
        and recorded.idempotency_key == persisted.idempotency_key
        and recorded.decision is persisted.decision
        and recorded.approver_oid.strip().casefold() == persisted.approver_oid.strip().casefold()
        and recorded.justification == persisted.justification
        and recorded.decided_at == persisted.decided_at
        and recorded.receipt_ref == persisted.receipt_ref
    )


class HilDecisionOutboxBridge:
    """Own the replay worker inside the Operator application lifecycle."""

    def __init__(
        self,
        *,
        store: HilDecisionOutboxStore,
        registry: HilDecisionDeliveryRegistry,
        publisher: HilDecisionPublisher,
        topic: str,
        retry_seconds: float = 1.0,
    ) -> None:
        if retry_seconds <= 0:
            raise ValueError("HIL decision retry_seconds MUST be positive")
        self._drainer = HilDecisionOutboxDrainer(
            store=store,
            registry=registry,
            publisher=publisher,
            topic=topic,
        )
        self._retry_seconds = retry_seconds
        self._task: asyncio.Task[None] | None = None

    def workers_ready(self) -> bool:
        """Report whether the replay worker remains active."""
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the single HIL decision replay worker once."""
        if self._task is None:
            self._task = asyncio.create_task(
                self._run(),
                name="operator-hil-decision-outbox",
            )

    async def aclose(self) -> None:
        """Cancel and join the HIL decision replay worker."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            try:
                published = await self._drainer.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - transient store failures retry in-process
                _LOGGER.warning("hil_decision_outbox_drainer_retrying", exc_info=True)
                published = False
            await asyncio.sleep(0 if published else self._retry_seconds)


def _text(value: Mapping[str, object], key: str) -> str:
    item = value[key]
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"HIL decision outbox field {key!r} is malformed")
    return item


__all__ = [
    "HIL_DECISION_ENQUEUE_OPERATION",
    "DurableHilDecisionOutboxPublisher",
    "HilDecisionDeliveryLedger",
    "HilDecisionDeliveryRegistry",
    "HilDecisionOutboxBridge",
    "HilDecisionOutboxClaim",
    "HilDecisionOutboxDrainer",
    "HilDecisionOutboxStore",
    "HilDecisionPublisher",
    "hil_decision_delivery_key",
    "hil_decision_payload",
    "outbox_payload",
    "receipt_from_outbox_payload",
]
