"""Lease-fenced assignment notice delivery over the existing Operator transport."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from fdai_service_contracts.assignment_transport import ASSIGNMENT_REQUEST_TOPIC

from fdai_operator_service.assignment_notice import assignment_notice_from_record

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AssignmentProposalClaim:
    """One exclusive, bounded transport claim over an immutable source proposal."""

    key: str
    claim_id: str
    record: Mapping[str, Any]


class AssignmentOutboxStore(Protocol):
    """Lease and close only assignment proposals; never change assignment authority."""

    async def claim(self) -> AssignmentProposalClaim | None: ...

    async def finish(self, claim: AssignmentProposalClaim, *, rejected: bool = False) -> bool: ...

    async def release(self, claim: AssignmentProposalClaim) -> None: ...


class AssignmentNoticePublisher(Protocol):
    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> object: ...


@dataclass(frozen=True, slots=True)
class AssignmentNoticeDrainer:
    """Publish at most one immutable reference; at-least-once duplicates retain its identity."""

    store: AssignmentOutboxStore
    publisher: AssignmentNoticePublisher

    async def run_once(self) -> bool:
        claim = await self.store.claim()
        if claim is None:
            return False
        try:
            notice = assignment_notice_from_record(claim.record)
            if claim.key != notice.proposal_ref:
                raise ValueError("assignment claim key differs from source identity")
        except (KeyError, TypeError, ValueError):
            await self.store.finish(claim, rejected=True)
            return False
        try:
            await self.publisher.publish(
                ASSIGNMENT_REQUEST_TOPIC,
                notice.case_id,
                notice.model_dump(mode="json"),
            )
        except Exception:  # noqa: BLE001 - an inert notice may replay, never repeat an effect
            await self.store.release(claim)
            return False
        return await self.store.finish(claim)


class AssignmentNoticeBridge:
    """Own one restartable Operator outbox task with no provider or approval capability."""

    def __init__(self, drainer: AssignmentNoticeDrainer, *, retry_seconds: float = 1.0) -> None:
        if not 0 < retry_seconds <= 60:
            raise ValueError("assignment notice retry interval MUST be in (0, 60]")
        self._drainer = drainer
        self._retry_seconds = retry_seconds
        self._task: asyncio.Task[None] | None = None
        self._healthy = False

    def workers_ready(self) -> bool:
        return self._task is not None and not self._task.done() and self._healthy

    async def start(self) -> None:
        if self._task is None:
            self._healthy = False
            self._task = asyncio.create_task(self._run(), name="operator-assignment-outbox")

    async def aclose(self) -> None:
        task, self._task = self._task, None
        self._healthy = False
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            try:
                sent = await self._drainer.run_once()
                self._healthy = True
            except Exception as exc:  # noqa: BLE001 - preserve durable work, omit source content
                _LOGGER.warning(
                    "assignment_outbox_unavailable", extra={"error_type": type(exc).__name__}
                )
                self._healthy = False
                sent = False
            await asyncio.sleep(0 if sent else self._retry_seconds)


__all__ = [
    "AssignmentNoticeBridge",
    "AssignmentNoticeDrainer",
    "AssignmentOutboxStore",
    "AssignmentProposalClaim",
]
