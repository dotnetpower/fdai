"""Durable requester-contact command delivery over the existing HIL topic."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from fdai_operator_service.families.iam.contracts import (
    ReportLineContactContext,
    ReportLineContactOutbox,
)
from fdai_service_contracts import ReportLineContactCommand

_LOGGER = logging.getLogger(__name__)
REPORT_LINE_CONTACT_ENQUEUE_OPERATION = "hil.report-line-contact.enqueue"


class ReportLineContactPublisher(Protocol):
    """Publish one typed contact command after its durable write."""

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object: ...


class ReportLineContactDeliveryLedger(Protocol):
    """Close a durable contact command after broker acceptance."""

    async def mark_report_line_contact_published(self, idempotency_key: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class DurableReportLineContactPublisher:
    """Persist first, then publish one contact command to the shared HIL transport."""

    durable: ReportLineContactOutbox
    publisher: ReportLineContactPublisher
    topic: str
    ledger: ReportLineContactDeliveryLedger | None = None

    def __post_init__(self) -> None:
        if not self.topic.strip():
            raise ValueError("report-line contact topic MUST be non-empty")

    async def get_report_line_contact_context(
        self,
        approval_id: str,
    ) -> ReportLineContactContext | None:
        return await self.durable.get_report_line_contact_context(approval_id)

    async def list_report_line_contact_contexts(
        self,
        *,
        requester_ref: str,
        limit: int,
    ) -> tuple[ReportLineContactContext, ...]:
        return await self.durable.list_report_line_contact_contexts(
            requester_ref=requester_ref,
            limit=limit,
        )

    async def enqueue_report_line_contact(
        self,
        command: ReportLineContactCommand,
    ) -> None:
        await self.durable.enqueue_report_line_contact(command)
        await self.publisher.publish(
            self.topic,
            command.approval_id,
            command.model_dump(mode="json"),
        )
        if self.ledger is not None:
            await self.ledger.mark_report_line_contact_published(command.idempotency_key)


class ReportLineContactClaim(Protocol):
    """One leased contact command proposal."""

    @property
    def key(self) -> str: ...

    @property
    def claim_id(self) -> str: ...

    @property
    def payload(self) -> Mapping[str, object]: ...


class ReportLineContactOutboxStore(Protocol):
    """Lease and close only report-line contact proposals."""

    async def claim_report_line_contact_proposal(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> ReportLineContactClaim | None: ...

    async def mark_proposal_published(self, *, key: str, claim_id: str) -> bool: ...

    async def mark_proposal_rejected(
        self,
        *,
        key: str,
        claim_id: str,
        reason_code: str,
    ) -> bool: ...

    async def release_proposal_claim(self, *, key: str, claim_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class ReportLineContactOutboxDrainer:
    """Replay one durable contact command under an exclusive lease."""

    store: ReportLineContactOutboxStore
    publisher: ReportLineContactPublisher
    topic: str
    worker_id: str = "operator-report-line-contact-outbox"
    lease_seconds: int = 60

    async def run_once(self) -> bool:
        claim = await self.store.claim_report_line_contact_proposal(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if claim is None:
            return False
        try:
            command = ReportLineContactCommand.model_validate(claim.payload)
        except ValueError:
            await self.store.mark_proposal_rejected(
                key=claim.key,
                claim_id=claim.claim_id,
                reason_code="malformed_report_line_contact_outbox_record",
            )
            return False
        try:
            await self.publisher.publish(
                self.topic,
                command.approval_id,
                command.model_dump(mode="json"),
            )
            return await self.store.mark_proposal_published(
                key=claim.key,
                claim_id=claim.claim_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - durable proposal remains retryable
            await self.store.release_proposal_claim(
                key=claim.key,
                claim_id=claim.claim_id,
            )
            return False


__all__ = [
    "REPORT_LINE_CONTACT_ENQUEUE_OPERATION",
    "DurableReportLineContactPublisher",
    "ReportLineContactDeliveryLedger",
    "ReportLineContactOutboxDrainer",
    "ReportLineContactOutboxStore",
    "ReportLineContactPublisher",
]
