"""Coordinate verified Teams mentions, knowledge retrieval, and durable replies."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from fdai_service_contracts.system_knowledge import SystemKnowledgeQueryRequest

from fdai_system_knowledge_service.config import TeamsTransport
from fdai_system_knowledge_service.ledger import DeliveryLedger
from fdai_system_knowledge_service.render import outgoing_webhook_payload, teams_payload
from fdai_system_knowledge_service.search import SystemKnowledgeIndex
from fdai_system_knowledge_service.teams import (
    TeamsMentionVerifier,
    TeamsOutgoingWebhookVerifier,
    TeamsPublisher,
    TeamsPublishError,
)


@dataclass(frozen=True, slots=True)
class KnowledgeTurnResult:
    """One content-free terminal state returned to the HTTP route."""

    state: str
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class OutgoingWebhookTurnResult:
    """One synchronous response returned directly to Teams."""

    state: str
    payload: dict[str, object]
    duplicate: bool = False


class SystemKnowledgeRuntime:
    """Own one mention through catalog verification and provider acknowledgement."""

    def __init__(
        self,
        *,
        ingress: TeamsMentionVerifier,
        index: SystemKnowledgeIndex,
        ledger: DeliveryLedger,
        publisher: TeamsPublisher,
    ) -> None:
        self._ingress = ingress
        self._index = index
        self._ledger = ledger
        self._publisher = publisher
        self._ready = False

    @property
    def transport(self) -> TeamsTransport:
        """Return the Bot Framework transport owned by this runtime."""

        return TeamsTransport.BOT_FRAMEWORK

    @property
    def ready(self) -> bool:
        """Return whether trust roots, catalog, and claims are ready."""

        return self._ready

    async def start(self) -> None:
        """Reconcile durable sends and warm Teams trust before opening readiness."""

        await self._ledger.start()
        await self._ingress.warm()
        self._ready = True

    async def aclose(self) -> None:
        """Close the outbound identity exactly once."""

        self._ready = False
        first_error: BaseException | None = None
        try:
            await self._publisher.aclose()
        except BaseException as exc:
            first_error = exc
        try:
            await self._ledger.aclose()
        except BaseException as exc:
            if first_error is None:
                first_error = exc
        if first_error is not None:
            raise first_error

    async def handle(
        self,
        *,
        body: bytes,
        authorization: str,
        received_at: datetime,
    ) -> KnowledgeTurnResult:
        """Process one activity without retrying ambiguous provider sends."""

        turn = await self._ingress.parse(
            body=body,
            authorization=authorization,
            received_at=received_at,
        )
        if turn is None:
            return KnowledgeTurnResult(state="ignored")
        if not await self._ledger.claim(turn.message_key):
            return KnowledgeTurnResult(state="duplicate", duplicate=True)
        try:
            query = turn.query or (
                "FDAI 시스템 지식 봇은 어떻게 동작하나요?"
                if turn.locale == "ko"
                else "How does the FDAI system knowledge bot work?"
            )
            response = self._index.search(
                SystemKnowledgeQueryRequest(
                    query=query,
                    locale=turn.locale,
                    principal_scope_digest=turn.principal_scope_digest,
                )
            )
            payload = teams_payload(
                response,
                locale=turn.locale,
                reply_to_id=turn.message_id,
            )
            response_digest = (
                "sha256:"
                + hashlib.sha256(
                    json.dumps(
                        payload,
                        allow_nan=False,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8")
                ).hexdigest()
            )
            await self._ledger.mark_sending(turn.message_key, response_digest)
            activity_id = await self._publisher.send(
                conversation_id=turn.conversation_id,
                service_url=turn.service_url,
                payload=payload,
            )
        except TeamsPublishError as exc:
            if exc.ambiguous:
                await self._ledger.mark_ambiguous(turn.message_key)
                return KnowledgeTurnResult(state="ambiguous")
            await self._ledger.release_retryable(turn.message_key)
            raise
        except (TypeError, ValueError):
            await self._ledger.release_retryable(turn.message_key)
            raise
        await self._ledger.mark_delivered(turn.message_key, activity_id)
        return KnowledgeTurnResult(state="delivered")


class OutgoingWebhookKnowledgeRuntime:
    """Answer one authenticated Outgoing Webhook request without provider I/O."""

    def __init__(
        self,
        *,
        ingress: TeamsOutgoingWebhookVerifier,
        index: SystemKnowledgeIndex,
        ledger: DeliveryLedger,
    ) -> None:
        self._ingress = ingress
        self._index = index
        self._ledger = ledger
        self._ready = False

    @property
    def transport(self) -> TeamsTransport:
        """Return the Outgoing Webhook transport owned by this runtime."""

        return TeamsTransport.OUTGOING_WEBHOOK

    @property
    def ready(self) -> bool:
        """Return whether the catalog and claim store are ready."""

        return self._ready

    async def start(self) -> None:
        """Reconcile durable claims before opening readiness."""

        await self._ledger.start()
        await self._ingress.warm()
        self._ready = True

    async def aclose(self) -> None:
        """Close the claim store exactly once."""

        self._ready = False
        await self._ledger.aclose()

    async def handle(
        self,
        *,
        body: bytes,
        authorization: str,
        received_at: datetime,
    ) -> OutgoingWebhookTurnResult:
        """Return a deterministic synchronous response for one signed mention."""

        turn = await self._ingress.parse(
            body=body,
            authorization=authorization,
            received_at=received_at,
        )
        if turn is None:
            raise RuntimeError("verified Outgoing Webhook mention is unavailable")
        query = turn.query or (
            "FDAI 시스템 지식 봇은 어떻게 동작하나요?"
            if turn.locale == "ko"
            else "How does the FDAI system knowledge bot work?"
        )
        response = self._index.search(
            SystemKnowledgeQueryRequest(
                query=query,
                locale=turn.locale,
                principal_scope_digest=turn.principal_scope_digest,
            )
        )
        payload = outgoing_webhook_payload(response, locale=turn.locale)
        if not await self._ledger.claim(turn.message_key):
            return OutgoingWebhookTurnResult(
                state="duplicate",
                payload=payload,
                duplicate=True,
            )
        response_digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    payload,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
        )
        try:
            await self._ledger.mark_sending(turn.message_key, response_digest)
            await self._ledger.mark_delivered(
                turn.message_key,
                f"outgoing-webhook:{turn.message_id}",
            )
        except (TypeError, ValueError):
            await self._ledger.release_retryable(turn.message_key)
            raise
        return OutgoingWebhookTurnResult(state="responded", payload=payload)


__all__ = [
    "KnowledgeTurnResult",
    "OutgoingWebhookKnowledgeRuntime",
    "OutgoingWebhookTurnResult",
    "SystemKnowledgeRuntime",
]
