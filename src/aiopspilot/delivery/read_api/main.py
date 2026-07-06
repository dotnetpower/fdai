"""Read-only console API — three GET routes, no POST surface.

This module is the **only** place Starlette is imported in the codebase.
The rest of the delivery layer stays framework-agnostic; the app factory
takes an :class:`~aiopspilot.delivery.read_api.auth.Authenticator` and a
:class:`~aiopspilot.delivery.read_api.read_model.ConsoleReadModel` and
returns a Starlette application ready to be served by any ASGI server
(uvicorn, hypercorn, granian).

Contract (`app-shape.instructions.md § Operator console`):

- **Never** exposes a mutating route. Only ``GET`` is registered; ``POST``
  / ``PUT`` / ``DELETE`` / ``PATCH`` return ``405`` from Starlette's
  built-in method-not-allowed handler.
- **Never** shares an identity with the executor. The API validates the
  caller's Entra token; it does not (and can not) call executor MI.
- Authenticated **anonymous fallback** is available only when
  ``AIOPSPILOT_READ_API_DEV_MODE=1`` at process start — used by the
  local dev harness (``dev-and-deploy-parity.md``) and by pytest.

Every handler is a plain ``async def`` — the framework-agnostic
:class:`~aiopspilot.core.rbac.enforcer.RoleEnforcer` sits behind
:class:`Authenticator.require_roles`, so tests can drive the same
handlers without Starlette's request objects.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from aiopspilot.core.rbac.enforcer import RoleRequiredError
from aiopspilot.core.rbac.roles import Role
from aiopspilot.delivery.read_api.auth import (
    AuthenticationError,
    Authenticator,
)
from aiopspilot.delivery.read_api.read_model import (
    DEFAULT_LIMIT,
    ConsoleReadModel,
    clamp_limit,
)

_LOGGER = logging.getLogger(__name__)

_READER_ROLES: tuple[Role, ...] = (Role.READER, Role.CONTRIBUTOR, Role.APPROVER, Role.OWNER)

_DEV_MODE_ENV = "AIOPSPILOT_READ_API_DEV_MODE"
_DEV_MODE_PRINCIPAL = "dev-anon"


@dataclass(frozen=True, slots=True)
class ReadApiConfig:
    """Composition-root configuration for :func:`build_app`.

    ``dev_mode`` short-circuits authentication for local development and
    tests. It MUST default to ``False`` and MUST NOT be true in a
    production composition root — the fork's IaC pipeline enforces that
    by never setting ``AIOPSPILOT_READ_API_DEV_MODE`` on deployed
    revisions.
    """

    dev_mode: bool = False
    """When True, unauthenticated requests are treated as anonymous
    Readers. Only for local dev + pytest."""

    cors_allow_origins: tuple[str, ...] = ()
    """Origins the console SPA is served from. Empty tuple disables CORS
    (same-origin deployment). MUST NOT be ``('*',)`` in production."""


def build_app(
    *,
    authenticator: Authenticator,
    read_model: ConsoleReadModel,
    config: ReadApiConfig | None = None,
) -> Starlette:
    """Assemble the ASGI app.

    The returned app carries three GET routes plus a ``/healthz`` liveness
    probe. Nothing else — the read-only invariant is enforced by *not
    registering* any mutating route.
    """
    resolved_config = config or ReadApiConfig()
    if resolved_config.dev_mode and os.environ.get(_DEV_MODE_ENV) != "1":
        raise ValueError(
            "ReadApiConfig.dev_mode=True but "
            f"{_DEV_MODE_ENV} is not set; refusing to build a dev-mode app "
            "outside an explicit local-dev environment."
        )

    async def _authorize(request: Request) -> str:
        """Return the caller's ``oid`` (or ``dev-anon``) or raise 401/403."""
        if resolved_config.dev_mode:
            return _DEV_MODE_PRINCIPAL
        header = request.headers.get("authorization")
        principal = authenticator.require_roles(header, required=_READER_ROLES)
        return principal.oid

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def get_audit(request: Request) -> Response:
        oid = await _authorize(request)
        try:
            limit = _parse_int_query(request, "limit", default=DEFAULT_LIMIT)
        except _BadQueryError as exc:
            return _error(400, str(exc))
        cursor = request.query_params.get("cursor")
        try:
            page = await read_model.list_audit(limit=clamp_limit(limit), cursor=cursor)
        except ValueError as exc:
            return _error(400, str(exc))
        _LOGGER.info("audit_page_served", extra={"actor": oid, "returned": len(page.items)})
        return JSONResponse(page.to_dict())

    async def get_kpi(request: Request) -> Response:
        oid = await _authorize(request)
        kpi = await read_model.dashboard_metrics()
        _LOGGER.info("kpi_served", extra={"actor": oid, "event_count": kpi.event_count})
        return JSONResponse(kpi.to_dict())

    async def get_hil_queue(request: Request) -> Response:
        oid = await _authorize(request)
        try:
            limit = _parse_int_query(request, "limit", default=DEFAULT_LIMIT)
        except _BadQueryError as exc:
            return _error(400, str(exc))
        page = await read_model.list_hil_queue(limit=clamp_limit(limit))
        _LOGGER.info(
            "hil_queue_served",
            extra={"actor": oid, "returned": len(page.items)},
        )
        return JSONResponse(page.to_dict())

    async def healthz(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    # ------------------------------------------------------------------
    # Exception handlers translate RBAC primitives to HTTP status codes.
    # ------------------------------------------------------------------

    async def handle_authentication_error(_: Request, exc: Exception) -> Response:
        return _error(401, str(exc))

    async def handle_authorization_error(_: Request, exc: Exception) -> Response:
        return _error(403, str(exc))

    async def handle_http_exception(_: Request, exc: Exception) -> Response:
        if isinstance(exc, HTTPException):
            return _error(exc.status_code, exc.detail)
        return _error(500, "internal error")

    routes = [
        Route("/audit", get_audit, methods=["GET"]),
        Route("/kpi", get_kpi, methods=["GET"]),
        Route("/hil-queue", get_hil_queue, methods=["GET"]),
        Route("/healthz", healthz, methods=["GET"]),
    ]

    middleware: list[Middleware] = []
    if resolved_config.cors_allow_origins:
        # Console SPA cross-origin fetches. `allow_methods=["GET"]` keeps
        # the pre-flight surface aligned with the read-only invariant —
        # a POST/PUT/DELETE pre-flight will be denied at the middleware.
        middleware.append(
            Middleware(
                CORSMiddleware,
                allow_origins=list(resolved_config.cors_allow_origins),
                allow_methods=["GET"],
                allow_headers=["authorization", "content-type"],
                allow_credentials=False,
            )
        )

    return Starlette(
        debug=False,
        routes=routes,
        middleware=middleware,
        exception_handlers={
            AuthenticationError: handle_authentication_error,
            RoleRequiredError: handle_authorization_error,
            HTTPException: handle_http_exception,
        },
    )


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


class _BadQueryError(ValueError):
    """Raised inside ``get_*`` when a query string is malformed.

    Caught locally and turned into a ``400`` response — the caller
    should not see a stack trace for a typo in ``?limit=``.
    """


def _parse_int_query(request: Request, name: str, *, default: int) -> int:
    raw = request.query_params.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise _BadQueryError(f"query param {name!r} must be an integer, got {raw!r}") from exc


def _error(status: int, message: str) -> JSONResponse:
    body: dict[str, Any] = {"error": {"status": status, "message": message}}
    return JSONResponse(body, status_code=status)


__all__ = [
    "ReadApiConfig",
    "build_app",
]
