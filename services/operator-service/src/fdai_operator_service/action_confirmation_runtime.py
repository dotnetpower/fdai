"""Durable action-confirmation publication into the governed Core ingress."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from fdai_service_contracts.action_intent import ActionIntentSource, OntologyActionIntent

from fdai_operator_service.postgres_family_store import PostgresFamilyStore

_LOGGER = logging.getLogger(__name__)


class ActionEventPublisher(Protocol):
    """Publish one canonical mapping after durable action acceptance."""

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class ActionConfirmationOutboxDrainer:
    """Lease and publish action confirmations with retry-safe CAS closure."""

    store: PostgresFamilyStore
    publisher: ActionEventPublisher
    topic: str
    worker_id: str = "operator-action-confirmation"
    lease_seconds: int = 120

    async def run_once(self) -> bool:
        """Publish at most one confirmation and release any failed attempt."""
        claim = await self.store.claim_action_proposal(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if claim is None:
            return False
        try:
            body = claim.payload.get("body")
            if not isinstance(body, Mapping):
                raise ValueError("action confirmation body is malformed")
            request_id = body.get("request_id")
            projection_id = body.get("projection_id")
            if not isinstance(request_id, str) or not isinstance(projection_id, str):
                raise ValueError("action confirmation source identity is malformed")
            source = await self.store.read_semantic_action_draft_source(
                principal_id=claim.principal_id,
                request_id=request_id,
                projection_id=projection_id,
            )
            if source is None:
                raise ValueError("action confirmation source is unavailable")
            event = _action_event(
                claim.payload,
                principal_id=claim.principal_id,
                source_projection=source,
            )
            await self.publisher.publish(self.topic, str(event["idempotency_key"]), event)
        except ValueError:
            await self.store.mark_action_proposal_rejected(
                key=claim.key,
                claim_id=claim.claim_id,
                reason_code="invalid_semantic_action_source",
            )
            return False
        except Exception:  # noqa: BLE001 - transient store or transport failure remains retryable
            await self.store.release_action_proposal_claim(
                key=claim.key,
                claim_id=claim.claim_id,
            )
            return False
        return await self.store.mark_action_proposal_published(
            key=claim.key,
            claim_id=claim.claim_id,
        )


class ActionConfirmationBridge:
    """Run the durable action-confirmation drainer with application lifecycle ownership."""

    def __init__(
        self,
        *,
        store: PostgresFamilyStore,
        publisher: ActionEventPublisher,
        topic: str,
        retry_seconds: float = 1.0,
    ) -> None:
        if not topic.strip():
            raise ValueError("action event topic MUST be non-empty")
        if retry_seconds <= 0:
            raise ValueError("action retry_seconds MUST be positive")
        self._drainer = ActionConfirmationOutboxDrainer(store, publisher, topic)
        self._retry_seconds = retry_seconds
        self._task: asyncio.Task[None] | None = None

    def workers_ready(self) -> bool:
        """Report whether the configured drainer remains active."""
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the single action outbox worker once."""
        if self._task is None:
            self._task = asyncio.create_task(
                self._run(),
                name="operator-action-outbox",
            )

    async def aclose(self) -> None:
        """Cancel and join the action outbox worker."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            try:
                published = await self._drainer.run_once()
            except Exception:  # noqa: BLE001 - transient store failures retry in-process
                _LOGGER.warning("action_confirmation_drainer_retrying", exc_info=True)
                published = False
            await asyncio.sleep(0 if published else self._retry_seconds)


def validate_action_confirmation_source(
    body: Mapping[str, object],
    source_projection: Mapping[str, object],
    *,
    principal_id: str,
) -> OntologyActionIntent:
    """Require one exact durable action draft owned by the authenticated principal."""
    intent = OntologyActionIntent.model_validate(body.get("ontology_intent"))
    request_id = body.get("request_id")
    projection_id = body.get("projection_id")
    idempotency_key = body.get("idempotency_key")
    session_id = body.get("session_id")
    semantic_result = source_projection.get("semantic_result")
    if not isinstance(semantic_result, Mapping):
        raise ValueError("semantic action draft source is malformed")
    source_intent = OntologyActionIntent.model_validate(semantic_result.get("action_intent"))
    if (
        intent.actor_ref != f"operator:{principal_id}"
        or source_intent != intent
        or source_projection.get("request_id") != request_id
        or source_projection.get("projection_id") != projection_id
        or source_projection.get("idempotency_key") != idempotency_key
        or source_projection.get("status") != "action_draft"
        or semantic_result.get("disposition") != "action_draft"
        or semantic_result.get("session_id") != session_id
    ):
        raise ValueError("action confirmation does not match its durable semantic source")
    return intent


def _action_event(
    payload: Mapping[str, object],
    *,
    principal_id: str,
    source_projection: Mapping[str, object],
) -> dict[str, object]:
    body = payload.get("body")
    if not isinstance(body, Mapping):
        raise ValueError("action confirmation body is malformed")
    intent = validate_action_confirmation_source(
        body,
        source_projection,
        principal_id=principal_id,
    )
    action_type = body.get("action_type")
    arguments = body.get("arguments")
    session_id = body.get("session_id")
    idempotency_key = payload.get("idempotency_key")
    resource_ref = intent.target_selector.get("resource_ref")
    if (
        intent.source is not ActionIntentSource.OPERATOR_LANGUAGE
        or intent.actor_ref != f"operator:{principal_id}"
        or action_type != intent.action_type_name
        or arguments != intent.arguments
        or intent.target_selector != {"resource_ref": resource_ref}
        or not isinstance(session_id, str)
        or not session_id.strip()
        or not isinstance(idempotency_key, str)
        or not idempotency_key.strip()
        or idempotency_key != body.get("idempotency_key")
        or not isinstance(resource_ref, str)
        or not resource_ref.strip()
    ):
        raise ValueError("action confirmation does not match its exact intent")
    return {
        "idempotency_key": idempotency_key,
        "correlation_id": session_id,
        "initiator_principal": principal_id,
        "operator_initiated": True,
        "action_type": intent.action_type_name,
        "resource_id": resource_ref,
        "event_type": "operator_request",
        "params": intent.arguments,
        "ontology_intent": intent.model_dump(mode="json"),
    }


__all__ = [
    "ActionConfirmationBridge",
    "ActionConfirmationOutboxDrainer",
    "ActionEventPublisher",
    "validate_action_confirmation_source",
]
