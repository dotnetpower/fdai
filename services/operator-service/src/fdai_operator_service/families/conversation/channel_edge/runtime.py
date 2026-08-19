"""Run the standalone fail-closed Operator channel-edge ASGI workload."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Protocol

from fdai_operator_service.families.conversation.channel_delivery_models import ChannelKind
from fdai_operator_service.families.conversation.channel_edge.models import (
    AuthenticatedInboundTurn,
)
from fdai_operator_service.families.conversation.channel_edge.pipeline import (
    ChannelDeliveryPipeline,
)
from fdai_operator_service.families.conversation.channel_edge.queues import (
    SlackIngressQueue,
    TeamsIngressQueue,
)
from fdai_operator_service.families.conversation.channel_edge.slack_ingress import (
    SlackIngressAction,
    SlackIngressError,
)
from fdai_operator_service.families.conversation.channel_edge.teams_ingress import (
    TeamsIngressError,
)
from fdai_operator_service.families.conversation.channel_edge.worker import (
    ChannelDeliveryWorker,
)
from fdai_operator_service.routes import SecurityHeadersMiddleware
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

ReadinessCheck = Callable[[], Awaitable[bool]]
StartupCheck = Callable[[], Awaitable[None]]


class ApplicationLifecycle(Protocol):
    """Start and close one process-owned dependency."""

    async def start(self) -> None: ...

    async def aclose(self) -> None: ...


class SemanticBridgeLifecycle(ApplicationLifecycle, Protocol):
    """Expose whether semantic publisher and result consumers remain supervised."""

    def workers_ready(self) -> bool: ...


class AsyncResource(Protocol):
    """Close one process-owned HTTP client or credential."""

    async def aclose(self) -> None: ...


class ChannelEdgeHttpRuntime(Protocol):
    """Expose only route-safe edge admission and readiness behavior."""

    max_body_bytes: int
    enabled_channels: frozenset[ChannelKind]

    @property
    def ready(self) -> bool: ...

    async def start(self) -> None: ...

    async def aclose(self) -> None: ...

    def accept_slack(
        self,
        *,
        body: bytes,
        headers: Mapping[str, str],
        received_at: datetime,
    ) -> tuple[SlackIngressAction, str | None]: ...

    async def accept_teams(
        self,
        *,
        body: bytes,
        authorization: str,
        received_at: datetime,
    ) -> None: ...


class ChannelEdgeRuntime:
    """Supervise channel ingress only after every trust and durability check passes."""

    def __init__(
        self,
        *,
        enabled_channels: frozenset[ChannelKind],
        pipeline: ChannelDeliveryPipeline,
        worker: ChannelDeliveryWorker,
        semantic_transport: ApplicationLifecycle,
        semantic_bridge: SemanticBridgeLifecycle,
        slack_queue: SlackIngressQueue | None = None,
        teams_queue: TeamsIngressQueue | None = None,
        readiness_checks: Sequence[ReadinessCheck] = (),
        startup_checks: Sequence[StartupCheck] = (),
        resources: Sequence[AsyncResource] = (),
        max_body_bytes: int = 256_000,
        shutdown_grace_seconds: float = 5.0,
    ) -> None:
        if enabled_channels != {
            channel
            for channel, queue in (
                (ChannelKind.SLACK, slack_queue),
                (ChannelKind.TEAMS, teams_queue),
            )
            if queue is not None
        }:
            raise ValueError("enabled channels MUST exactly match configured ingress queues")
        if max_body_bytes < 1 or shutdown_grace_seconds <= 0:
            raise ValueError("channel edge body or shutdown limit is invalid")
        self.max_body_bytes = max_body_bytes
        self.enabled_channels = enabled_channels
        self._pipeline = pipeline
        self._worker = worker
        self._semantic_transport = semantic_transport
        self._semantic_bridge = semantic_bridge
        self._slack_queue = slack_queue
        self._teams_queue = teams_queue
        self._readiness_checks = tuple(readiness_checks)
        self._startup_checks = tuple(startup_checks)
        self._resources = tuple(resources)
        self._shutdown_grace_seconds = shutdown_grace_seconds
        self._consumer_tasks: tuple[asyncio.Task[None], ...] = ()
        self._started = False
        self._closed = False

    @property
    def ready(self) -> bool:
        """Report false when any semantic, delivery, or queue consumer task stops."""
        return (
            self._started
            and self._worker.ready
            and self._semantic_bridge.workers_ready()
            and len(self._consumer_tasks) == len(self.enabled_channels)
            and all(not task.done() for task in self._consumer_tasks)
        )

    async def start(self) -> None:
        """Resolve transport, trust roots, stores, recovery, then queue consumers in order."""
        if self._closed:
            raise RuntimeError("closed channel edge runtime cannot restart")
        if self._started:
            return
        try:
            await self._semantic_transport.start()
            await self._semantic_bridge.start()
            for check in self._startup_checks:
                await check()
            for probe in self._readiness_checks:
                if not await probe():
                    raise RuntimeError("channel edge required dependency is unavailable")
            await self._worker.start()
            consumers: list[asyncio.Task[None]] = []
            if self._slack_queue is not None:
                consumers.append(
                    asyncio.create_task(
                        self._consume(self._slack_queue.receive()),
                        name="operator-channel-edge-slack",
                    )
                )
            if self._teams_queue is not None:
                consumers.append(
                    asyncio.create_task(
                        self._consume(self._teams_queue.receive()),
                        name="operator-channel-edge-teams",
                    )
                )
            self._consumer_tasks = tuple(consumers)
            self._started = True
            await asyncio.sleep(0)
            if not self.ready:
                raise RuntimeError("channel edge workers did not become ready")
        except BaseException:
            await self.aclose()
            raise

    async def aclose(self) -> None:
        """Close admission, bound queue drain, workers, semantic transport, and resources."""
        if self._closed:
            return
        self._closed = True
        self._started = False
        first_error: BaseException | None = None

        async def close(awaitable: Awaitable[None]) -> None:
            nonlocal first_error
            try:
                await awaitable
            except BaseException as exc:
                if first_error is None:
                    first_error = exc

        if self._slack_queue is not None:
            await close(self._slack_queue.close())
        if self._teams_queue is not None:
            await close(self._teams_queue.close())
        tasks, self._consumer_tasks = self._consumer_tasks, ()
        if tasks:
            try:
                done, pending = await asyncio.wait(tasks, timeout=self._shutdown_grace_seconds)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*done, *pending, return_exceptions=True)
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        await close(self._worker.close())
        await close(self._semantic_bridge.aclose())
        await close(self._semantic_transport.aclose())
        for resource in reversed(self._resources):
            await close(resource.aclose())
        if first_error is not None:
            raise first_error

    def accept_slack(
        self,
        *,
        body: bytes,
        headers: Mapping[str, str],
        received_at: datetime,
    ) -> tuple[SlackIngressAction, str | None]:
        """Admit one Slack request only while every supervised dependency is ready."""
        if not self.ready or self._slack_queue is None:
            raise SlackIngressError(
                "Slack channel edge is unavailable",
                code="unavailable",
                http_status=503,
            )
        result = self._slack_queue.accept(
            body=body,
            headers=headers,
            received_at=received_at,
        )
        return result.action, result.challenge

    async def accept_teams(
        self,
        *,
        body: bytes,
        authorization: str,
        received_at: datetime,
    ) -> None:
        """Admit one Teams request only while every supervised dependency is ready."""
        if not self.ready or self._teams_queue is None:
            raise TeamsIngressError(
                "Teams channel edge is unavailable",
                code="unavailable",
                http_status=503,
            )
        await self._teams_queue.accept(
            body=body,
            authorization=authorization,
            received_at=received_at,
        )

    async def _consume(self, turns: AsyncIterator[AuthenticatedInboundTurn]) -> None:
        async for turn in turns:
            await self._pipeline.process(turn)


def create_channel_edge_app(runtime: ChannelEdgeHttpRuntime) -> Starlette:
    """Create the public webhook app without Operator API or execution routes."""

    async def live(_: Request) -> Response:
        return JSONResponse({"status": "live"})

    async def ready(_: Request) -> Response:
        status = 200 if runtime.ready else 503
        return JSONResponse(
            {"status": "ready" if runtime.ready else "unavailable"}, status_code=status
        )

    async def slack(request: Request) -> Response:
        _require_json(request)
        body = await _bounded_request_body(request, maximum=runtime.max_body_bytes)
        action, challenge = runtime.accept_slack(
            body=body,
            headers=request.headers,
            received_at=datetime.now(UTC),
        )
        if action is SlackIngressAction.CHALLENGE:
            return JSONResponse({"challenge": challenge})
        return JSONResponse({"accepted": action is SlackIngressAction.ACCEPTED}, status_code=202)

    async def teams(request: Request) -> Response:
        _require_json(request)
        authorization = request.headers.get("authorization", "")
        if len(authorization) > 16_384:
            raise TeamsIngressError(
                "Teams authorization header exceeds the limit",
                code="authentication_too_large",
                http_status=401,
            )
        body = await _bounded_request_body(request, maximum=runtime.max_body_bytes)
        await runtime.accept_teams(
            body=body,
            authorization=authorization,
            received_at=datetime.now(UTC),
        )
        return JSONResponse({"accepted": True}, status_code=202)

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        await runtime.start()
        try:
            yield
        finally:
            await runtime.aclose()

    routes = [
        Route("/health/live", live, methods=["GET"]),
        Route("/health/ready", ready, methods=["GET"]),
    ]
    if ChannelKind.SLACK in runtime.enabled_channels:
        routes.append(Route("/webhooks/slack/events", slack, methods=["POST"]))
    if ChannelKind.TEAMS in runtime.enabled_channels:
        routes.append(Route("/webhooks/teams/activities", teams, methods=["POST"]))
    return Starlette(
        routes=routes,
        middleware=[Middleware(SecurityHeadersMiddleware)],
        lifespan=lifespan,
        exception_handlers={
            SlackIngressError: _channel_error,
            TeamsIngressError: _channel_error,
            _UnsupportedMediaTypeError: _unsupported_media_type,
            _BodyTooLargeError: _body_too_large,
        },
    )


class _UnsupportedMediaTypeError(ValueError):
    pass


class _BodyTooLargeError(ValueError):
    pass


def _require_json(request: Request) -> None:
    content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if content_type != "application/json":
        raise _UnsupportedMediaTypeError


async def _bounded_request_body(request: Request, *, maximum: int) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > maximum:
            raise _BodyTooLargeError
    return bytes(body)


async def _channel_error(_: Request, exc: Exception) -> Response:
    status = exc.http_status if isinstance(exc, SlackIngressError | TeamsIngressError) else 500
    code = exc.code if isinstance(exc, SlackIngressError | TeamsIngressError) else "internal_error"
    return JSONResponse({"error": {"code": code}}, status_code=status)


async def _unsupported_media_type(_: Request, __: Exception) -> Response:
    return JSONResponse({"error": {"code": "unsupported_media_type"}}, status_code=415)


async def _body_too_large(_: Request, __: Exception) -> Response:
    return JSONResponse({"error": {"code": "body_too_large"}}, status_code=413)


__all__ = ["ChannelEdgeRuntime", "create_channel_edge_app"]
