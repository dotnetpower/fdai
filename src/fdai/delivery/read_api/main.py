"""Read-only console API - three GET routes, no POST surface.

This module is the **only** place Starlette is imported in the codebase.
The rest of the delivery layer stays framework-agnostic; the app factory
takes an :class:`~fdai.delivery.read_api.auth.Authenticator` and a
:class:`~fdai.delivery.read_api.read_model.ConsoleReadModel` and
returns a Starlette application ready to be served by any ASGI server
(uvicorn, hypercorn, granian).

Contract (`app-shape.instructions.md § Operator console`):

- **Never** exposes a mutating route. Only ``GET`` is registered; ``POST``
  / ``PUT`` / ``DELETE`` / ``PATCH`` return ``405`` from Starlette's
  built-in method-not-allowed handler.
- **Never** shares an identity with the executor. The API validates the
  caller's Entra token; it does not (and can not) call executor MI.
- Authenticated **anonymous fallback** is available only when
  ``FDAI_READ_API_DEV_MODE=1`` at process start - used by the
  local dev harness (``dev-and-deploy-parity.md``) and by pytest.

Every handler is a plain ``async def`` - the framework-agnostic
:class:`~fdai.core.rbac.enforcer.RoleEnforcer` sits behind
:class:`Authenticator.require_roles`, so tests can drive the same
handlers without Starlette's request objects.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.hil_resume import HilResumeCoordinator
from fdai.core.rbac.enforcer import RoleRequiredError
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.delivery.read_api.auth import (
    AuthenticationError,
    Authenticator,
)
from fdai.delivery.read_api.hil_callback import (
    HilCallbackConfig,
    make_hil_callback_route,
)
from fdai.delivery.read_api.live_stream import (
    LiveEmitter,
    LiveStreamConfig,
    SyntheticLiveEmitter,
    make_live_stream_route,
)
from fdai.delivery.read_api.panels import ReadPanel
from fdai.delivery.read_api.provision_stream import (
    ProvisionStreamConfig,
    make_provision_stream_route,
)
from fdai.delivery.read_api.read_model import (
    DEFAULT_LIMIT,
    ConsoleReadModel,
    clamp_limit,
)
from fdai.shared.providers.hil_registry import HilApprovalRegistry
from fdai.shared.providers.sse import SseSink
from fdai.shared.providers.testing.sse import InMemorySseSink

_LOGGER = logging.getLogger(__name__)

_CORE_ROUTE_PATHS: frozenset[str] = frozenset({"/audit", "/kpi", "/hil-queue", "/healthz"})

_READER_ROLES: tuple[Role, ...] = (Role.READER, Role.CONTRIBUTOR, Role.APPROVER, Role.OWNER)

_DEV_MODE_ENV = "FDAI_READ_API_DEV_MODE"
_DEV_MODE_PRINCIPAL = "dev-anon"


class _SecurityHeadersMiddleware:
    """Attach conservative security headers to every response.

    Kept as a pure ASGI middleware (not `starlette.BaseHTTPMiddleware`) so
    it never buffers the response body - critical for the SSE routes
    served by ``live_stream.py`` which stream indefinitely.

    Headers set:

    - ``X-Content-Type-Options: nosniff`` - block MIME sniffing.
    - ``X-Frame-Options: DENY`` - refuse framing (the SPA is same-origin).
    - ``Referrer-Policy: no-referrer`` - no leak of internal URLs.
    - ``Cache-Control: no-store`` - the console shows live state; a
      cached audit response is misleading and stale.
    - ``Strict-Transport-Security: max-age=31536000; includeSubDomains``
      - forces HTTPS on every subsequent request.

    ``Cache-Control`` is intentionally not applied to ``/live/stream``
    responses since they already set their own ``no-cache, no-transform``
    header - we do not override an explicit choice made by the route.
    """

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self._app = app

    async def __call__(self, scope: Mapping[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        async def send_with_headers(message: Mapping[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                # Copy so we do not mutate a shared reference.
                headers = list(message.get("headers") or [])
                existing_names = {name.lower() for name, _ in headers}

                def _add_if_absent(name: bytes, value: bytes) -> None:
                    if name.lower() not in existing_names:
                        headers.append((name, value))

                _add_if_absent(b"x-content-type-options", b"nosniff")
                _add_if_absent(b"x-frame-options", b"DENY")
                _add_if_absent(b"referrer-policy", b"no-referrer")
                _add_if_absent(b"cache-control", b"no-store")
                _add_if_absent(
                    b"strict-transport-security",
                    b"max-age=31536000; includeSubDomains",
                )
                new_message = dict(message)
                new_message["headers"] = headers
                await send(new_message)
            else:
                await send(message)

        await self._app(scope, receive, send_with_headers)


@dataclass(frozen=True, slots=True)
class ReadApiConfig:
    """Composition-root configuration for :func:`build_app`.

    ``dev_mode`` short-circuits authentication for local development and
    tests. It MUST default to ``False`` and MUST NOT be true in a
    production composition root - the fork's IaC pipeline enforces that
    by never setting ``FDAI_READ_API_DEV_MODE`` on deployed
    revisions.
    """

    dev_mode: bool = False
    """When True, unauthenticated requests are treated as anonymous
    Readers. Only for local dev + pytest."""

    cors_allow_origins: tuple[str, ...] = ()
    """Origins the console SPA is served from. Empty tuple disables CORS
    (same-origin deployment). MUST NOT be ``('*',)`` in production."""

    extra_panels: tuple[ReadPanel, ...] = ()
    """Fork-supplied read-only console panels (see
    :mod:`fdai.delivery.read_api.panels`). Empty by default so the
    upstream UI stays minimal; a fork registers vertical dashboards here.
    Each panel is registered as a ``GET``-only route, preserving the
    read-only invariant. The app factory fails fast on a malformed or
    colliding panel path."""

    hil_callback: HilCallbackConfig | None = None
    """Opt-in ChatOps HIL callback config. When set, registers a single
    ``POST /hil/{approval_id}/decision`` route that verifies an HMAC
    signature over the request body. ``None`` (the default) keeps the
    read-API strictly GET-only. The route consumes a
    :class:`~fdai.shared.providers.hil_registry.HilApprovalRegistry`
    instead of the executor identity, so no privilege boundary is
    crossed. See Wave W1.3 in
    [implementation-plan.md](../../../../docs/roadmap/implementation-plan.md)."""

    hil_registry: HilApprovalRegistry | None = None
    """Registry consumed by the HIL callback route. When
    ``hil_callback`` is set, this MUST also be set - the app factory
    fails fast otherwise."""

    hil_coordinator: HilResumeCoordinator | None = None
    """Optional park-and-resume coordinator for the HIL callback route.
    When set, an inbound decision is applied to a control-loop-parked
    action first (APPROVE re-dispatches it to the executor); an
    approval with no matching park falls through to the registry path.
    ``None`` keeps the callback registry-only (console-pull approvals)."""

    live_stream: LiveStreamConfig | None = None
    """Opt-in live SSE fan-out. When set, registers a ``GET`` streaming
    route (default ``/live/stream``) that broadcasts control-plane
    events to any subscriber. The default is ``None`` - upstream ships
    strictly three GET routes; a fork (or the dev harness in
    :mod:`fdai.delivery.read_api._local`) opts in. See
    :mod:`fdai.delivery.read_api.live_stream` for the read-only /
    fan-out contract."""

    provision_stream: ProvisionStreamConfig | None = None
    """Opt-in provisioning progress SSE surface. When set, registers a
    ``GET`` streaming route (default ``/provision/stream``) that fans out
    ``provision.*`` events to the Genesis console. Read-only: the console
    renders progress, it never executes provisioning. The producer (the
    ``azd up`` terraform bridge, or an in-product relay) publishes onto
    the shared sink via
    :class:`~fdai.delivery.read_api.provision_stream.SseProvisionPublisher`.
    Default ``None``. See
    :mod:`fdai.delivery.read_api.provision_stream`."""

    blast_radius_graph: Any = None
    """Opt-in blast-radius simulator. When set (an
    :class:`~fdai.core.risk_gate.blast_radius_simulator.OntologyGraph`),
    registers ``GET /simulate/blast-radius``. Read-only projection: the
    caller supplies a target Resource id + traversal spec, gets back
    the depth-N reachable subgraph. The default is ``None`` so upstream
    stays minimal; a fork wires its Postgres-backed graph adapter here.
    See :mod:`fdai.delivery.read_api.blast_radius`."""

    ontology_object_types: tuple[Any, ...] = ()
    """Opt-in ontology explorer input. Tuple of
    :class:`~fdai.shared.contracts.models.OntologyObjectType`. When
    combined with :attr:`ontology_link_types`, the app registers
    ``GET /ontology/graph`` returning a Mermaid ``classDiagram`` plus
    node/edge counts. Empty by default."""

    ontology_link_types: tuple[Any, ...] = ()
    """Opt-in ontology explorer input. Tuple of
    :class:`~fdai.shared.contracts.models.OntologyLinkType`. See
    :attr:`ontology_object_types` for the pairing contract."""

    rule_catalog_rules: tuple[Any, ...] = ()
    """Opt-in rule-catalog explorer input: the *active* catalog. Tuple of
    :class:`~fdai.shared.contracts.models.Rule` loaded at
    composition-root time via
    :func:`~fdai.rule_catalog.schema.rule.load_rule_catalog` (the curated
    ``rule-catalog/catalog/`` tier T0 evaluates). When this OR
    :attr:`rule_catalog_collected_rules` is non-empty, the app registers
    a paginated ``GET /rules`` returning rule summaries tagged
    ``origin=active`` plus facet counts, so the console's Knowledge >
    Rules panel can render every policy the system knows. Empty by
    default so upstream stays minimal. Read-only projection - the route
    never mutates state. See :mod:`fdai.delivery.read_api.rule_catalog`."""

    rule_catalog_collected_rules: tuple[Any, ...] = ()
    """Opt-in rule-catalog explorer input: the *collected* corpus. Tuple
    of :class:`~fdai.shared.contracts.models.Rule` parsed from the
    imported ``rule-catalog/collected/`` tree (Azure Policy built-ins,
    kube-bench). Thousands of candidate / reference rules that are not
    all normalized to the canonical vocabulary yet; served tagged
    ``origin=collected`` alongside the active tier on ``GET /rules``.
    Empty by default. Same read-only projection contract as
    :attr:`rule_catalog_rules`."""

    rule_catalog_policies_root: Any = None
    """Opt-in filesystem root (:class:`pathlib.Path`) for the rule detail
    view. When set, ``GET /rules/{id}`` resolves a rule's
    ``check_logic.reference`` (e.g. ``policies/x.rego``) to the file body
    so the console drawer can show the actual Rego. Reads are sandboxed
    to this root; a traversal or non-file reference yields ``null``.
    ``None`` serves metadata only."""

    rule_catalog_remediation_root: Any = None
    """Opt-in filesystem root (:class:`pathlib.Path`) for the rule detail
    view. When set, ``GET /rules/{id}`` resolves a rule's
    ``remediation.template_ref`` (e.g. ``remediation/x.tftpl``) to the
    file body. Same sandbox contract as
    :attr:`rule_catalog_policies_root`."""

    rule_catalog_findings_provider: Any = None
    """Opt-in findings source for ``GET /rules/{id}/findings`` (the
    affected-resources view). A callable ``(rule_id, origin) ->
    awaitable[sequence[mapping]]`` where each mapping describes one
    resource violating the rule plus the attribute at fault. ``None``
    (default) makes the endpoint report ``evaluated=false`` with no
    findings - upstream never fabricates resource impact. A fork wires
    an inventory-evaluation source (assurance_twin / T0 over real
    inventory)."""

    rule_catalog_findings_summary_provider: Any = None
    """Opt-in count source for ``GET /rules/findings-summary`` (the
    at-a-glance affected-count badge on the list). A callable ``() ->
    awaitable[mapping[rule_id, int]]``. ``None`` (default) makes the
    endpoint report ``evaluated=false``; a fork wires the same
    inventory-evaluation source as :attr:`rule_catalog_findings_provider`."""

    promotion_gate_action_types: tuple[Any, ...] = ()
    """Opt-in promotion-gate dashboard input: tuple of
    :class:`~fdai.shared.contracts.models.OntologyActionType`."""

    promotion_gate_source: Any = None
    """Opt-in promotion-gate dashboard input:
    :class:`~fdai.core.measurement.promotion_gate.ShadowVerdictSource`.
    When BOTH this and :attr:`promotion_gate_action_types` are set,
    the app registers ``GET /kpi/promotion-gates``."""

    trace_reader: Any = None
    """Opt-in rule-fire trace viewer. When set (an
    :class:`~fdai.core.audit.rule_fire_trace.AuditTraceReader`),
    registers ``GET /audit/{correlation_id}/trace``. The reader plugs
    into any audit backing store; the shipped
    :class:`~fdai.core.audit.rule_fire_trace.ConsoleReadModelTraceReader`
    wraps the existing :class:`ConsoleReadModel` and works with the
    in-memory store out of the box."""

    bitemporal_reader: Any = None
    """Opt-in bitemporal snapshot route. When set (an
    :class:`~fdai.core.audit.rule_fire_trace.AuditTraceReader`),
    registers ``GET /audit/{correlation_id}/bitemporal``. Typically the
    same reader used for :attr:`trace_reader`."""

    what_if_reader: Any = None
    """Opt-in what-if replay route reader. When BOTH this and
    :attr:`what_if_evaluators` are set, registers
    ``GET /audit/{correlation_id}/what-if?scenario=<name>``."""

    what_if_evaluators: Mapping[str, Any] = field(default_factory=dict)
    """Named pre-registered
    :class:`~fdai.core.audit.what_if_replay.WhatIfEvaluator` implementations.
    Empty by default so upstream stays minimal; a fork registers each
    scenario at composition-root time."""

    chat: Any = None
    """Opt-in CommandDeck chat backend. When set (an implementer of
    :class:`~fdai.delivery.read_api.chat.ChatBackend`), registers
    ``POST /chat`` for the console's screen-aware conversational
    surface. The backend is a read-only translator - it never issues a
    privileged call. Wire :class:`~fdai.delivery.read_api.chat.OpenAiCompatibleChatBackend`
    (or a fork adapter) at composition root; leave ``None`` to keep the
    endpoint unregistered (the FE deck then falls back to its built-in
    deterministic answerer)."""

    console_action: Any = None
    """Opt-in console action submitter
    (:class:`~fdai.delivery.read_api.console_action.ConsoleActionSubmitter`).
    When set, registers ``POST /chat/action`` - the ONE write-direction
    conversational path: it publishes an operator ``ActionProposal`` onto the
    raw event topic where the pantheon judges/approves/executes it. It holds no
    executor identity and never mutates a resource (propose, never execute);
    RBAC is server-derived (Contributor+ ``author-draft-pr``). Leave ``None`` to
    keep the console read-only with no action-submit surface."""

    expose_pantheon: bool = False
    """Opt-in pantheon graph + workflows endpoints. When True, registers
    two read-only routes: ``GET /pantheon/graph`` (15 agents, org chart
    edges, owned object types, LLM hot-path flag) and
    ``GET /pantheon/workflows`` (10 cross-agent workflow catalog). Both
    are pure projections of the in-memory pantheon registry
    (``fdai.agents``); no state, no side effects. Reader-role gate.
    See :mod:`fdai.delivery.read_api.pantheon`."""

    workflow_authoring: Any = None
    """Opt-in custom workflow authoring routes. When set (a
    :class:`~fdai.delivery.read_api.workflow_authoring.WorkflowAuthoringConfig`),
    registers ``GET /workflows/action-types`` (the ActionType palette the
    builder maps steps onto) and ``POST /workflows/validate`` (validate a
    draft Workflow and return a canonical YAML preview). Both are
    read-only: the validate route is a pure function that writes no state
    and never creates a PR - the console copies the previewed YAML into a
    remediation PR through the git-native path. Reader-role gate. Unset by
    default so upstream stays minimal.
    See :mod:`fdai.delivery.read_api.workflow_authoring`."""

    reporting: Any = None
    """Opt-in reporting subsystem routes. When set (a
    :class:`~fdai.delivery.read_api.reporting.ReportingConfig`),
    registers four ``GET`` routes under the configured prefix (default
    ``/reports``): catalog listing, registry inspection, per-report
    definition, and per-report render (with ``?format=json|markdown|
    csv``). All read-only; every route hits the reader-role gate. See
    :mod:`fdai.delivery.read_api.reporting` and
    :mod:`fdai.core.reporting` for the fork-extensible datasource /
    widget / format seams. Unset by default so upstream stays minimal."""


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

    async def _authorize(request: Request) -> str:
        """Return the caller's ``oid`` (or ``dev-anon``) or raise 401/403."""
        if resolved_config.dev_mode:
            return _DEV_MODE_PRINCIPAL
        header = request.headers.get("authorization")
        principal = authenticator.require_roles(header, required=_READER_ROLES)
        return principal.oid

    async def _authorize_principal(request: Request) -> Principal:
        """Return the caller's full :class:`Principal` (roles) or raise 401/403.

        The action-submit route needs the role bag to gate on capability
        server-side. In dev mode there is no token; return a Contributor-roled
        dev principal so the local harness can exercise the submit path (dev
        mode is refused outside local by :func:`build_app`).
        """
        if resolved_config.dev_mode:
            return Principal(oid=_DEV_MODE_PRINCIPAL, roles=frozenset({Role.CONTRIBUTOR}))
        header = request.headers.get("authorization")
        return authenticator.require_roles(header, required=_READER_ROLES)

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
        if cursor is not None and len(cursor) > 1024:
            # Real cursors are opaque tokens under 200 bytes; anything
            # larger is either a client bug or a probe. Cap so the log
            # line + downstream store lookup stay bounded.
            return _error(400, "cursor is too long")
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

    def _make_panel_handler(panel: ReadPanel) -> Callable[[Request], Awaitable[Response]]:
        async def get_panel(request: Request) -> Response:
            oid = await _authorize(request)
            payload = await panel.render(params=dict(request.query_params))
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

    routes = [
        Route("/audit", get_audit, methods=["GET"]),
        Route("/kpi", get_kpi, methods=["GET"]),
        Route("/hil-queue", get_hil_queue, methods=["GET"]),
        Route("/healthz", healthz, methods=["GET"]),
    ]

    # Fork-supplied panels: registered GET-only, after fail-fast validation
    # so a colliding or malformed path cannot ship a broken revision.
    seen_panel_paths: set[str] = set()
    for panel in resolved_config.extra_panels:
        path = panel.path
        if not path.startswith("/"):
            raise ValueError(f"panel path MUST start with '/', got {path!r} ({panel.name!r})")
        if path in _CORE_ROUTE_PATHS:
            raise ValueError(f"panel path {path!r} collides with a core route ({panel.name!r})")
        if path in seen_panel_paths:
            raise ValueError(f"duplicate panel path {path!r} ({panel.name!r})")
        seen_panel_paths.add(path)
        routes.append(Route(path, _make_panel_handler(panel), methods=["GET"]))

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
            )
        )

    # Optional live SSE fan-out. Same reader-role gate as snapshot routes.
    # The sink is the fan-out point: real pipeline stages publish onto it
    # via SseSinkStagePublisher (or EventBusStagePublisher + broadcaster);
    # the route below is one of that sink's consumers.
    live_sink: SseSink | None = None
    live_emitter: LiveEmitter | None = None
    if resolved_config.live_stream is not None:
        live_cfg = resolved_config.live_stream
        if live_cfg.path in _CORE_ROUTE_PATHS:
            raise ValueError(f"live_stream.path {live_cfg.path!r} collides with a core route")
        if live_cfg.path in seen_panel_paths:
            raise ValueError(f"live_stream.path {live_cfg.path!r} collides with a panel path")
        live_sink = live_cfg.sink if live_cfg.sink is not None else InMemorySseSink()
        if live_cfg.emitter_factory is not None:
            live_emitter = live_cfg.emitter_factory(live_sink, live_cfg.channel)
        elif live_cfg.sink is None:
            # Dev-friendly default: no external sink supplied means no real
            # publishers are wired, so start a synthetic emitter so the
            # console has something to render. When a fork supplies its own
            # sink (real publishers already write to it) we do NOT stack a
            # synthetic emitter on top.
            live_emitter = SyntheticLiveEmitter(sink=live_sink, channel=live_cfg.channel)
        routes.append(
            make_live_stream_route(
                sink=live_sink,
                channel=live_cfg.channel,
                path=live_cfg.path,
                keepalive_seconds=live_cfg.keepalive_seconds,
                authorize=_authorize,
            )
        )

    # Optional provisioning progress SSE. Same reader-role gate; the
    # producer (terraform bridge / in-product relay) publishes onto the
    # shared sink. No synthetic emitter - a stream with no producer simply
    # waits, which is the honest ambient state the Genesis screen renders.
    if resolved_config.provision_stream is not None:
        prov_cfg = resolved_config.provision_stream
        if prov_cfg.path in _CORE_ROUTE_PATHS:
            raise ValueError(
                f"provision_stream.path {prov_cfg.path!r} collides with a core route"
            )
        if prov_cfg.path in seen_panel_paths:
            raise ValueError(
                f"provision_stream.path {prov_cfg.path!r} collides with a panel path"
            )
        if (
            resolved_config.live_stream is not None
            and prov_cfg.path == resolved_config.live_stream.path
        ):
            # Two SSE routes on one path silently shadow each other in
            # Starlette (first match wins); fail fast at build time instead.
            raise ValueError(
                f"provision_stream.path {prov_cfg.path!r} collides with the live-stream route"
            )
        prov_sink = prov_cfg.sink if prov_cfg.sink is not None else InMemorySseSink()
        routes.append(
            make_provision_stream_route(
                sink=prov_sink,
                channel=prov_cfg.channel,
                path=prov_cfg.path,
                keepalive_seconds=prov_cfg.keepalive_seconds,
                authorize=_authorize,
            )
        )

    # Optional blast-radius simulator. Reader-role gate, GET-only, and
    # collision-checked against every other route registered so far.
    if resolved_config.blast_radius_graph is not None:
        from fdai.delivery.read_api.blast_radius import (
            DEFAULT_ROUTE_PATH as _BR_PATH,
        )
        from fdai.delivery.read_api.blast_radius import (
            make_blast_radius_route,
        )

        if _BR_PATH in _CORE_ROUTE_PATHS:
            raise ValueError(f"blast-radius path {_BR_PATH!r} collides with a core route")
        if _BR_PATH in seen_panel_paths:
            raise ValueError(f"blast-radius path {_BR_PATH!r} collides with a panel path")
        routes.append(
            make_blast_radius_route(
                graph=resolved_config.blast_radius_graph,
                authorize=_authorize,
            )
        )

    # Optional ontology explorer. Both ObjectType and LinkType tuples
    # MUST be non-empty for the graph to make sense.
    if resolved_config.ontology_object_types and resolved_config.ontology_link_types:
        from fdai.delivery.read_api.ontology_graph import (
            DEFAULT_ROUTE_PATH as _OG_PATH,
        )
        from fdai.delivery.read_api.ontology_graph import (
            make_ontology_graph_route,
        )

        if _OG_PATH in _CORE_ROUTE_PATHS:
            raise ValueError(f"ontology-graph path {_OG_PATH!r} collides with a core route")
        if _OG_PATH in seen_panel_paths:
            raise ValueError(f"ontology-graph path {_OG_PATH!r} collides with a panel path")
        routes.append(
            make_ontology_graph_route(
                object_types=resolved_config.ontology_object_types,
                link_types=resolved_config.ontology_link_types,
                authorize=_authorize,
            )
        )

    # Optional rule-catalog explorer. Registered when either tier
    # (active catalog or collected corpus) is wired in; a pure paginated
    # projection over an immutable rule snapshot, plus a detail route.
    if resolved_config.rule_catalog_rules or resolved_config.rule_catalog_collected_rules:
        from fdai.delivery.read_api.rule_catalog import (
            DEFAULT_ROUTE_PATH as _RC_PATH,
        )
        from fdai.delivery.read_api.rule_catalog import (
            DETAIL_ROUTE_PATH as _RC_DETAIL_PATH,
        )
        from fdai.delivery.read_api.rule_catalog import (
            FINDINGS_ROUTE_PATH as _RC_FINDINGS_PATH,
        )
        from fdai.delivery.read_api.rule_catalog import (
            FINDINGS_SUMMARY_ROUTE_PATH as _RC_SUMMARY_PATH,
        )
        from fdai.delivery.read_api.rule_catalog import (
            make_rule_catalog_routes,
        )

        for _rc in (_RC_PATH, _RC_DETAIL_PATH, _RC_FINDINGS_PATH, _RC_SUMMARY_PATH):
            if _rc in _CORE_ROUTE_PATHS:
                raise ValueError(f"rule-catalog path {_rc!r} collides with a core route")
            if _rc in seen_panel_paths:
                raise ValueError(f"rule-catalog path {_rc!r} collides with a panel path")
        routes.extend(
            make_rule_catalog_routes(
                active_rules=resolved_config.rule_catalog_rules,
                collected_rules=resolved_config.rule_catalog_collected_rules,
                authorize=_authorize,
                policies_root=resolved_config.rule_catalog_policies_root,
                remediation_root=resolved_config.rule_catalog_remediation_root,
                findings_provider=resolved_config.rule_catalog_findings_provider,
                findings_summary_provider=resolved_config.rule_catalog_findings_summary_provider,
            )
        )

    # Optional promotion-gate dashboard.
    if (
        resolved_config.promotion_gate_action_types
        and resolved_config.promotion_gate_source is not None
    ):
        from fdai.delivery.read_api.promotion_gates import (
            DEFAULT_ROUTE_PATH as _PG_PATH,
        )
        from fdai.delivery.read_api.promotion_gates import (
            make_promotion_gates_route,
        )

        if _PG_PATH in _CORE_ROUTE_PATHS:
            raise ValueError(f"promotion-gates path {_PG_PATH!r} collides with a core route")
        if _PG_PATH in seen_panel_paths:
            raise ValueError(f"promotion-gates path {_PG_PATH!r} collides with a panel path")
        routes.append(
            make_promotion_gates_route(
                action_types=resolved_config.promotion_gate_action_types,
                source=resolved_config.promotion_gate_source,
                authorize=_authorize,
            )
        )

    # Optional pantheon graph + workflows routes. Pantheon data is
    # in-memory and upstream-fixed, so the endpoints just serialize
    # the registry - no external inputs beyond a config flag.
    if resolved_config.expose_pantheon:
        from fdai.delivery.read_api.pantheon import (
            GRAPH_ROUTE_PATH as _PT_GRAPH_PATH,
        )
        from fdai.delivery.read_api.pantheon import (
            WORKFLOWS_ROUTE_PATH as _PT_WF_PATH,
        )
        from fdai.delivery.read_api.pantheon import (
            make_pantheon_graph_route,
            make_pantheon_workflows_route,
        )

        for _pt_path in (_PT_GRAPH_PATH, _PT_WF_PATH):
            if _pt_path in _CORE_ROUTE_PATHS:
                raise ValueError(f"pantheon path {_pt_path!r} collides with a core route")
            if _pt_path in seen_panel_paths:
                raise ValueError(f"pantheon path {_pt_path!r} collides with a panel path")
        routes.append(make_pantheon_graph_route(authorize=_authorize))
        routes.append(make_pantheon_workflows_route(authorize=_authorize))

    # Optional custom workflow authoring routes (palette + validate).
    # Read-only: the palette is a projection of the loaded ActionType
    # catalog, and validate is a pure function (no state, no PR).
    if resolved_config.workflow_authoring is not None:
        from fdai.delivery.read_api.workflow_authoring import (
            ACTION_TYPES_ROUTE_PATH as _WF_AT_PATH,
        )
        from fdai.delivery.read_api.workflow_authoring import (
            CATALOG_ROUTE_PATH as _WF_CAT_PATH,
        )
        from fdai.delivery.read_api.workflow_authoring import (
            VALIDATE_ROUTE_PATH as _WF_VAL_PATH,
        )
        from fdai.delivery.read_api.workflow_authoring import (
            make_action_types_route,
            make_workflow_catalog_route,
            make_workflow_validate_route,
        )

        for _wf_path in (_WF_AT_PATH, _WF_VAL_PATH, _WF_CAT_PATH):
            if _wf_path in _CORE_ROUTE_PATHS:
                raise ValueError(f"workflow authoring path {_wf_path!r} collides with a core route")
            if _wf_path in seen_panel_paths:
                raise ValueError(f"workflow authoring path {_wf_path!r} collides with a panel path")
        routes.append(
            make_action_types_route(config=resolved_config.workflow_authoring, authorize=_authorize)
        )
        routes.append(
            make_workflow_validate_route(
                config=resolved_config.workflow_authoring, authorize=_authorize
            )
        )
        routes.append(
            make_workflow_catalog_route(
                config=resolved_config.workflow_authoring, authorize=_authorize
            )
        )

    # Optional reporting subsystem (catalog + engine + format registry).
    # All routes are GET-only; reader-role gate; the composition root
    # owns the engine + registries so a fork adds datasources / widget
    # types / formats without editing this file.
    if resolved_config.reporting is not None:
        from fdai.delivery.read_api.reporting import build_reporting_routes

        routes.extend(
            build_reporting_routes(
                config=resolved_config.reporting,
                authorize=_authorize,
                core_paths=_CORE_ROUTE_PATHS,
                seen_extra_paths=seen_panel_paths,
            )
        )

    # Optional rule-fire trace viewer.
    if resolved_config.trace_reader is not None:
        from fdai.delivery.read_api.rule_fire_trace import (
            make_rule_fire_trace_route,
        )

        # Path contains a template so collision is on the literal prefix
        # ``/audit/`` rather than the full template - keep parity with
        # the core `/audit` list route (they are siblings, both GETs, so
        # no conflict).
        routes.append(
            make_rule_fire_trace_route(
                reader=resolved_config.trace_reader,
                authorize=_authorize,
            )
        )

    # Optional bitemporal snapshot route.
    if resolved_config.bitemporal_reader is not None:
        from fdai.delivery.read_api.bitemporal import make_bitemporal_route

        routes.append(
            make_bitemporal_route(
                reader=resolved_config.bitemporal_reader,
                authorize=_authorize,
            )
        )

    # Optional what-if replay route.
    if resolved_config.what_if_reader is not None and resolved_config.what_if_evaluators:
        from fdai.delivery.read_api.what_if import make_what_if_route

        routes.append(
            make_what_if_route(
                reader=resolved_config.what_if_reader,
                evaluators=dict(resolved_config.what_if_evaluators),
                authorize=_authorize,
            )
        )

    # Optional CommandDeck chat backend. Registered POST-only; the
    # backend is a read-only translator (see chat.py). Reader role is
    # required by ``authorize`` so the endpoint stays behind the same
    # RBAC gate as the snapshot routes.
    if resolved_config.chat is not None:
        from fdai.delivery.read_api.chat import (
            DEFAULT_ROUTE_PATH as _CHAT_PATH,
        )
        from fdai.delivery.read_api.chat import (
            describe_backend as _describe_backend,
        )
        from fdai.delivery.read_api.chat import (
            make_chat_health_route,
            make_chat_route,
            make_chat_stream_route,
        )

        if _CHAT_PATH in _CORE_ROUTE_PATHS:
            raise ValueError(f"chat path {_CHAT_PATH!r} collides with a core route")
        if _CHAT_PATH in seen_panel_paths:
            raise ValueError(f"chat path {_CHAT_PATH!r} collides with a panel path")
        routes.append(
            make_chat_route(
                backend=resolved_config.chat,
                authorize=_authorize,
            )
        )
        routes.append(
            make_chat_stream_route(
                backend=resolved_config.chat,
                authorize=_authorize,
            )
        )
        routes.append(
            make_chat_health_route(
                backend=resolved_config.chat,
                authorize=_authorize,
            )
        )
        # Loud, single-line startup log so the operator sees at a
        # glance whether the LLM narrator is wired.
        _desc = _describe_backend(resolved_config.chat)
        if _desc.get("available"):
            _LOGGER.warning(
                "CommandDeck chat backend ready: mode=%s model=%s endpoint=%s",
                _desc.get("mode"),
                _desc.get("model"),
                _desc.get("endpoint"),
            )
        else:
            _LOGGER.warning(
                "CommandDeck chat backend NOT wired - the FE will fall back "
                "to the deterministic answerer. Set FDAI_NARRATOR_* env vars "
                "or ship resolved-models.json to enable the LLM path."
            )

    # Optional console action-submit route. The ONE write-direction
    # conversational path: an operator command becomes a typed ActionProposal
    # published onto the raw event topic (pantheon judges/approves/executes).
    # Propose-never-execute; server-derived RBAC (Contributor+). Registered
    # only when a submitter is wired at composition root.
    if resolved_config.console_action is not None:
        from fdai.delivery.read_api.console_action import (
            DEFAULT_ACTION_PATH as _ACTION_PATH,
        )
        from fdai.delivery.read_api.console_action import (
            make_console_action_route,
        )

        if _ACTION_PATH in _CORE_ROUTE_PATHS:
            raise ValueError(f"action path {_ACTION_PATH!r} collides with a core route")
        routes.append(
            make_console_action_route(
                submitter=resolved_config.console_action,
                authorize_principal=_authorize_principal,
            )
        )
        _LOGGER.warning(
            "Console action-submit route wired at POST %s (propose-only, "
            "Contributor+ required); operator commands enter the typed pipeline.",
            _ACTION_PATH,
        )

    middleware: list[Middleware] = []
    # Baseline security headers on every response. Cheap defence in depth;
    # each header covers a class of well-known browser-side attacks
    # (MIME sniffing, clickjacking, cross-window leaks) that Starlette
    # does not add by default. `Cache-Control: no-store` prevents any
    # intermediary from caching audit / KPI payloads that reflect the
    # current control-plane state.
    middleware.append(
        Middleware(
            _SecurityHeadersMiddleware,
        )
    )
    if resolved_config.cors_allow_origins:
        # Console SPA cross-origin fetches. The base surface is GET-only;
        # POST is opened up ONLY when a chat backend is wired, and only
        # for the /chat translator (which never mutates state).
        allow_methods = ["GET"]
        if resolved_config.chat is not None:
            allow_methods.append("POST")
        middleware.append(
            Middleware(
                CORSMiddleware,
                allow_origins=list(resolved_config.cors_allow_origins),
                allow_methods=allow_methods,
                allow_headers=["authorization", "content-type"],
                allow_credentials=False,
            )
        )

    # Lifespan for the optional live emitter. Starlette collects
    # per-app resources here so uvicorn / hypercorn / granian all handle
    # startup + shutdown identically.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_app: Starlette):  # type: ignore[no-untyped-def]
        if live_emitter is not None:
            await live_emitter.start()
        # Warm the latency router (if wired) so GET /chat/health reports the
        # measured-fastest mini before the first operator turn. Fire-and-forget
        # so startup is never blocked on LLM round-trips.
        bench_task = None
        chat_backend = resolved_config.chat
        if _is_routed_chat_backend(chat_backend):
            import asyncio

            async def _warm_router() -> None:
                try:
                    chose = await chat_backend.benchmark()
                    _LOGGER.warning("CommandDeck router benchmarked - fastest candidate: %s", chose)
                except Exception as exc:  # noqa: BLE001 - best-effort warm-up
                    _LOGGER.warning("CommandDeck router benchmark failed: %s", exc)

            bench_task = asyncio.create_task(_warm_router())
        try:
            yield
        finally:
            if bench_task is not None:
                bench_task.cancel()
            if live_emitter is not None:
                await live_emitter.stop()

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


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _is_routed_chat_backend(backend: object) -> bool:
    """True when the chat backend is the latency-routed multi-candidate one.

    Lazy import keeps ``chat`` optional for builds that never wire a narrator.
    """
    if backend is None:
        return False
    from fdai.delivery.read_api.chat import LatencyRoutedChatBackend

    return isinstance(backend, LatencyRoutedChatBackend)


class _BadQueryError(ValueError):
    """Raised inside ``get_*`` when a query string is malformed.

    Caught locally and turned into a ``400`` response - the caller
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
