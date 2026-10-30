"""Loopback Bootstrap surface; privileged work stays in the customer executor."""

from __future__ import annotations

import hmac
import secrets
import time
from pathlib import Path

from fdai_deployment_cli.bootstrap_channel import (
    read_status,
    submit_decision,
    submit_request,
)
from fdai_deployment_cli.contracts import load_json_object
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp

MAX_BODY_BYTES = 16 * 1024
SESSION_SECONDS = 8 * 60 * 60
ASSETS = Path(__file__).with_name("setup_ui")
COOKIE_NAME = "fdai_bootstrap_session"


def _matches(supplied: str, expected: str) -> bool:
    return hmac.compare_digest(supplied.encode(), expected.encode())


async def _body(request: Request) -> dict[str, object]:
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        raise ValueError("Send an application/json object.")
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_BODY_BYTES:
            raise ValueError("Bootstrap request exceeds the supported size.")
    return load_json_object(
        bytes(content), label="Bootstrap request", max_bytes=MAX_BODY_BYTES, strict=True
    )


class _Boundary(BaseHTTPMiddleware):
    def __init__(
        self, app: ASGIApp, *, origin: str, session: str, csrf: str, expires: float
    ) -> None:
        super().__init__(app)
        self.origin = origin
        self.host = origin.removeprefix("http://")
        self.session = session
        self.csrf = csrf
        self.expires = expires

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if (
            request.headers.get("host") != self.host
            or request.client is None
            or request.client.host not in {"127.0.0.1", "::1"}
        ):
            return JSONResponse({"error": "Bootstrap accepts loopback requests only."}, 403)
        if request.headers.get("origin") not in {None, self.origin}:
            return JSONResponse({"error": "Cross-origin Bootstrap access is not allowed."}, 403)
        if request.headers.get("sec-fetch-site") not in {None, "same-origin", "none"}:
            return JSONResponse({"error": "Cross-site Bootstrap access is not allowed."}, 403)
        path = request.url.path
        if path.startswith("/setup/api/") and path != "/setup/api/session":
            supplied = request.cookies.get(COOKIE_NAME, "")
            if time.monotonic() >= self.expires or not _matches(supplied, self.session):
                return JSONResponse({"error": "Open Bootstrap from its local launcher."}, 401)
            if request.method != "GET" and (
                request.headers.get("origin") != self.origin
                or not _matches(request.headers.get("x-fdai-csrf", ""), self.csrf)
            ):
                return JSONResponse({"error": "Bootstrap request verification failed."}, 403)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": (
                    "default-src 'none'; script-src 'self'; style-src 'self'; "
                    "connect-src 'self'; img-src 'self'; base-uri 'none'; "
                    "frame-ancestors 'none'; form-action 'self'"
                ),
            }
        )
        return response


def create_setup_app(
    state_dir: Path, *, origin: str, launch_token: str, assets: Path = ASSETS
) -> Starlette:
    """Create an isolated Bootstrap API without opening the Hub or Runtime database."""
    if not origin.startswith("http://127.0.0.1:"):
        raise ValueError("Bootstrap requires an exact IPv4 loopback origin.")
    try:
        port = int(origin.rsplit(":", 1)[1])
    except ValueError as error:
        raise ValueError("Bootstrap requires a valid loopback port.") from error
    if not 1 <= port <= 65535 or origin != f"http://127.0.0.1:{port}":
        raise ValueError("Bootstrap requires an exact IPv4 loopback origin.")
    if len(launch_token) < 32:
        raise ValueError("Bootstrap requires a strong ephemeral launch token.")
    session = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    expires = time.monotonic() + SESSION_SECONDS
    token_consumed = False

    async def exchange(request: Request) -> Response:
        nonlocal token_consumed
        if request.headers.get("origin") != origin:
            return JSONResponse({"error": "Open Bootstrap from its local launcher."}, 403)
        try:
            body = await _body(request)
        except ValueError as error:
            return JSONResponse({"error": str(error)}, 400)
        supplied = body.get("token")
        if (
            token_consumed
            or time.monotonic() >= expires
            or set(body) != {"token"}
            or not isinstance(supplied, str)
            or not _matches(supplied, launch_token)
        ):
            return JSONResponse({"error": "Bootstrap launch link is invalid or already used."}, 401)
        token_consumed = True
        response = JSONResponse({"authenticated": True})
        response.set_cookie(
            COOKIE_NAME,
            session,
            max_age=SESSION_SECONDS,
            httponly=True,
            samesite="strict",
            path="/setup",
        )
        return response

    async def status(request: Request) -> Response:
        try:
            result = await run_in_threadpool(read_status, state_dir)
        except (ValueError, OSError):
            return JSONResponse(
                {"error": "Setup state is unavailable; preserve it and inspect local diagnostics."},
                409,
            )
        return JSONResponse({**result, "csrf_token": csrf})

    async def action(request: Request) -> Response:
        try:
            body = await _body(request)
            name, payload = body.get("action"), body.get("payload")
            if set(body) != {"action", "payload"} or not isinstance(name, str):
                raise ValueError("Specify one Bootstrap action and its payload.")
            if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
                raise ValueError("Bootstrap payload must be a JSON object.")
            result = await run_in_threadpool(submit_request, state_dir, name, payload)
        except ValueError as error:
            return JSONResponse({"error": str(error)}, 409)
        except OSError:
            return JSONResponse(
                {"error": "Cannot retain setup request; check private storage."}, 503
            )
        return JSONResponse(result, 202)

    async def decision(request: Request) -> Response:
        try:
            body = await _body(request)
            result = await run_in_threadpool(submit_decision, state_dir, body)
        except ValueError as error:
            return JSONResponse({"error": str(error)}, 409)
        except OSError:
            return JSONResponse({"error": "Cannot retain decision; check private storage."}, 503)
        return JSONResponse(result, 202)

    async def page(request: Request) -> Response:
        name = request.path_params.get("asset", "index.html")
        if name not in {"index.html", "setup.css", "setup.js"}:
            return Response(status_code=404)
        return FileResponse(assets / name)

    app = Starlette(
        routes=[
            Route("/setup/api/session", exchange, methods=["POST"]),
            Route("/setup/api/status", status),
            Route("/setup/api/actions", action, methods=["POST"]),
            Route("/setup/api/decisions", decision, methods=["POST"]),
            Route("/setup", page),
            Route("/setup/", page),
            Route("/setup/{asset}", page),
        ]
    )
    app.add_middleware(_Boundary, origin=origin, session=session, csrf=csrf, expires=expires)
    return app
