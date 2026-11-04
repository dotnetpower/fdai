"""Audited transport settings and an untrusted, bounded Release Hub catalog preview."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Column, Engine, Integer, MetaData, String, Table, Text, inspect, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Mount, Route

from fdai_lifecycle_hub.domain import Clock
from fdai_lifecycle_hub.migrations import begin_sqlite_write

DEFAULT_RELEASE_HUB_ENDPOINT = "http://127.0.0.1:8091"
MAX_PREVIEW_BYTES = 16 * 1024 * 1024
PREVIEW_TIMEOUT_SECONDS = 5
logger = logging.getLogger(__name__)
metadata = MetaData()
endpoint_settings = Table(
    "hub_release_endpoint",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("revision", Integer, nullable=False),
    Column("endpoint", String(2048)),
)
endpoint_events = Table(
    "hub_release_endpoint_event",
    metadata,
    Column("sequence", Integer, primary_key=True, autoincrement=True),
    Column("revision", Integer, nullable=False),
    Column("endpoint", String(2048)),
    Column("actor", String(160), nullable=False),
    Column("reason", Text, nullable=False),
    Column("recorded_at", String(40), nullable=False),
)


def normalize_endpoint(value: str) -> str:
    """Accept an origin only; HTTP is confined to explicit loopback targets."""
    parsed = urlsplit(value)
    host = parsed.hostname
    if (
        not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or any(character in host for character in "\\%")
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        raise ValueError("Release Hub endpoint must be an origin without credentials or a path.")
    port = parsed.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Release Hub endpoint port must be between 1 and 65535.")
    if parsed.scheme == "http":
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        if not loopback:
            raise ValueError("HTTP Release Hub endpoints must use an explicit loopback host.")
    elif parsed.scheme != "https" or port not in (None, 443):
        raise ValueError("Remote Release Hub endpoints require HTTPS on port 443.")
    canonical_host = host.encode("idna").decode("ascii").lower()
    authority = f"[{canonical_host}]" if ":" in canonical_host else canonical_host
    if port is not None and port != (80 if parsed.scheme == "http" else 443):
        authority += f":{port}"
    return f"{parsed.scheme}://{authority}"


def prepare_connection_schema(engine: Engine) -> None:
    """Explicitly expand connection storage; serving never creates database tables."""
    with engine.begin() as connection:
        metadata.create_all(connection)


EndpointSource = Literal["saved", "environment", "local-default", "deployment"]


class ConnectionState(BaseModel):
    endpoint: str
    configured_endpoint: str | None
    revision: int
    source: EndpointSource
    editable: bool
    requires_migration: bool


class EndpointChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    endpoint: str | None = Field(max_length=2048)
    revision: int = Field(ge=0)
    reason: str = Field(min_length=3, max_length=500)
    confirmation: str


class EndpointError(ValueError):
    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status, self.reason = status, reason


class ConnectionStore:
    def __init__(self, engine: Engine, *, deployment_endpoint: str | None = None) -> None:
        self.engine = engine
        self.deployment_endpoint = (
            normalize_endpoint(deployment_endpoint) if deployment_endpoint is not None else None
        )
        configured = os.environ.get("FDAI_RELEASE_HUB_ENDPOINT")
        self.environment_endpoint = (
            normalize_endpoint(configured) if configured is not None else None
        )

    def status(self) -> ConnectionState:
        ready = inspect(self.engine).has_table(endpoint_settings.name)
        if not ready:
            logger.warning("release_hub_settings_require_migration")
        with self.engine.connect() as connection:
            row = (
                connection.execute(select(endpoint_settings)).mappings().one_or_none()
                if ready
                else None
            )
        saved = row["endpoint"] if row is not None else None
        source: EndpointSource
        if self.deployment_endpoint is not None:
            endpoint, source = self.deployment_endpoint, "deployment"
        elif saved is not None:
            endpoint, source = saved, "saved"
        elif self.environment_endpoint is not None:
            endpoint, source = self.environment_endpoint, "environment"
        else:
            endpoint, source = DEFAULT_RELEASE_HUB_ENDPOINT, "local-default"
        return ConnectionState(
            endpoint=endpoint,
            configured_endpoint=saved,
            revision=row["revision"] if row is not None else 0,
            source=source,
            editable=ready and self.deployment_endpoint is None,
            requires_migration=not ready,
        )

    def change(self, change: EndpointChange, *, actor: str, clock: Clock) -> ConnectionState:
        if self.deployment_endpoint is not None:
            raise EndpointError(409, "release_hub_endpoint_is_deployment_owned")
        endpoint = normalize_endpoint(change.endpoint) if change.endpoint is not None else None
        target = endpoint if endpoint is not None else "local-default"
        if change.confirmation != f"connect release hub {target} {change.revision}":
            raise EndpointError(422, "release_hub_endpoint_confirmation_invalid")
        if len(change.reason.strip()) < 3:
            raise EndpointError(422, "release_hub_endpoint_reason_invalid")
        if not inspect(self.engine).has_table(endpoint_settings.name):
            raise EndpointError(503, "release_hub_settings_require_migration")
        try:
            with self.engine.begin() as connection:
                begin_sqlite_write(connection)
                row = (
                    connection.execute(select(endpoint_settings).with_for_update())
                    .mappings()
                    .one_or_none()
                )
                revision = row["revision"] if row is not None else 0
                if revision != change.revision:
                    raise EndpointError(409, "release_hub_endpoint_revision_changed")
                values = {"revision": revision + 1, "endpoint": endpoint}
                if row is None:
                    connection.execute(endpoint_settings.insert().values(id=1, **values))
                else:
                    connection.execute(
                        endpoint_settings.update()
                        .where(endpoint_settings.c.id == 1)
                        .values(**values)
                    )
                connection.execute(
                    endpoint_events.insert().values(
                        **values,
                        actor=actor,
                        reason=change.reason.strip(),
                        recorded_at=clock().isoformat(),
                    )
                )
        except IntegrityError as error:
            raise EndpointError(409, "release_hub_endpoint_revision_changed") from error
        return self.status()


class RegisteredRelease(BaseModel):
    model_config = ConfigDict(strict=True)
    id: str = Field(min_length=1, max_length=128)
    state: Literal["draft", "published", "recalled"]


class RegisteredCatalog(BaseModel):
    model_config = ConfigDict(strict=True)
    revision: int = Field(ge=0)
    mode: str
    expired: bool
    releases: list[RegisteredRelease] = Field(max_length=10000)


async def fetch_catalog_preview(endpoint: str) -> dict[str, object]:
    """Read registrations, never infer build verification or accept catalog trust."""
    try:
        async with asyncio.timeout(PREVIEW_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(
                timeout=PREVIEW_TIMEOUT_SECONDS, follow_redirects=False, trust_env=False
            ) as client:
                async with client.stream("GET", endpoint + "/v1/catalog") as response:
                    if response.status_code != 200:
                        raise EndpointError(503, "release_hub_catalog_unavailable")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > MAX_PREVIEW_BYTES:
                            raise EndpointError(502, "release_hub_catalog_too_large")
                        raw.extend(chunk)
        catalog = RegisteredCatalog.model_validate_json(raw)
    except (TimeoutError, httpx.HTTPError) as error:
        raise EndpointError(503, "release_hub_catalog_unavailable") from error
    except ValidationError as error:
        raise EndpointError(502, "release_hub_catalog_invalid") from error
    return {
        "endpoint": endpoint,
        "revision": catalog.revision,
        "mode": catalog.mode,
        "expired": catalog.expired,
        "releases": [release.model_dump() for release in catalog.releases],
        "release_count": len(catalog.releases),
        "build_verification": "not-performed",
        "trusted": False,
    }


def release_connection_routes(
    engine: Engine, clock: Clock, *, deployment_endpoint: str | None = None
) -> list[BaseRoute]:
    store = ConnectionStore(engine, deployment_endpoint=deployment_endpoint)

    async def status(request: Request) -> Response:
        return JSONResponse((await run_in_threadpool(store.status)).model_dump())

    async def change(request: Request) -> Response:
        from fdai_lifecycle_hub.api import _decision_request_error, _read_limited

        if decision_error := _decision_request_error(request):
            return decision_error
        body = await _read_limited(request, 4096)
        if body is None:
            raise EndpointError(413, "request_too_large")
        try:
            update = EndpointChange.model_validate_json(body)
        except ValidationError as error:
            raise EndpointError(422, "release_hub_endpoint_invalid") from error
        operator = getattr(request.state, "operator", None)
        actor = operator if isinstance(operator, str) and operator.strip() else "local-operator"
        try:
            state = await run_in_threadpool(store.change, update, actor=actor, clock=clock)
        except EndpointError:
            raise
        except ValueError as error:
            raise EndpointError(422, "release_hub_endpoint_invalid") from error
        return JSONResponse(state.model_dump())

    async def preview(request: Request) -> Response:
        state = await run_in_threadpool(store.status)
        return JSONResponse(await fetch_catalog_preview(state.endpoint))

    async def endpoint_error(request: Request, error: Exception) -> Response:
        if isinstance(error, EndpointError):
            logger.warning("release_hub_connection_rejected reason=%s", error.reason)
            return JSONResponse({"error": error.reason}, status_code=error.status)
        logger.error("release_hub_connection_storage_unavailable")
        return JSONResponse({"error": "release_hub_settings_unavailable"}, status_code=503)

    app = Starlette(
        routes=[
            Route("/connection", status),
            Route("/connection", change, methods=["POST"]),
            Route("/catalog", preview),
        ],
        exception_handlers={EndpointError: endpoint_error, SQLAlchemyError: endpoint_error},
    )
    return [Mount("/v1/release-hub", app=app)]


def unconfigured_catalog_routes() -> list[Route]:
    """Report a missing trust profile explicitly, without fabricating update results."""

    async def unavailable(request: Request) -> Response:
        logger.warning("hub_catalog_unavailable reason=catalog_not_configured")
        return JSONResponse({"error": "catalog_not_configured"}, status_code=503)

    return [
        Route("/v1/catalog/" + path, unavailable, methods=methods)
        for path, methods in [
            ("trust", ["GET"]),
            ("trust/approve", ["POST"]),
            ("import", ["POST"]),
            ("updates", ["GET"]),
            ("updates/check", ["POST"]),
            ("updates/apply", ["POST"]),
            ("releases", ["GET"]),
            ("local-channels", ["GET", "POST"]),
        ]
    ] + [Route("/v1/installations/{installation_id}/recompute", unavailable, methods=["POST"])]
