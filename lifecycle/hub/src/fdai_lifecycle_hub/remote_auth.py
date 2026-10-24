"""Direct Entra access-token verification; proxy principal headers grant no authority."""

from __future__ import annotations

import json
import logging
import re
import time
from threading import Condition
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
import jwt
from jwt import PyJWK
from jwt.exceptions import PyJWTError
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

logger = logging.getLogger(__name__)
MAX_JWKS_BYTES = 256 * 1024
JWKS_CACHE_SECONDS = 300
MAX_JWKS_STALE_SECONDS = 900
UNKNOWN_KID_REFRESH_SECONDS = 30


class AgentPrincipal(BaseModel):
    """A separately provisioned workload identity bound to one installation."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    installation_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    object_id: str = Field(min_length=1)
    client_id: str = Field(min_length=1)


class RemoteAuth(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    profile: Literal["remote-development"]
    tenant_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    audience: str = Field(min_length=1)
    origin: str
    spa_client_id: str = Field(min_length=1)
    operator_scope: str = Field(min_length=1)
    operator_ids: frozenset[str] = Field(min_length=1)
    service_object_id: str | None = None
    service_client_id: str | None = None
    service_role: str = "Catalog.Read"
    agent_principals: tuple[AgentPrincipal, ...] = ()

    @model_validator(mode="after")
    def validate_boundary(self) -> RemoteAuth:
        parsed = urlsplit(self.origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.port not in (None, 443)
        ):
            raise ValueError("Remote origin must be an exact HTTPS origin without a path.")
        if bool(self.service_object_id) != bool(self.service_client_id):
            raise ValueError("Service object and client identities must be supplied together.")
        for field in ("installation_id", "object_id", "client_id"):
            values = [getattr(principal, field) for principal in self.agent_principals]
            if len(values) != len(set(values)):
                raise ValueError("Agent identity and installation bindings must be unique.")
        if any(
            principal.object_id in self.operator_ids
            or principal.object_id == self.service_object_id
            or principal.client_id in {self.spa_client_id, self.service_client_id}
            for principal in self.agent_principals
        ):
            raise ValueError(
                "Agent identities must be distinct from operator and catalog identities."
            )
        return self

    @property
    def issuer(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"


class EntraVerifier:
    def __init__(self, config: RemoteAuth) -> None:
        self.config = config
        self._keys: dict[str, PyJWK] = {}
        self._refresh_after = 0.0
        self._unknown_kid_refresh_after = 0.0
        self._last_successful_refresh: float | None = None
        self._refresh_condition = Condition()
        self._refreshing = False

    def _refresh(self) -> None:
        url = f"https://login.microsoftonline.com/{self.config.tenant_id}/discovery/v2.0/keys"
        raw = bytearray()
        deadline = time.monotonic() + 5
        with httpx.stream(
            "GET",
            url,
            headers={"Accept-Encoding": "identity"},
            timeout=5,
            follow_redirects=False,
            trust_env=False,
        ) as response:
            response.raise_for_status()
            if response.headers.get("content-encoding", "identity") != "identity":
                raise ValueError("Compressed signing-key responses are not accepted.")
            for chunk in response.iter_raw():
                raw.extend(chunk)
                if len(raw) > MAX_JWKS_BYTES or time.monotonic() >= deadline:
                    raise ValueError("Entra signing-key response exceeded its bound.")
        body = _strict_json(raw)
        if not isinstance(body, dict) or not isinstance(body.get("keys"), list):
            raise ValueError("Entra signing-key response is invalid.")
        keys = {}
        for item in body["keys"]:
            if not isinstance(item, dict) or not isinstance(item.get("kid"), str):
                raise ValueError("Entra signing-key entry is invalid.")
            if item.get("kty") == "RSA" and item.get("use", "sig") == "sig":
                if item["kid"] in keys:
                    raise ValueError("Entra signing-key response has a duplicate key id.")
                keys[item["kid"]] = PyJWK.from_dict(item, algorithm="RS256")
        if not keys:
            raise ValueError("Entra signing-key response has no supported key.")
        self._keys = keys
        refreshed_at = time.monotonic()
        self._last_successful_refresh = refreshed_at
        self._refresh_after = refreshed_at + JWKS_CACHE_SECONDS
        self._unknown_kid_refresh_after = refreshed_at + UNKNOWN_KID_REFRESH_SECONDS

    def _stale_keys_usable(self, now: float) -> bool:
        return (
            bool(self._keys)
            and self._last_successful_refresh is not None
            and now < self._last_successful_refresh + MAX_JWKS_STALE_SECONDS
        )

    def _refresh_for(self, kid: str) -> None:
        """Single-flight a due refresh and briefly retain valid keys when refresh fails."""

        while True:
            with self._refresh_condition:
                now = time.monotonic()
                due = now >= self._refresh_after or (
                    kid not in self._keys and now >= self._unknown_kid_refresh_after
                )
                if not due:
                    if self._keys and not self._stale_keys_usable(now):
                        raise ValueError("Entra signing keys exceeded their stale lifetime.")
                    return
                if self._refreshing:
                    completed = self._refresh_condition.wait_for(
                        lambda: not self._refreshing, timeout=5
                    )
                    if not completed:
                        raise ValueError("Entra signing-key refresh exceeded its bound.")
                    continue
                self._refreshing = True
                break
        try:
            self._refresh()
        except (httpx.HTTPError, PyJWTError, KeyError, ValueError) as error:
            failed_at = time.monotonic()
            retry_at = failed_at + UNKNOWN_KID_REFRESH_SECONDS
            with self._refresh_condition:
                self._refresh_after = retry_at
                self._unknown_kid_refresh_after = retry_at
            logger.warning("hub_jwks_refresh_failed error=%s", type(error).__name__)
            if not self._keys:
                raise
            if not self._stale_keys_usable(failed_at):
                raise ValueError("Entra signing keys exceeded their stale lifetime.") from error
        finally:
            with self._refresh_condition:
                self._refreshing = False
                self._refresh_condition.notify_all()

    def verify(self, token: str) -> dict[str, Any]:
        if len(token) > 16 * 1024:
            raise ValueError("Access token is too large.")
        kid = jwt.get_unverified_header(token).get("kid")
        if not isinstance(kid, str):
            raise ValueError("Access token signing key is not trusted.")
        self._refresh_for(kid)
        if kid not in self._keys:
            raise ValueError("Access token signing key is not trusted.")
        claims = jwt.decode(
            token,
            self._keys[kid].key,
            algorithms=["RS256"],
            audience=self.config.audience,
            issuer=self.config.issuer,
            options={"require": ["exp", "iat", "nbf", "iss", "aud", "tid", "oid", "sub"]},
        )
        if claims["tid"] != self.config.tenant_id or claims.get("ver") != "2.0":
            raise ValueError("Access token tenant or version does not match.")
        if not all(isinstance(claims.get(name), str) for name in ("oid", "sub", "azp")):
            raise ValueError("Access token principal binding is invalid.")
        return claims


def _strict_json(raw: bytes | bytearray) -> object:
    """Decode a JWKS as unambiguous UTF-8 JSON."""

    try:
        return json.loads(
            bytes(raw).decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise ValueError("Entra signing-key response is invalid.") from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError("non-finite number")


def secure_app(
    app: Starlette, config: RemoteAuth | None, *, vendor: bool, origin: str | None = None
) -> Starlette:
    if config is None:
        if origin is None:
            raise ValueError("Remote serving requires an explicit HTTPS origin.")
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.port not in (None, 443)
        ):
            raise ValueError("Remote serving requires an exact HTTPS origin.")

        async def unavailable_config(request: Request) -> Response:
            return JSONResponse(
                {
                    "profile": "remote-unconfigured",
                    "origin": origin,
                    "product": "release" if vendor else "lifecycle",
                    "management": "unavailable",
                    "reason": "operator_auth_not_configured",
                },
                headers={"Cache-Control": "no-store"},
            )

        async def unavailable(request: Request, call_next: RequestResponseEndpoint) -> Response:
            if request.url.path == "/v1" or request.url.path.startswith("/v1/"):
                logger.warning("hub_management_unavailable reason=operator_auth_not_configured")
                return _denied(503, "operator_auth_not_configured")
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
            )
            return response

        app.routes.insert(0, Route("/auth/config", unavailable_config))
        app.add_middleware(BaseHTTPMiddleware, dispatch=unavailable)
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=[parsed.hostname])
        return app

    verifier = EntraVerifier(config)
    if vendor and config.agent_principals:
        raise ValueError("Release Hub does not accept Agent principals.")
    app.state.entra_verifier = verifier

    async def auth_config(request: Request) -> Response:
        return JSONResponse(
            {
                "profile": config.profile,
                "clientId": config.spa_client_id,
                "authority": f"https://login.microsoftonline.com/{config.tenant_id}",
                "scope": f"api://{config.audience}/{config.operator_scope}",
                "origin": config.origin,
            },
            headers={"Cache-Control": "no-store"},
        )

    app.routes.insert(0, Route("/auth/config", auth_config))
    hostname = urlsplit(config.origin).hostname
    if hostname is None:
        raise ValueError("Remote origin requires a hostname.")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[hostname])

    async def boundary(request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if path.startswith("/v1/") or path == "/v1":
            authorization = request.headers.get("authorization", "")
            if not authorization.startswith("Bearer "):
                return _denied(401, "authentication_required")
            try:
                claims = await run_in_threadpool(verifier.verify, authorization[7:])
            except (jwt.PyJWTError, ValueError, KeyError, httpx.HTTPError):
                return _denied(401, "invalid_access_token")
            service = "scp" not in claims
            if service:
                allowed = (
                    vendor
                    and request.method in {"GET", "HEAD"}
                    and path == "/v1/catalog/export"
                    and config.service_object_id is not None
                    and claims.get("oid") == config.service_object_id
                    and claims.get("azp") == config.service_client_id
                    and _application_identity(claims)
                    and isinstance(claims.get("roles"), list)
                    and config.service_role in claims["roles"]
                )
                if not vendor:
                    allowed = _agent_allowed(config, claims, request.method, path)
            else:
                allowed = (
                    claims.get("oid") in config.operator_ids
                    and claims.get("azp") == config.spa_client_id
                    and isinstance(claims.get("scp"), str)
                    and config.operator_scope in claims["scp"].split()
                )
            if (
                not vendor
                and not service
                and path.endswith(("/state", "/reports", "/plan", "/enrollment"))
            ):
                allowed = False
            if not allowed:
                return _denied(403, "principal_not_authorized")
            if request.method not in {"GET", "HEAD"}:
                if (
                    request.headers.get("origin") not in (None, config.origin)
                    or request.headers.get("sec-fetch-site") == "cross-site"
                    or request.headers.get("content-type", "").split(";")[0] != "application/json"
                ):
                    return _denied(403, "untrusted_mutation")
            request.state.principal = claims["oid"]
            if not service or vendor:
                request.state.operator = claims["oid"]
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self' https://login.microsoftonline.com; frame-src "
            "https://login.microsoftonline.com; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    app.add_middleware(BaseHTTPMiddleware, dispatch=boundary)
    return app


def _agent_allowed(config: RemoteAuth, claims: dict[str, Any], method: str, path: str) -> bool:
    match = re.fullmatch(
        r"/v1/installations/([A-Za-z0-9][A-Za-z0-9._-]{0,127})/"
        r"(plan|state|native-proofs|plans/[A-Za-z0-9][A-Za-z0-9._-]{0,127}/reports|"
        r"artifacts/(?:release|configuration)/[0-9a-f]{64})",
        path,
        flags=re.ASCII,
    )
    if match is None:
        return False
    installation, operation = match.groups()
    return (
        method
        in (
            {"GET", "HEAD"}
            if operation == "plan" or operation.startswith("artifacts/")
            else {"POST"}
        )
        and _application_identity(claims)
        and isinstance(claims.get("roles"), list)
        and "Agent.Access" in claims["roles"]
        and any(
            principal.installation_id == installation
            and principal.object_id == claims["oid"]
            and principal.client_id == claims["azp"]
            for principal in config.agent_principals
        )
    )


def _application_identity(claims: dict[str, Any]) -> bool:
    """Accept v2 application tokens whose optional identity-type claim is omitted."""
    return claims.get("idtyp") in (None, "app")


def _denied(status: int, reason: str) -> Response:
    logger.warning("hub_access_denied reason=%s", reason)
    return JSONResponse(
        {"error": reason}, status_code=status, headers={"Cache-Control": "no-store"}
    )
