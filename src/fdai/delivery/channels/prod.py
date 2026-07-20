"""Production ASGI composition for bidirectional Slack and Teams channels."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.conversation.adapter_health import AdapterHealthService
from fdai.delivery.channels.adapter_health_commands import (
    AdapterHealthCommandAuthenticator,
    make_adapter_health_command_routes,
)
from fdai.delivery.channels.publishers import (
    SlackReplyPublisherConfig,
    SlackWebApiReplyPublisher,
    TeamsBotFrameworkReplyPublisher,
    TeamsReplyPublisherConfig,
)
from fdai.delivery.channels.routes import (
    TeamsActivityAuthenticator,
    make_slack_events_route,
    make_teams_activity_route,
)
from fdai.delivery.channels.routes import (
    TeamsPrincipalResolver as TeamsPrincipalResolverProtocol,
)
from fdai.delivery.channels.slack import SlackBotChannel
from fdai.delivery.channels.teams import TeamsBotChannel
from fdai.delivery.channels.teams_auth import (
    BotFrameworkJwtAuthenticator,
    TeamsPrincipalResolver,
)
from fdai.shared.providers.conversation_channel import ConversationChannelAdapter
from fdai.shared.providers.secret_provider import SecretProvider
from fdai.shared.providers.workload_identity import WorkloadIdentity


class ChannelGatewayRunner(Protocol):
    async def run(self, adapter: ConversationChannelAdapter) -> None: ...


class ChannelDeliveryStartupReconciler(Protocol):
    async def reconcile_startup(self) -> int: ...

    async def drain_due(self) -> tuple[object, ...]: ...


@dataclass(frozen=True, slots=True)
class ProductionChannelConfig:
    slack_enabled: bool
    teams_enabled: bool
    slack_signing_secret_ref: str = "slack-signing-secret"  # noqa: S105 - reference name
    slack_bot_token_ref: str = "slack-bot-token"  # noqa: S105 - reference name
    queue_capacity: int = 256

    def __post_init__(self) -> None:
        if not self.slack_enabled and not self.teams_enabled:
            raise ValueError("at least one production channel MUST be enabled")
        if self.queue_capacity < 1 or self.queue_capacity > 4096:
            raise ValueError("channel queue_capacity MUST be in [1, 4096]")
        if self.slack_enabled and (
            not self.slack_signing_secret_ref or not self.slack_bot_token_ref
        ):
            raise ValueError("Slack credential references MUST NOT be empty")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ProductionChannelConfig:
        env = environ if environ is not None else os.environ
        return cls(
            slack_enabled=_enabled(env.get("FDAI_SLACK_CHANNEL_ENABLED")),
            teams_enabled=_enabled(env.get("FDAI_TEAMS_CHANNEL_ENABLED")),
            slack_signing_secret_ref=(
                env.get("FDAI_SLACK_SIGNING_SECRET_REF", "").strip() or "slack-signing-secret"
            ),
            slack_bot_token_ref=(
                env.get("FDAI_SLACK_BOT_TOKEN_REF", "").strip() or "slack-bot-token"
            ),
            queue_capacity=_positive_int(env.get("FDAI_CHANNEL_QUEUE_CAPACITY"), 256),
        )


class ProductionChannelRuntime:
    """Own channel adapters, HTTP transport, and gateway consumer tasks."""

    def __init__(
        self,
        *,
        config: ProductionChannelConfig,
        gateway: ChannelGatewayRunner,
        secrets: SecretProvider,
        teams_identity: WorkloadIdentity | None = None,
        teams_endpoint_resolver: Any = None,
        teams_authenticate: TeamsActivityAuthenticator | None = None,
        teams_principal_resolver: TeamsPrincipalResolverProtocol | None = None,
        delivery_reconciler: ChannelDeliveryStartupReconciler | None = None,
        adapter_health_service: AdapterHealthService | None = None,
        adapter_health_authenticator: AdapterHealthCommandAuthenticator | None = None,
        http_client: httpx.AsyncClient | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._config = config
        self._gateway = gateway
        self._secrets = secrets
        self._teams_identity = teams_identity
        self._teams_endpoint_resolver = teams_endpoint_resolver
        self._teams_authenticate = teams_authenticate
        self._teams_principal_resolver = teams_principal_resolver
        self._delivery_reconciler = delivery_reconciler
        if (adapter_health_service is None) != (adapter_health_authenticator is None):
            raise ValueError(
                "adapter health commands require both service and separate authenticator"
            )
        self._adapter_health_service = adapter_health_service
        self._adapter_health_authenticator = adapter_health_authenticator
        self._http = http_client
        self._owns_http = http_client is None
        self._environ = environ
        self._channels: list[ConversationChannelAdapter] = []
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> tuple[Route, ...]:
        if self._tasks:
            raise RuntimeError("production channel runtime is already started")
        http_client = self._http or httpx.AsyncClient()
        self._http = http_client
        routes: list[Route] = []
        try:
            if self._delivery_reconciler is not None:
                await self._delivery_reconciler.reconcile_startup()
                await self._delivery_reconciler.drain_due()
            if (
                self._adapter_health_service is not None
                and self._adapter_health_authenticator is not None
            ):
                routes.extend(
                    make_adapter_health_command_routes(
                        service=self._adapter_health_service,
                        authenticator=self._adapter_health_authenticator,
                    )
                )
            if self._config.slack_enabled:
                signing_secret, bot_token = await asyncio.gather(
                    self._secrets.get(self._config.slack_signing_secret_ref),
                    self._secrets.get(self._config.slack_bot_token_ref),
                )
                slack = SlackBotChannel(
                    signing_secret=signing_secret,
                    publisher=SlackWebApiReplyPublisher(
                        config=SlackReplyPublisherConfig(),
                        token=bot_token,
                        http_client=http_client,
                    ),
                    queue_capacity=self._config.queue_capacity,
                )
                self._channels.append(slack)
                routes.append(make_slack_events_route(channel=slack))
            if self._config.teams_enabled:
                if self._teams_identity is None or not callable(self._teams_endpoint_resolver):
                    raise ValueError("Teams workload identity and endpoint resolver are required")
                authenticate = self._teams_authenticate or BotFrameworkJwtAuthenticator.from_env(
                    self._environ
                )
                principal_resolver = (
                    self._teams_principal_resolver or TeamsPrincipalResolver.from_env(self._environ)
                )
                teams = TeamsBotChannel(
                    publisher=TeamsBotFrameworkReplyPublisher(
                        config=TeamsReplyPublisherConfig(),
                        identity=self._teams_identity,
                        endpoint_resolver=self._teams_endpoint_resolver,
                        http_client=http_client,
                    ),
                    queue_capacity=self._config.queue_capacity,
                )
                self._channels.append(teams)
                routes.append(
                    make_teams_activity_route(
                        channel=teams,
                        authenticate=authenticate,
                        resolve_principal=principal_resolver,
                    )
                )
            self._tasks = [
                asyncio.create_task(self._gateway.run(channel)) for channel in self._channels
            ]
            return tuple(routes)
        except BaseException:
            await self.stop()
            raise

    async def stop(self) -> None:
        for channel in self._channels:
            close = getattr(channel, "close", None)
            if callable(close):
                close()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self._channels.clear()
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None


def build_channel_app(runtime: ProductionChannelRuntime) -> Starlette:
    """Build the standalone channel ingress app; routes appear only after startup."""

    async def healthz(_request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    routes: list[Route] = [Route("/healthz", healthz, methods=["GET"])]

    @asynccontextmanager
    async def lifespan(app: Starlette):  # type: ignore[no-untyped-def]
        channel_routes = await runtime.start()
        app.router.routes.extend(channel_routes)
        try:
            yield
        finally:
            for route in channel_routes:
                app.router.routes.remove(route)
            await runtime.stop()

    return Starlette(routes=routes, lifespan=lifespan)


def _enabled(value: str | None) -> bool:
    return bool(value and value.strip().casefold() in {"1", "true", "yes", "on"})


def _positive_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError("FDAI_CHANNEL_QUEUE_CAPACITY MUST be an integer") from exc


__all__ = [
    "ChannelDeliveryStartupReconciler",
    "ChannelGatewayRunner",
    "ProductionChannelConfig",
    "ProductionChannelRuntime",
    "build_channel_app",
]
