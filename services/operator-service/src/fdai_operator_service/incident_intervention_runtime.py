"""Publish durable Incident intervention proposals through versioned transport."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai_service_contracts.incident_intervention import (
    INCIDENT_INTERVENTION_REQUEST_TOPIC,
    IncidentInterventionProposalBody,
    IncidentInterventionRequest,
    build_incident_intervention_request,
)
from fdai_service_contracts.operator import OperatorRole

from fdai_operator_service.postgres_family_store import (
    IncidentInterventionProposalClaim,
    PostgresFamilyStore,
)

_LOGGER = logging.getLogger(__name__)


class IncidentInterventionPublisher(Protocol):
    """Publish one versioned request after durable Operator acceptance."""

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class IncidentInterventionOutboxDrainer:
    """Lease and publish intervention requests with retry-safe CAS closure."""

    store: PostgresFamilyStore
    publisher: IncidentInterventionPublisher
    topic: str = INCIDENT_INTERVENTION_REQUEST_TOPIC
    worker_id: str = "operator-incident-intervention"
    lease_seconds: int = 120

    async def run_once(self) -> bool:
        """Publish at most one request and release only transient failures."""

        claim = await self.store.claim_incident_intervention_proposal(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if claim is None:
            return False
        try:
            request = request_from_claim(claim)
            await self.publisher.publish(
                self.topic,
                request.incident_id,
                request.model_dump(mode="json"),
            )
        except ValueError:
            await self.store.mark_proposal_rejected(
                key=claim.key,
                claim_id=claim.claim_id,
                reason_code="invalid_incident_intervention_request",
            )
            return False
        except Exception:  # noqa: BLE001 - transport failures remain retryable
            await self.store.release_proposal_claim(key=claim.key, claim_id=claim.claim_id)
            return False
        return await self.store.mark_proposal_published(
            key=claim.key,
            claim_id=claim.claim_id,
        )


class IncidentInterventionBridge:
    """Run the intervention outbox drainer with Operator lifecycle ownership."""

    def __init__(
        self,
        *,
        store: PostgresFamilyStore,
        publisher: IncidentInterventionPublisher,
        topic: str = INCIDENT_INTERVENTION_REQUEST_TOPIC,
        retry_seconds: float = 1.0,
    ) -> None:
        if not topic.strip():
            raise ValueError("incident intervention topic MUST be non-empty")
        if retry_seconds <= 0:
            raise ValueError("incident intervention retry_seconds MUST be positive")
        self._drainer = IncidentInterventionOutboxDrainer(store, publisher, topic)
        self._retry_seconds = retry_seconds
        self._task: asyncio.Task[None] | None = None

    def workers_ready(self) -> bool:
        """Report whether the configured drainer remains active."""

        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the single intervention outbox worker once."""

        if self._task is None:
            self._task = asyncio.create_task(
                self._run(),
                name="operator-incident-intervention-outbox",
            )

    async def aclose(self) -> None:
        """Cancel and join the intervention outbox worker."""

        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            try:
                published = await self._drainer.run_once()
            except Exception:  # noqa: BLE001 - transient store failures retry in-process
                _LOGGER.warning("incident_intervention_drainer_retrying", exc_info=True)
                published = False
            await asyncio.sleep(0 if published else self._retry_seconds)


def request_from_claim(
    claim: IncidentInterventionProposalClaim,
) -> IncidentInterventionRequest:
    """Convert one exact durable proposal to the no-authority wire contract."""

    if claim.payload.get("operation") != "incident.intervention":
        raise ValueError("incident intervention proposal operation is malformed")
    if claim.payload.get("principal_id") != claim.principal_id:
        raise ValueError("incident intervention proposal principal is malformed")
    if claim.payload.get("idempotency_key") != claim.idempotency_key:
        raise ValueError("incident intervention proposal idempotency is malformed")
    if claim.payload.get("correlation_id") != claim.correlation_id:
        raise ValueError("incident intervention proposal correlation is malformed")
    body_value = claim.payload.get("payload")
    if not isinstance(body_value, Mapping):
        raise ValueError("incident intervention proposal body is malformed")
    target_ref = body_value.get("target_ref")
    principal_roles = body_value.get("principal_roles")
    if not isinstance(target_ref, str):
        raise ValueError("incident intervention target is malformed")
    if not isinstance(principal_roles, list | tuple) or not all(
        isinstance(role, str) for role in principal_roles
    ):
        raise ValueError("incident intervention roles are malformed")
    body = IncidentInterventionProposalBody.model_validate(
        {
            key: value
            for key, value in body_value.items()
            if key not in {"target_ref", "principal_roles"}
        }
    )
    if body.correlation_id != claim.correlation_id:
        raise ValueError("incident intervention body correlation is malformed")
    requested_at = datetime.fromisoformat(claim.accepted_at.replace("Z", "+00:00"))
    return build_incident_intervention_request(
        request_id=claim.request_id,
        principal_id=claim.principal_id,
        principal_roles=tuple(OperatorRole(role) for role in principal_roles),
        idempotency_key=claim.idempotency_key,
        target_ref=target_ref,
        body=body,
        requested_at=requested_at,
    )


__all__ = [
    "IncidentInterventionBridge",
    "IncidentInterventionOutboxDrainer",
    "IncidentInterventionPublisher",
    "request_from_claim",
]
