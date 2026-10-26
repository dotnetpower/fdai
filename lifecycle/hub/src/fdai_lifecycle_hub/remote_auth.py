"""Direct Entra access-token verification; proxy principal headers grant no authority."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta
from threading import Condition
from typing import Any, Literal
from urllib.parse import quote, urlsplit

import httpx
import jwt
from jwt import PyJWK
from jwt.exceptions import PyJWTError
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from fdai_lifecycle_hub.configuration_keys import _validate_signing_public_key
from fdai_lifecycle_hub.signing import installation_key_id

logger = logging.getLogger(__name__)
# The signed export and the signed roles that vouch for it share one read policy.
CATALOG_READ_PATHS = frozenset({"/v1/catalog/export", "/v1/catalog/metadata"})
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


class DevelopmentRecoveryAuthorization(BaseModel):
    """Protected, expiring authority for one exact development identity recovery."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    profile: Literal["full-authority-development"]
    installation_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    scope: str = Field(min_length=1, max_length=256)
    operator_id: str = Field(min_length=1)
    previous_identity_key_id: str = Field(pattern=r"^installation-[0-9a-f]{16}$")
    replacement_identity_public_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorized_at: AwareDatetime
    authorization_expires_at: AwareDatetime
    allow_single_owner_configuration_approval: Literal[True]
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def validate_recovery(self) -> DevelopmentRecoveryAuthorization:
        replacement = bytes.fromhex(self.replacement_identity_public_key)
        _validate_signing_public_key(replacement)
        if self.previous_identity_key_id == installation_key_id(replacement) or not timedelta(
            0
        ) < self.authorization_expires_at - self.authorized_at <= timedelta(days=14):
            raise ValueError("Development recovery authorization is invalid.")
        return self

    @property
    def replacement_identity_key_id(self) -> str:
        return installation_key_id(bytes.fromhex(self.replacement_identity_public_key))

    def is_current(self, *, installation_id: str, operator_id: str, now: datetime) -> bool:
        return (
            installation_id == self.installation_id
            and operator_id == self.operator_id
            and self.authorized_at <= now < self.authorization_expires_at
        )


MAX_REDIRECT_HOSTS = 4
_HOSTNAME = re.compile(
    r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$"
)


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
    # Public Release Hub export and metadata-only request intake; vendor management stays private.
    public_catalog_export: bool = False
    agent_principals: tuple[AgentPrincipal, ...] = ()
    development_recovery: DevelopmentRecoveryAuthorization | None = None
    # Former hostnames whose GET and HEAD requests are redirected to `origin`. They never serve.
    redirect_hosts: tuple[str, ...] = ()

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
        if (
            len(self.redirect_hosts) > MAX_REDIRECT_HOSTS
            or len(set(self.redirect_hosts)) != len(self.redirect_hosts)
            or any(
                _HOSTNAME.fullmatch(host) is None or host == parsed.hostname
                for host in self.redirect_hosts
            )
        ):
            raise ValueError("Redirect hosts must be distinct DNS names other than the origin.")
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
        if self.development_recovery is not None and (
            self.development_recovery.operator_id not in self.operator_ids
            or self.profile != "remote-development"
        ):
            raise ValueError("Development recovery requires one configured operator identity.")
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


class _RedirectFormerHosts:
    """Send GET and HEAD for a former hostname to the configured origin and nothing else.

    The target is the fixed origin plus the request's own path, so no request value chooses the
    destination host. Every other method and path keeps the ordinary host check and is refused.
    """

    def __init__(self, app: ASGIApp, *, hosts: frozenset[str], origin: str) -> None:
        self._app = app
        self._hosts = hosts
        self._origin = origin

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in ("GET", "HEAD"):
            host = ""
            for name, value in scope["headers"]:
                if name == b"host":
                    host = value.decode("latin-1").rsplit(":", 1)[0].lower()
                    break
            if host in self._hosts:
                query = scope.get("query_string", b"").decode("latin-1")
                location = (
                    self._origin + quote(scope["path"], safe="/") + ("?" + query if query else "")
                )
                await Response(
                    status_code=308,
                    headers={"Location": location, "Cache-Control": "no-store"},
                )(scope, receive, send)
                return
        await self._app(scope, receive, send)


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
    if vendor and config.development_recovery is not None:
        raise ValueError("Release Hub does not accept development recovery authority.")
    if config.public_catalog_export and not vendor:
        raise ValueError("Only Release Hub may serve a public catalog export.")
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
        public_export = (
            vendor
            and config.public_catalog_export
            and path in CATALOG_READ_PATHS
            and request.method in {"GET", "HEAD"}
        )
        public_intake = (
            vendor
            and config.public_catalog_export
            and path == "/v1/deployment-requests"
            and request.method == "POST"
        )
        if public_intake and (
            request.headers.get("origin") not in (None, config.origin)
            or request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return _denied(403, "untrusted_mutation")
        if (path.startswith("/v1/") or path == "/v1") and not (public_export or public_intake):
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
                    and path in CATALOG_READ_PATHS
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
                and path.endswith(
                    ("/state", "/reports", "/plan", "/enrollment", "/enrollment-request")
                )
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
    if config.redirect_hosts:
        app.add_middleware(
            _RedirectFormerHosts, hosts=frozenset(config.redirect_hosts), origin=config.origin
        )
    return app


def _agent_allowed(config: RemoteAuth, claims: dict[str, Any], method: str, path: str) -> bool:
    match = re.fullmatch(
        r"/v1/installations/([A-Za-z0-9][A-Za-z0-9._-]{0,127})/"
        r"(plan|state|native-proofs|native-transition-completion|enrollment-request|"
        r"plans/[A-Za-z0-9][A-Za-z0-9._-]{0,127}/reports|"
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
