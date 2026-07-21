"""Allowlisted local proxy to an authoritative Entra-protected read API."""

from __future__ import annotations

import json
import posixpath
import re
from collections.abc import Mapping
from urllib.parse import unquote, urlsplit

import httpx
from starlette.types import ASGIApp, Receive, Scope, Send

AUTHORITATIVE_READ_API_ENV = "FDAI_AUTHORITATIVE_READ_API_BASE_URL"

_EXACT_PATHS: frozenset[str] = frozenset(
    {
        "/agents/stream",
        "/audit",
        "/automation-blueprints",
        "/browser-evidence",
        "/context-selection-comparisons",
        "/conversation-delivery",
        "/finops",
        "/hil-queue",
        "/incidents",
        "/kpi",
        "/kpi/autonomy",
        "/kpi/llm-cost",
        "/kpi/promotion-gates",
        "/live/stream",
        "/onboarding",
        "/operator-memory",
        "/rca",
        "/reports",
        "/reports/registry",
        "/scheduler-runs",
        "/scope",
        "/stewardship",
        "/views/process",
    }
)
_PREFIX_PATHS: tuple[str, ...] = ("/reports/", "/views/process/")
_FORWARDED_RESPONSE_HEADERS: frozenset[str] = frozenset(
    {"content-disposition", "content-type", "etag", "last-modified"}
)
_BEARER_PATTERN = re.compile(r"Bearer [A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)


class AuthoritativeReadProxy:
    """Stream allowlisted GET responses without forwarding cookies or redirects."""

    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = _validated_base_url(base_url)
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0),
            follow_redirects=False,
            trust_env=False,
        )

    def handles(self, path: str) -> bool:
        return _is_canonical_path(path) and (
            path in _EXACT_PATHS or any(path.startswith(prefix) for prefix in _PREFIX_PATHS)
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            raise RuntimeError("authoritative read proxy only handles HTTP requests")
        method = str(scope.get("method", "")).upper()
        path = str(scope.get("path", ""))
        if method != "GET" or not self.handles(path):
            raise RuntimeError("authoritative read proxy received a non-allowlisted request")
        authorization = _header(scope, b"authorization")
        if authorization is None or _BEARER_PATTERN.fullmatch(authorization) is None:
            await _json_error(send, 401, "authoritative read proxy requires a bearer token")
            return
        query = bytes(scope.get("query_string", b"")).decode("ascii")
        target = f"{self._base_url}{path}{f'?{query}' if query else ''}"
        response_started = False
        try:
            async with self._client.stream(
                "GET",
                target,
                headers={
                    "accept": _header(scope, b"accept") or "application/json",
                    "authorization": authorization,
                },
            ) as response:
                headers = [
                    (name.encode("latin-1"), value.encode("latin-1"))
                    for name, value in response.headers.items()
                    if name.lower() in _FORWARDED_RESPONSE_HEADERS
                ]
                headers.append((b"cache-control", b"no-store"))
                await send(
                    {
                        "type": "http.response.start",
                        "status": response.status_code,
                        "headers": headers,
                    }
                )
                response_started = True
                if response.is_stream_consumed:
                    await send(
                        {
                            "type": "http.response.body",
                            "body": response.content,
                            "more_body": True,
                        }
                    )
                else:
                    async for chunk in response.aiter_raw():
                        await send({"type": "http.response.body", "body": chunk, "more_body": True})
                await send({"type": "http.response.body", "body": b"", "more_body": False})
        except httpx.HTTPError as exc:
            if response_started:
                await send({"type": "http.response.body", "body": b"", "more_body": False})
                return
            await _json_error(
                send,
                503,
                f"authoritative read API is unreachable: {type(exc).__name__}",
            )

    async def aclose(self) -> None:
        await self._client.aclose()


class AuthoritativeReadProxyMiddleware:
    """Dispatch allowlisted GETs to the remote source before local routes."""

    def __init__(self, app: ASGIApp, *, proxy: AuthoritativeReadProxy) -> None:
        self._app = app
        self._proxy = proxy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and str(scope.get("method", "")).upper() == "GET"
            and self._proxy.handles(str(scope.get("path", "")))
        ):
            await self._proxy(scope, receive, send)
            return
        await self._app(scope, receive, send)


def authoritative_read_proxy_from_env(
    env: Mapping[str, str],
) -> AuthoritativeReadProxy | None:
    base_url = env.get(AUTHORITATIVE_READ_API_ENV, "").strip()
    return AuthoritativeReadProxy(base_url=base_url) if base_url else None


def _validated_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"{AUTHORITATIVE_READ_API_ENV} MUST be an absolute HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{AUTHORITATIVE_READ_API_ENV} MUST NOT contain credentials")
    if parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError(f"{AUTHORITATIVE_READ_API_ENV} MUST contain only an origin")
    return f"https://{parsed.netloc}"


def _is_canonical_path(path: str) -> bool:
    if not path.startswith("/") or "\\" in path or "?" in path or "#" in path:
        return False
    if any(ord(character) < 32 or ord(character) == 127 for character in path):
        return False
    if unquote(path) != path:
        return False
    return posixpath.normpath(path) == path


def _header(scope: Scope, name: bytes) -> str | None:
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name.lower() == name:
            return bytes(raw_value).decode("latin-1")
    return None


async def _json_error(send: Send, status: int, message: str) -> None:
    body = json.dumps({"error": {"status": status, "message": message}}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


__all__ = [
    "AUTHORITATIVE_READ_API_ENV",
    "AuthoritativeReadProxy",
    "AuthoritativeReadProxyMiddleware",
    "authoritative_read_proxy_from_env",
]
