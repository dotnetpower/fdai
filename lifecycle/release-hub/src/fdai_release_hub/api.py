"""Bounded, loopback-only development API and same-origin static UI."""

from __future__ import annotations

import ipaddress
import logging
import sqlite3
from functools import partial
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from fdai_lifecycle_hub.remote_auth import RemoteAuth, secure_app
from fdai_release_hub.store import CatalogError, Change, ReleaseStore

MAX_BODY = 2 * 1024 * 1024
logger = logging.getLogger(__name__)


def create_app(
    store: ReleaseStore,
    *,
    static_dir: Path | None = None,
    remote_auth: RemoteAuth | None = None,
    remote_origin: str | None = None,
) -> Starlette:
    async def catalog(request: Request) -> Response:
        try:
            snapshot = await run_in_threadpool(store.snapshot)
            _, digest = store.export_snapshot(snapshot)
            return JSONResponse({**snapshot, "export_sha256": digest})
        except CatalogError as error:
            return JSONResponse({"error": str(error)}, status_code=error.status)

    async def export(request: Request) -> Response:
        try:
            raw, digest = await run_in_threadpool(store.export)
            return Response(raw, media_type="application/json", headers={"ETag": f'"{digest}"'})
        except CatalogError as error:
            return JSONResponse({"error": str(error)}, status_code=error.status)

    async def change(request: Request, *, action: str) -> Response:
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            return JSONResponse({"error": "Use application/json."}, status_code=415)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY:
                return JSONResponse({"error": "Request body is too large."}, status_code=413)
        try:
            payload = Change.model_validate_json(bytes(body))
            result = await run_in_threadpool(
                store.change,
                action,
                request.path_params["release_id"],
                payload,
                actor=request.state.operator if remote_auth else "local-operator",
            )
        except ValidationError:
            return JSONResponse(
                {"error": "Invalid fields. Check revision, confirmation, reason and manifest."},
                status_code=422,
            )
        except ValueError as error:
            status = error.status if isinstance(error, CatalogError) else 422
            message = str(error) if isinstance(error, CatalogError) else "Invalid Release manifest."
            return JSONResponse({"error": message}, status_code=status)
        return JSONResponse(result)

    routes = [
        Route("/auth/config", lambda request: JSONResponse({"profile": "local-development"})),
        Route(
            "/healthz",
            lambda request: JSONResponse(
                {
                    "status": "ok",
                    "mode": "remote"
                    if remote_origin
                    else ("remote-development" if remote_auth else "local-development"),
                }
            ),
        ),
        Route("/v1/catalog", catalog),
        Route("/v1/catalog/export", export),
    ]
    routes += [
        Route(
            f"/v1/releases/{{release_id}}/{action}",
            partial(change, action=action),
            methods=["POST"],
        )
        for action in ("register", "publish", "contribute", "recall")
    ]
    app = Starlette(routes=routes)
    if remote_auth is None and remote_origin is None:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])

    async def local_boundary(request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            local = (
                request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
            )
        except ValueError:
            local = False
        if remote_auth is None and remote_origin is None and not local:
            return JSONResponse({"error": "Release Hub is loopback-only."}, status_code=403)
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD") and origin is not None:
            expected = (
                remote_auth.origin
                if remote_auth
                else remote_origin or f"{request.url.scheme}://{request.url.netloc}"
            )
            if origin != expected:
                return JSONResponse(
                    {"error": "Cross-origin mutations are not allowed."}, status_code=403
                )
        try:
            response = await call_next(request)
        except (OSError, sqlite3.DatabaseError, SQLAlchemyError):
            logger.error("release_hub_storage_unavailable")
            return JSONResponse({"error": "Local storage is unavailable."}, status_code=503)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    app.add_middleware(BaseHTTPMiddleware, dispatch=local_boundary)
    if static_dir is not None and (static_dir / "index.html").is_file():
        app.routes.append(Mount("/assets", app=StaticFiles(directory=static_dir / "assets")))
        app.routes.append(Mount("/brand", app=StaticFiles(directory=static_dir / "brand")))

        async def index(request: Request) -> Response:
            if request.url.path.startswith("/v1/"):
                return JSONResponse({"error": "Unknown API route."}, status_code=404)
            return FileResponse(static_dir / "index.html")

        app.routes.append(Route("/{path:path}", index))
    return (
        secure_app(app, remote_auth, vendor=True, origin=remote_origin)
        if remote_auth is not None or remote_origin is not None
        else app
    )
