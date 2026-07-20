"""Console projection API with explicitly opt-in, non-executing command routes.

This module owns the Starlette app factory. It accepts the authenticator and
read model while the rest of the delivery layer stays framework-agnostic.

Contract (`app-shape.instructions.md § Operator console`):

- **Never** exposes a cloud-resource mutation route. Projection routes use
    ``GET``. Opt-in ``POST`` routes may record an approval, proposal, or access
    request, but they never hold the executor identity or call a resource API.
- **Never** shares an identity with the executor. The API validates the
  caller's Entra token; it does not (and can not) call executor MI.
- Authenticated **anonymous fallback** is available only when
    ``FDAI_READ_API_DEV_MODE=1`` at process start - used by the
    local dev harness (``dev-and-deploy-parity.md``) and by pytest.
- A separate local Azure CLI mode projects the current ``az login`` user
    into the dev harness without sending the CLI token to the browser.

Every handler is a plain ``async def`` - the framework-agnostic
:class:`~fdai.core.rbac.enforcer.RoleEnforcer` sits behind
:class:`Authenticator.require_roles`, so tests can drive the same
handlers without Starlette's request objects.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute

from fdai.core.rbac.enforcer import RoleRequiredError
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.delivery.read_api.app.config import ReadApiConfig
from fdai.delivery.read_api.app.lifespan import build_lifespan
from fdai.delivery.read_api.app.middleware import (
    SecurityHeadersMiddleware as _SecurityHeadersMiddleware,
)
from fdai.delivery.read_api.app.projection_routes import append_projection_routes
from fdai.delivery.read_api.app.stream_routes import append_stream_routes
from fdai.delivery.read_api.auth import (
    AuthenticationError,
    Authenticator,
)
from fdai.delivery.read_api.read_model import ConsoleReadModel
from fdai.delivery.read_api.routes import auxiliary_registration, dynamic_views
from fdai.delivery.read_api.routes.conversation_delivery import ConversationDeliveryPanel
from fdai.delivery.read_api.routes.core_reads import append_local_auth_route, make_core_read_routes
from fdai.delivery.read_api.routes.hil_callback import (
    make_hil_callback_route,
)
from fdai.delivery.read_api.routes.iam import append_iam_routes
from fdai.delivery.read_api.routes.panels import (
    PanelNotFoundError,
    PanelQueryError,
    ReadPanel,
    append_read_panels,
)
from fdai.delivery.read_api.routes.webhook import make_webhook_route

_LOGGER = logging.getLogger(__name__)

_CORE_ROUTE_PATHS: frozenset[str] = frozenset(
    {
        "/audit",
        "/kpi",
        "/hil-queue",
        "/incidents",
        "/rca",
        "/healthz",
        "/system/kill-switch",
        "/iam",
        "/iam/self",
        "/iam/directory/users",
        "/iam/directory/roster",
        "/iam/access-requests",
        "/iam/access-requests/self",
        "/me/context",
        "/me/preferences",
        "/me/memories",
        "/me/policies",
        "/me/briefing-subscriptions",
        "/me/opening-briefing",
        "/workflows/definitions",
        "/workflows/bindings",
    }
)

_READER_ROLES: tuple[Role, ...] = (Role.READER, Role.CONTRIBUTOR, Role.APPROVER, Role.OWNER)

_DEV_MODE_ENV = "FDAI_READ_API_DEV_MODE"
_DEV_MODE_PRINCIPAL = "dev-anon"
_LOCAL_AZURE_CLI_ENV = "FDAI_READ_API_LOCAL_AZURE_CLI"


def build_app(
    *,
    authenticator: Authenticator,
    read_model: ConsoleReadModel,
    config: ReadApiConfig | None = None,
) -> Starlette:
    """Assemble the ASGI app.

    The returned app carries three GET routes plus a ``/healthz`` liveness
    probe. Nothing else - the read-only invariant is enforced by *not
    registering* any mutating route.
    """
    resolved_config = config or ReadApiConfig()
    if resolved_config.dev_mode and os.environ.get(_DEV_MODE_ENV) != "1":
        raise ValueError(
            "ReadApiConfig.dev_mode=True but "
            f"{_DEV_MODE_ENV} is not set; refusing to build a dev-mode app "
            "outside an explicit local-dev environment."
        )
    # Defense in depth: even if a fork mistakenly wires dev_mode=True
    # AND FDAI_READ_API_DEV_MODE=1 in staging / prod, we refuse to boot.
    # Auth-off in staging / prod is a security-critical misconfiguration,
    # not a warning-level condition.
    if resolved_config.dev_mode:
        runtime_env = os.environ.get("RUNTIME_ENV", "").strip().lower()
        if runtime_env in ("staging", "prod"):
            raise ValueError(
                f"dev_mode is prohibited in RUNTIME_ENV={runtime_env!r}. "
                "The read API MUST require signed Entra tokens outside dev."
            )

    local_cli_principal = resolved_config.local_cli_principal
    local_cli_profile = resolved_config.local_cli_profile
    local_cli_enabled = local_cli_principal is not None
    if local_cli_enabled != (local_cli_profile is not None):
        raise ValueError("local_cli_principal and local_cli_profile MUST be configured together")
    if local_cli_enabled and resolved_config.dev_mode:
        raise ValueError("local Azure CLI auth and dev_mode MUST NOT be enabled together")
    if local_cli_enabled and os.environ.get(_LOCAL_AZURE_CLI_ENV) != "1":
        raise ValueError(
            f"local_cli_principal is configured but {_LOCAL_AZURE_CLI_ENV}=1 is not set"
        )
    if local_cli_enabled:
        runtime_env = os.environ.get("RUNTIME_ENV", "").strip().lower()
        if runtime_env in ("staging", "prod"):
            raise ValueError(f"local Azure CLI auth is prohibited in RUNTIME_ENV={runtime_env!r}")
        if local_cli_principal is None or local_cli_profile is None:
            raise ValueError("local Azure CLI auth configuration is incomplete")
        if local_cli_profile.get("oid") != local_cli_principal.oid:
            raise ValueError("local_cli_profile oid MUST match local_cli_principal")

    # Reject CORS wildcards outside dev. `allow_origins=('*',)` combined
    # with any future credentialed request is a cross-origin data leak;
    # the doc already says "MUST NOT be ('*',) in production" but the
    # code enforces it here so a bad tfvars can never ship.
    if "*" in resolved_config.cors_allow_origins:
        runtime_env = os.environ.get("RUNTIME_ENV", "").strip().lower()
        if runtime_env in ("staging", "prod"):
            raise ValueError(
                "cors_allow_origins MUST NOT contain '*' outside dev "
                f"(RUNTIME_ENV={runtime_env!r})."
            )

    def _dev_request_principal(
        request: Request,
        *,
        require_console_access: bool,
    ) -> Principal:
        header = request.headers.get("authorization")
        if header:
            if require_console_access:
                return authenticator.require_roles(header, required=_READER_ROLES)
            return authenticator.authenticate(header)
        return Principal(oid=_DEV_MODE_PRINCIPAL, roles=frozenset({Role.CONTRIBUTOR}))

    async def _authorize(request: Request) -> str:
        """Return the caller's ``oid`` (or ``dev-anon``) or raise 401/403."""
        if resolved_config.dev_mode:
            return _dev_request_principal(request, require_console_access=True).oid
        if local_cli_principal is not None:
            return local_cli_principal.oid
        header = request.headers.get("authorization")
        principal = authenticator.require_roles(header, required=_READER_ROLES)
        return principal.oid

    async def _authorize_principal(request: Request) -> Principal:
        """Return the caller's full :class:`Principal` (roles) or raise 401/403.

        The action-submit route needs the role bag to gate on capability
        server-side. Dev mode projects role claims when the local sign-in
        chooser supplies a bearer token; anonymous dev sessions retain the
        Contributor ceiling. Dev mode is refused outside local by
        :func:`build_app`.
        """
        if resolved_config.dev_mode:
            return _dev_request_principal(request, require_console_access=True)
        if local_cli_principal is not None:
            return local_cli_principal
        header = request.headers.get("authorization")
        return authenticator.require_roles(header, required=_READER_ROLES)

    async def _authenticate_principal(request: Request) -> Principal:
        """Authenticate a caller without requiring an assigned App Role."""
        if resolved_config.dev_mode:
            return _dev_request_principal(request, require_console_access=False)
        if local_cli_principal is not None:
            return local_cli_principal
        return authenticator.authenticate(request.headers.get("authorization"))

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _make_panel_handler(panel: ReadPanel) -> Callable[[Request], Awaitable[Response]]:
        async def get_panel(request: Request) -> Response:
            oid = await _authorize(request)
            try:
                payload = await panel.render(params=dict(request.query_params))
            except PanelQueryError as exc:
                return _error(400, str(exc))
            except PanelNotFoundError as exc:
                return _error(404, str(exc))
            _LOGGER.info("panel_served", extra={"actor": oid, "panel": panel.name})
            return JSONResponse(dict(payload))

        return get_panel

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

    routes: list[BaseRoute] = list(
        make_core_read_routes(
            read_model=read_model,
            authorize_oid=_authorize,
            authorize_principal=_authorize_principal,
            dev_mode=resolved_config.dev_mode,
        )
    )

    if resolved_config.kill_switch_command is not None:
        from fdai.delivery.read_api.routes.kill_switch import make_kill_switch_route

        routes.append(
            make_kill_switch_route(
                service=resolved_config.kill_switch_command,
                authorize_principal=_authorize_principal,
            )
        )

    if resolved_config.iam_access is not None:
        append_iam_routes(
            routes,
            service=resolved_config.iam_access,
            authorize=_authorize_principal,
            authenticate=_authenticate_principal,
            directory=resolved_config.iam_directory,
            identity_provider=resolved_config.iam_identity_provider,
            role_group_ids=dict(resolved_config.iam_role_group_ids),
        )

    append_local_auth_route(routes, profile=local_cli_profile)
    extra_panels = resolved_config.extra_panels
    if resolved_config.conversation_delivery_store is not None:
        extra_panels = (
            *extra_panels,
            ConversationDeliveryPanel(
                store=resolved_config.conversation_delivery_store,
                source=resolved_config.conversation_delivery_source,
            ),
        )
    seen_panel_paths = append_read_panels(
        routes,
        read_model=read_model,
        extra_panels=extra_panels,
        handler_factory=_make_panel_handler,
        core_paths=_CORE_ROUTE_PATHS,
    )

    # Optional HIL callback POST route (Wave W1.3). Fails fast if the
    # config declares a callback but not a registry - the config error
    # MUST NOT reach a live deployment.
    if resolved_config.hil_callback is not None:
        if resolved_config.hil_registry is None:
            raise ValueError(
                "hil_callback set but hil_registry is None; "
                "both are required to enable the POST callback route"
            )
        routes.append(
            make_hil_callback_route(
                registry=resolved_config.hil_registry,
                config=resolved_config.hil_callback,
                coordinator=resolved_config.hil_coordinator,
                decision_publisher=resolved_config.hil_decision_publisher,
            )
        )

    # Optional inbound webhook POST route (P2-7). Fronts the transport-
    # agnostic WebhookIngress; authenticates + injects an event, never
    # executes a change. Default composition has no webhook surface.
    if resolved_config.webhook_ingress is not None:
        webhook_path = resolved_config.webhook_path
        if webhook_path in _CORE_ROUTE_PATHS:
            raise ValueError(f"webhook_path {webhook_path!r} collides with a core route")
        if webhook_path in seen_panel_paths:
            raise ValueError(f"webhook_path {webhook_path!r} collides with a panel path")
        routes.append(
            make_webhook_route(
                ingress=resolved_config.webhook_ingress,
                path=webhook_path,
            )
        )

    # Optional live SSE fan-out. Same reader-role gate as snapshot routes.
    # The sink is the fan-out point: real pipeline stages publish onto it
    # via SseSinkStagePublisher (or EventBusStagePublisher + broadcaster);
    # the route below is one of that sink's consumers.
    stream_lifecycles = append_stream_routes(
        routes,
        config=resolved_config,
        authorize=_authorize,
        core_paths=_CORE_ROUTE_PATHS,
        panel_paths=seen_panel_paths,
    )

    append_projection_routes(
        routes,
        config=resolved_config,
        authorize=_authorize,
        authorize_principal=_authorize_principal,
        core_paths=_CORE_ROUTE_PATHS,
        panel_paths=seen_panel_paths,
    )

    auxiliary_registration.append_auxiliary_routes(
        routes,
        config=resolved_config,
        authorize=_authorize,
        authorize_principal=_authorize_principal,
        read_model=read_model,
        core_paths=_CORE_ROUTE_PATHS,
        seen_panel_paths=seen_panel_paths,
        logger=_LOGGER,
    )

    from fdai.delivery.read_api.routes.console_action import append_console_action_route

    append_console_action_route(
        routes,
        submitter=resolved_config.console_action,
        authorize_principal=_authorize_principal,
        core_paths=_CORE_ROUTE_PATHS,
        logger=_LOGGER,
    )

    dynamic_views.validate_route_method_collisions(routes)

    middleware: list[Middleware] = []
    middleware.append(
        Middleware(
            _SecurityHeadersMiddleware,
        )
    )
    if resolved_config.cors_allow_origins:
        # Derive the allow-list from routes so opt-in user-owned PUT / DELETE
        # surfaces cannot drift from CORS while absent methods stay closed.
        allow_methods = auxiliary_registration.registered_cors_methods(routes)
        middleware.append(
            Middleware(
                CORSMiddleware,
                allow_origins=list(resolved_config.cors_allow_origins),
                allow_methods=allow_methods,
                allow_headers=["authorization", "content-type"],
                allow_credentials=False,
            )
        )

    lifespan = build_lifespan(
        config=resolved_config,
        live_emitter=stream_lifecycles.live_emitter,
        live_broadcaster=stream_lifecycles.live_broadcaster,
        agent_emitter=stream_lifecycles.agent_emitter,
        agent_broadcaster=stream_lifecycles.agent_broadcaster,
        logger=_LOGGER,
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
        lifespan=lifespan,
    )


def _error(status: int, message: str) -> JSONResponse:
    body: dict[str, Any] = {"error": {"status": status, "message": message}}
    return JSONResponse(body, status_code=status)


__all__ = [
    "ReadApiConfig",
    "build_app",
]
