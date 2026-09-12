"""ASGI application for the independent System Knowledge Service."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Protocol

import httpx
from azure.identity.aio import ClientSecretCredential, ManagedIdentityCredential
from azure.storage.blob.aio import ContainerClient
from fdai_service_contracts.venue import ExecutionVenue
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai_system_knowledge_service.blob_ledger import (
    AzureBlobContainerAdapter,
    AzureBlobMessageLedger,
)
from fdai_system_knowledge_service.catalog import load_catalog
from fdai_system_knowledge_service.config import (
    SystemKnowledgeSettings,
    TeamsOutgoingWebhookSettings,
    TeamsSettings,
    TeamsTransport,
)
from fdai_system_knowledge_service.ledger import DeliveryLedger, MessageLedger
from fdai_system_knowledge_service.runtime import (
    OutgoingWebhookKnowledgeRuntime,
    OutgoingWebhookTurnResult,
    SystemKnowledgeRuntime,
)
from fdai_system_knowledge_service.search import SystemKnowledgeIndex
from fdai_system_knowledge_service.teams import (
    AzureChannelTokenProvider,
    PyJwtServiceTokenVerifier,
    RemoteJwksProvider,
    TeamsIngressError,
    TeamsMentionVerifier,
    TeamsOutgoingWebhookVerifier,
    TeamsPublisher,
    TeamsPublishError,
)

_MAX_BODY_BYTES = 256_000


class KnowledgeHttpRuntime(Protocol):
    """Route-safe lifecycle and activity surface."""

    @property
    def transport(self) -> TeamsTransport: ...

    @property
    def ready(self) -> bool: ...

    async def start(self) -> None: ...

    async def aclose(self) -> None: ...

    async def handle(
        self,
        *,
        body: bytes,
        authorization: str,
        received_at: datetime,
    ) -> object: ...


class _ComposedRuntime:
    """Close the knowledge runtime and its service-owned HTTP client together."""

    def __init__(
        self,
        *,
        runtime: SystemKnowledgeRuntime,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._runtime = runtime
        self._http_client = http_client

    @property
    def transport(self) -> TeamsTransport:
        return self._runtime.transport

    @property
    def ready(self) -> bool:
        return self._runtime.ready

    async def start(self) -> None:
        try:
            await self._runtime.start()
        except BaseException:
            await self.aclose()
            raise

    async def aclose(self) -> None:
        try:
            await self._runtime.aclose()
        finally:
            await self._http_client.aclose()

    async def handle(
        self,
        *,
        body: bytes,
        authorization: str,
        received_at: datetime,
    ) -> object:
        return await self._runtime.handle(
            body=body,
            authorization=authorization,
            received_at=received_at,
        )


def create_runtime(settings: SystemKnowledgeSettings) -> KnowledgeHttpRuntime:
    """Compose service-owned catalog, Teams trust, durable claims, and publisher."""

    catalog = load_catalog(
        settings.catalog_path,
        expected_source_revision=settings.expected_source_revision,
    )
    if settings.execution_venue is ExecutionVenue.LOCAL:
        ledger: DeliveryLedger = MessageLedger(settings.ledger_path)
    else:
        if settings.claim_container_url is None:
            raise RuntimeError("validated deployed claim container is unavailable")
        blob_credential = ManagedIdentityCredential(client_id=settings.managed_identity_client_id)
        ledger = AzureBlobMessageLedger(
            container=AzureBlobContainerAdapter(
                ContainerClient.from_container_url(
                    settings.claim_container_url,
                    credential=blob_credential,
                )
            ),
            credential=blob_credential,
        )
    if isinstance(settings.teams, TeamsOutgoingWebhookSettings):
        return OutgoingWebhookKnowledgeRuntime(
            ingress=TeamsOutgoingWebhookVerifier(settings=settings.teams),
            index=SystemKnowledgeIndex(catalog),
            ledger=ledger,
        )
    if not isinstance(settings.teams, TeamsSettings):
        raise RuntimeError("validated Teams transport settings are unavailable")
    bot_settings = settings.teams
    http_client = httpx.AsyncClient(
        trust_env=False,
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
    )
    jwks = RemoteJwksProvider(url=bot_settings.jwks_url, http_client=http_client)
    teams_credential = (
        ClientSecretCredential(
            tenant_id=bot_settings.tenant_id,
            client_id=bot_settings.application_id,
            client_secret=bot_settings.client_secret or "",
        )
        if settings.execution_venue is ExecutionVenue.LOCAL
        else ManagedIdentityCredential(client_id=settings.managed_identity_client_id)
    )
    token_provider = AzureChannelTokenProvider(teams_credential)
    publisher = TeamsPublisher(http_client=http_client, tokens=token_provider)
    runtime = SystemKnowledgeRuntime(
        ingress=TeamsMentionVerifier(
            settings=bot_settings,
            tokens=PyJwtServiceTokenVerifier(
                application_id=bot_settings.application_id,
                jwks=jwks,
            ),
        ),
        index=SystemKnowledgeIndex(catalog),
        ledger=ledger,
        publisher=publisher,
    )
    return _ComposedRuntime(runtime=runtime, http_client=http_client)


def create_app(
    environ: Mapping[str, str] | None = None,
    *,
    runtime: KnowledgeHttpRuntime | None = None,
) -> Starlette:
    """Build the standalone health and Teams activity application."""

    selected = runtime or create_runtime(
        SystemKnowledgeSettings.parse(os.environ if environ is None else environ)
    )

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        await selected.start()
        try:
            yield
        finally:
            await selected.aclose()

    async def live(_request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def ready(_request: Request) -> Response:
        return JSONResponse(
            {"status": "ok" if selected.ready else "unavailable"},
            status_code=200 if selected.ready else 503,
        )

    async def teams(request: Request) -> Response:
        if selected.transport is not TeamsTransport.BOT_FRAMEWORK:
            return JSONResponse({"error": {"code": "transport_disabled"}}, status_code=404)
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            return JSONResponse({"error": {"code": "unsupported_media_type"}}, status_code=415)
        body = await _bounded_request_body(request)
        if body is None:
            return JSONResponse({"error": {"code": "body_too_large"}}, status_code=413)
        authorization = request.headers.get("authorization", "")
        try:
            result = await selected.handle(
                body=body,
                authorization=authorization,
                received_at=datetime.now(UTC),
            )
        except TeamsIngressError as exc:
            return JSONResponse({"error": {"code": exc.code}}, status_code=exc.http_status)
        except TeamsPublishError as exc:
            return JSONResponse({"error": {"code": exc.code}}, status_code=503)
        state = getattr(result, "state", "accepted")
        return JSONResponse({"status": state}, status_code=202)

    async def outgoing_webhook(request: Request) -> Response:
        if selected.transport is not TeamsTransport.OUTGOING_WEBHOOK:
            return JSONResponse({"error": {"code": "transport_disabled"}}, status_code=404)
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            return JSONResponse({"error": {"code": "unsupported_media_type"}}, status_code=415)
        body = await _bounded_request_body(request)
        if body is None:
            return JSONResponse({"error": {"code": "body_too_large"}}, status_code=413)
        try:
            async with asyncio.timeout(4.0):
                result = await selected.handle(
                    body=body,
                    authorization=request.headers.get("authorization", ""),
                    received_at=datetime.now(UTC),
                )
        except TimeoutError:
            return JSONResponse(
                {"error": {"code": "outgoing_webhook_deadline_exceeded"}},
                status_code=503,
            )
        except TeamsIngressError as exc:
            return JSONResponse({"error": {"code": exc.code}}, status_code=exc.http_status)
        if not isinstance(result, OutgoingWebhookTurnResult):
            raise RuntimeError("Outgoing Webhook runtime returned an invalid result")
        return JSONResponse(result.payload, status_code=200)

    return Starlette(
        routes=[
            Route("/health/live", live, methods=["GET"]),
            Route("/health/ready", ready, methods=["GET"]),
            Route("/api/teams/messages", teams, methods=["POST"]),
            Route(
                "/api/teams/outgoing-webhook",
                outgoing_webhook,
                methods=["POST"],
            ),
        ],
        lifespan=lifespan,
    )


async def _bounded_request_body(request: Request) -> bytes | None:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_BODY_BYTES:
            return None
    return bytes(body)


__all__ = ["KnowledgeHttpRuntime", "create_app", "create_runtime"]
