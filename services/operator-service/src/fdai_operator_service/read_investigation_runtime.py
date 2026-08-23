"""Publish durable read-investigation proposals through versioned transport."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai_service_contracts.read_investigation import (
    READ_INVESTIGATION_REQUEST_TOPIC,
    ReadInvestigationCancellation,
    ReadInvestigationIntent,
    ReadInvestigationOrigin,
    ReadInvestigationProposalBody,
    ReadInvestigationRequest,
    ReadInvestigationSelector,
    build_read_investigation_cancellation,
    build_read_investigation_request,
    read_investigation_task_id,
)

from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    ReadInvestigationProposalClaim,
)

_LOGGER = logging.getLogger(__name__)


class ReadInvestigationPublisher(Protocol):
    """Publish one versioned request after durable Operator acceptance."""

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class ReadInvestigationOutboxDrainer:
    """Lease and publish read requests with retry-safe CAS closure."""

    store: PostgresFamilyStore
    publisher: ReadInvestigationPublisher
    topic: str = READ_INVESTIGATION_REQUEST_TOPIC
    worker_id: str = "operator-read-investigation"
    lease_seconds: int = 120

    async def run_once(self) -> bool:
        """Publish at most one request and release only transient failures."""

        claim = await self.store.claim_read_investigation_proposal(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if claim is None:
            return False
        try:
            request = request_from_claim(claim)
            partition_key = (
                request.task_id
                if isinstance(request, ReadInvestigationCancellation)
                else read_investigation_task_id(
                    request.owner_principal_id,
                    request.idempotency_key,
                )
            )
            await self.publisher.publish(
                self.topic,
                partition_key,
                request.model_dump(mode="json"),
            )
        except ValueError:
            await self.store.mark_proposal_rejected(
                key=claim.key,
                claim_id=claim.claim_id,
                reason_code="invalid_read_investigation_request",
            )
            return False
        except Exception:  # noqa: BLE001 - transport failures remain retryable
            await self.store.release_proposal_claim(key=claim.key, claim_id=claim.claim_id)
            return False
        return await self.store.mark_proposal_published(
            key=claim.key,
            claim_id=claim.claim_id,
        )


class ReadInvestigationBridge:
    """Run the read-request outbox drainer with Operator lifecycle ownership."""

    def __init__(
        self,
        *,
        store: PostgresFamilyStore,
        publisher: ReadInvestigationPublisher,
        topic: str = READ_INVESTIGATION_REQUEST_TOPIC,
        retry_seconds: float = 1.0,
    ) -> None:
        if not topic.strip():
            raise ValueError("read investigation topic MUST be non-empty")
        if retry_seconds <= 0:
            raise ValueError("read investigation retry_seconds MUST be positive")
        self._drainer = ReadInvestigationOutboxDrainer(store, publisher, topic)
        self._retry_seconds = retry_seconds
        self._task: asyncio.Task[None] | None = None

    def workers_ready(self) -> bool:
        """Report whether the configured drainer remains active."""

        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the single read-request outbox worker once."""

        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="operator-read-investigation-outbox")

    async def aclose(self) -> None:
        """Cancel and join the read-request outbox worker."""

        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            try:
                published = await self._drainer.run_once()
            except Exception:  # noqa: BLE001 - transient store failures retry in-process
                _LOGGER.warning("read_investigation_drainer_retrying", exc_info=True)
                published = False
            await asyncio.sleep(0 if published else self._retry_seconds)


def request_from_claim(
    claim: ReadInvestigationProposalClaim,
) -> ReadInvestigationRequest | ReadInvestigationCancellation:
    """Convert one exact durable proposal to the no-authority wire contract."""

    if claim.payload.get("operation") == "background.cancel":
        return _cancellation_from_claim(claim)
    if claim.payload.get("operation") != "read_investigation.start":
        raise ValueError("read investigation proposal operation is malformed")
    if claim.payload.get("principal_id") != claim.principal_id:
        raise ValueError("read investigation proposal principal is malformed")
    if claim.payload.get("idempotency_key") != claim.idempotency_key:
        raise ValueError("read investigation proposal idempotency is malformed")
    body = claim.payload.get("payload")
    if not isinstance(body, Mapping):
        raise ValueError("read investigation proposal body is malformed")
    proposal = ReadInvestigationProposalBody.model_validate(body)
    requested_at = datetime.fromisoformat(claim.accepted_at.replace("Z", "+00:00"))
    correlation_id = claim.correlation_id or claim.request_id
    return build_read_investigation_request(
        request_id=claim.request_id,
        owner_principal_id=claim.principal_id,
        idempotency_key=claim.idempotency_key,
        correlation_id=correlation_id,
        prompt=proposal.prompt,
        intent=ReadInvestigationIntent(proposal.intent),
        selector=ReadInvestigationSelector(
            name=proposal.resource_name,
            resource_type=proposal.resource_type,
            resource_group=proposal.resource_group,
        ),
        origin=ReadInvestigationOrigin(
            conversation_id=claim.request_id,
            channel_kind="web",
            channel_id=claim.principal_id,
        ),
        requested_at=requested_at,
        explicit_deep=proposal.explicit_deep,
    )


def _cancellation_from_claim(
    claim: ReadInvestigationProposalClaim,
) -> ReadInvestigationCancellation:
    if claim.payload.get("idempotency_key") != claim.idempotency_key:
        raise ValueError("read investigation cancellation idempotency is malformed")
    scope = claim.payload.get("scope")
    path_params = claim.payload.get("path_params")
    if not isinstance(scope, Mapping) or not isinstance(path_params, Mapping):
        raise ValueError("read investigation cancellation scope is malformed")
    if scope.get("subject_id") != claim.principal_id:
        raise ValueError("read investigation cancellation principal is malformed")
    roles = scope.get("roles")
    task_id = path_params.get("task_id")
    if not isinstance(roles, list | tuple) or not all(isinstance(role, str) for role in roles):
        raise ValueError("read investigation cancellation roles are malformed")
    if not isinstance(task_id, str):
        raise ValueError("read investigation cancellation task is malformed")
    requested_at = datetime.fromisoformat(claim.accepted_at.replace("Z", "+00:00"))
    return build_read_investigation_cancellation(
        request_id=claim.request_id,
        owner_principal_id=claim.principal_id,
        task_id=task_id,
        idempotency_key=claim.idempotency_key,
        requested_at=requested_at,
        admin_override="Owner" in roles,
    )


__all__ = [
    "ReadInvestigationBridge",
    "ReadInvestigationOutboxDrainer",
    "ReadInvestigationPublisher",
    "request_from_claim",
]
