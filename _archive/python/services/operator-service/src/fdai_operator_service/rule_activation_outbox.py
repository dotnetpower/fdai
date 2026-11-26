"""Lease-fenced Rule activation notice delivery over the Operator transport."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from fdai_service_contracts.rule_activation_transport import RULE_ACTIVATION_REQUEST_TOPIC

from fdai_operator_service.rule_activation_notice import rule_activation_notice_from_record

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RuleActivationProposalClaim:
    key: str
    claim_id: str
    record: Mapping[str, Any]


class RuleActivationOutboxStore(Protocol):
    async def claim(self) -> RuleActivationProposalClaim | None: ...

    async def finish(
        self,
        claim: RuleActivationProposalClaim,
        *,
        rejected: bool = False,
    ) -> bool: ...

    async def release(self, claim: RuleActivationProposalClaim) -> None: ...


class RuleActivationNoticePublisher(Protocol):
    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> object: ...


@dataclass(frozen=True, slots=True)
class RuleActivationNoticeDrainer:
    store: RuleActivationOutboxStore
    publisher: RuleActivationNoticePublisher

    async def run_once(self) -> bool:
        claim = await self.store.claim()
        if claim is None:
            return False
        try:
            notice = rule_activation_notice_from_record(claim.key, claim.record)
        except (KeyError, TypeError, ValueError):
            await self.store.finish(claim, rejected=True)
            return False
        try:
            await self.publisher.publish(
                RULE_ACTIVATION_REQUEST_TOPIC,
                notice.request_id,
                notice.model_dump(mode="json"),
            )
        except Exception:  # noqa: BLE001 - immutable notices are safe to replay
            await self.store.release(claim)
            return False
        return await self.store.finish(claim)


class RuleActivationNoticeBridge:
    def __init__(self, drainer: RuleActivationNoticeDrainer, *, retry_seconds: float = 1.0) -> None:
        if not 0 < retry_seconds <= 60:
            raise ValueError("Rule activation retry interval MUST be in (0, 60]")
        self._drainer = drainer
        self._retry_seconds = retry_seconds
        self._task: asyncio.Task[None] | None = None
        self._healthy = False

    def workers_ready(self) -> bool:
        return self._task is not None and not self._task.done() and self._healthy

    async def start(self) -> None:
        if self._task is None:
            self._healthy = False
            self._task = asyncio.create_task(self._run(), name="operator-rule-activation-outbox")

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
            except Exception as exc:  # noqa: BLE001 - omit proposal content from diagnostics
                _LOGGER.warning(
                    "rule_activation_outbox_unavailable",
                    extra={"error_type": type(exc).__name__},
                )
                self._healthy = False
                sent = False
            await asyncio.sleep(0 if sent else self._retry_seconds)


__all__ = [
    "RuleActivationNoticeBridge",
    "RuleActivationNoticeDrainer",
    "RuleActivationNoticePublisher",
    "RuleActivationOutboxStore",
    "RuleActivationProposalClaim",
]
