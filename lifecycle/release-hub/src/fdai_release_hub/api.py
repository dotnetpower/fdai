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
from fdai_release_hub.store import (
    CapabilityChange,
    CatalogConfirmation,
    CatalogError,
    Change,
    ReleaseStore,
)

MAX_BODY = 2 * 1024 * 1024
MAX_CATALOG_VIEW_BYTES = 16 * 1024 * 1024
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
            body = await run_in_threadpool(store.catalog_view, MAX_CATALOG_VIEW_BYTES)
            return Response(body, media_type="application/json")
        except CatalogError as error:
            return JSONResponse({"error": str(error)}, status_code=error.status)

    async def export(request: Request) -> Response:
        try:
            signed = await run_in_threadpool(store.signed_export)
            etag = f'"{signed.digest}"'
            offered = {
                token.strip().removeprefix("W/")
                for token in request.headers.get("if-none-match", "").split(",")
            }
            if etag in offered:
                return Response(status_code=304, headers={"ETag": etag})
            return Response(
                signed.raw,
                media_type="application/json",
                headers={
                    "ETag": etag,
                    "X-FDAI-Export-Signature": signed.signature,
                    "X-FDAI-Export-Key-Id": signed.key_id,
                },
            )
        except CatalogError as error:
            return JSONResponse({"error": str(error)}, status_code=error.status)

    async def metadata(request: Request) -> Response:
        try:
            signed = await run_in_threadpool(store.signed_metadata)
        except CatalogError as error:
            return JSONResponse({"error": str(error)}, status_code=error.status)
        etag = f'"{signed.digest}"'
        offered = {
            token.strip().removeprefix("W/")
            for token in request.headers.get("if-none-match", "").split(",")
        }
        if etag in offered:
            return Response(status_code=304, headers={"ETag": etag})
        return Response(signed.raw, media_type="application/json", headers={"ETag": etag})

    async def change(request: Request, *, action: str) -> Response:
        media_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
        if media_type != "application/json":
            return JSONResponse({"error": "Use application/json."}, status_code=415)
        content_encoding = request.headers.get("content-encoding", "identity").strip().lower()
        if content_encoding != "identity":
            return JSONResponse(
                {"error": "Encoded request bodies are not supported."}, status_code=415
            )
        declared_length = request.headers.get("content-length")
        if declared_length is not None:
            try:
                content_length = int(declared_length)
            except ValueError:
                return JSONResponse(
                    {"error": "Content-Length must be an integer."}, status_code=400
                )
            if content_length < 0:
                return JSONResponse(
                    {"error": "Content-Length cannot be negative."}, status_code=400
                )
            if content_length > MAX_BODY:
                return JSONResponse({"error": "Request body is too large."}, status_code=413)
        body = bytearray()
        async for chunk in request.stream():
            if len(chunk) > MAX_BODY - len(body):
                return JSONResponse({"error": "Request body is too large."}, status_code=413)
            body.extend(chunk)
        try:
            actor = request.state.operator if remote_auth else "local-operator"
            if action == "renew":
                renewal = CatalogConfirmation.model_validate_json(bytes(body))
                result = await run_in_threadpool(store.renew, renewal, actor=actor)
            elif "capability_id" in request.path_params:
                cap_payload = CapabilityChange.model_validate_json(bytes(body))
                result = await run_in_threadpool(
                    store.change_capability,
                    action,
                    request.path_params["capability_id"],
                    cap_payload,
                    actor=actor,
                )
            else:
                payload = Change.model_validate_json(bytes(body))
                result = await run_in_threadpool(
                    store.change,
                    action,
                    request.path_params["release_id"],
                    payload,
                    actor=actor,
                )
        except ValidationError:
            return JSONResponse(
                {"error": "Invalid fields. Check revision, confirmation, reason and manifest."},
                status_code=422,
            )
        except ValueError as error:
            status = error.status if isinstance(error, CatalogError) else 422
            message = (
                str(error)
                if isinstance(error, CatalogError)
                else (
                    "Invalid catalog renewal input."
                    if action == "renew"
                    else "Invalid Release manifest."
                )
            )
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
        Route("/v1/catalog/metadata", metadata),
        Route("/v1/catalog/renew", partial(change, action="renew"), methods=["POST"]),
    ]
    routes += [
        Route(
            f"/v1/releases/{{release_id}}/{action}",
            partial(change, action=action),
            methods=["POST"],
        )
        for action in ("register", "publish", "contribute", "recall")
    ]
    routes += [
        Route(
            f"/v1/capabilities/{{capability_id:path}}/{action}",
            partial(change, action=action),
            methods=["POST"],
        )
        for action in ("recall", "lift")
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
