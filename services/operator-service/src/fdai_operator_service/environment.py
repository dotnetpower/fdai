"""Validated environment contract for the independent Operator process."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from fdai_service_contracts import OperatorRole

HOST_ENV = "FDAI_OPERATOR_SERVICE_HOST"
PORT_ENV = "FDAI_OPERATOR_SERVICE_PORT"
TENANT_ENV = "FDAI_ENTRA_TENANT_ID"
AUDIENCE_ENV = "FDAI_API_AUDIENCE"
ISSUER_ENV = "FDAI_ENTRA_ISSUER"
JWKS_URI_ENV = "FDAI_ENTRA_JWKS_URI"
CORS_ORIGINS_ENV = "FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS"
DATABASE_URL_ENV = "FDAI_DATABASE_URL"
DATABASE_ROLE_ENV = "FDAI_DATABASE_ROLE"
DATABASE_STATEMENT_TIMEOUT_ENV = "FDAI_OPERATOR_DATABASE_STATEMENT_TIMEOUT_MS"
DATABASE_CONNECT_TIMEOUT_ENV = "FDAI_OPERATOR_DATABASE_CONNECT_TIMEOUT_S"
EXPECTED_DATABASE_ROLE = "fdai_operator"
DEFAULT_HOST = "0.0.0.0"  # noqa: S104 - Container ingress terminates external HTTPS.
DEFAULT_PORT = 8000
DEFAULT_DATABASE_STATEMENT_TIMEOUT_MS = 20_000
DEFAULT_DATABASE_CONNECT_TIMEOUT_S = 10

GROUP_ENV: Mapping[OperatorRole, str] = MappingProxyType(
    {
        OperatorRole.READER: "FDAI_RBAC_READERS_GROUP_ID",
        OperatorRole.CONTRIBUTOR: "FDAI_RBAC_CONTRIBUTORS_GROUP_ID",
        OperatorRole.APPROVER: "FDAI_RBAC_APPROVERS_GROUP_ID",
        OperatorRole.OWNER: "FDAI_RBAC_OWNERS_GROUP_ID",
        OperatorRole.BREAK_GLASS: "FDAI_RBAC_BREAK_GLASS_GROUP_ID",
    }
)


class OperatorServiceConfigurationError(ValueError):
    """Raised before provider loading when service configuration is invalid."""


@dataclass(frozen=True, slots=True)
class OperatorEnvironment:
    """Hold immutable production HTTP and human-identity configuration."""

    values: Mapping[str, str]
    host: str
    port: int
    tenant_id: str
    audience: str
    issuer: str
    jwks_uri: str
    group_ids: Mapping[OperatorRole, str]
    cors_allow_origins: tuple[str, ...]
    database_url: str | None
    database_role: str | None
    database_statement_timeout_ms: int
    database_connect_timeout_s: int

    @classmethod
    def parse(cls, environ: Mapping[str, str]) -> OperatorEnvironment:
        """Validate listener, Entra, RBAC, and CORS settings before provider use."""
        values = dict(environ)
        host = values.get(HOST_ENV, DEFAULT_HOST).strip()
        if not host:
            raise OperatorServiceConfigurationError(f"{HOST_ENV} MUST be non-empty")

        raw_port = values.get(PORT_ENV, str(DEFAULT_PORT)).strip()
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise OperatorServiceConfigurationError(f"{PORT_ENV} MUST be an integer") from exc
        if not 1 <= port <= 65535:
            raise OperatorServiceConfigurationError(f"{PORT_ENV} MUST be between 1 and 65535")

        tenant_id = _require(values, TENANT_ENV)
        audience = _require(values, AUDIENCE_ENV)
        issuer = values.get(ISSUER_ENV, "").strip() or (
            f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        )
        jwks_uri = values.get(JWKS_URI_ENV, "").strip() or (
            f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        )
        group_ids = {role: _require(values, key) for role, key in GROUP_ENV.items()}
        if len(set(group_ids.values())) != len(group_ids):
            raise OperatorServiceConfigurationError("Operator RBAC group IDs MUST be unique")

        cors_allow_origins = tuple(
            origin.strip()
            for origin in values.get(CORS_ORIGINS_ENV, "").split(",")
            if origin.strip()
        )
        if "*" in cors_allow_origins:
            raise OperatorServiceConfigurationError(
                f"{CORS_ORIGINS_ENV} MUST NOT contain a wildcard origin"
            )

        database_url = values.get(DATABASE_URL_ENV, "").strip() or None
        database_role = values.get(DATABASE_ROLE_ENV, "").strip() or None
        if database_url is None and database_role is not None:
            raise OperatorServiceConfigurationError(
                f"{DATABASE_ROLE_ENV} MUST be unset when {DATABASE_URL_ENV} is unset"
            )
        if database_url is not None and database_role != EXPECTED_DATABASE_ROLE:
            raise OperatorServiceConfigurationError(
                f"{DATABASE_ROLE_ENV} MUST be {EXPECTED_DATABASE_ROLE}"
            )
        database_statement_timeout_ms = _positive_int(
            values,
            DATABASE_STATEMENT_TIMEOUT_ENV,
            DEFAULT_DATABASE_STATEMENT_TIMEOUT_MS,
        )
        database_connect_timeout_s = _positive_int(
            values,
            DATABASE_CONNECT_TIMEOUT_ENV,
            DEFAULT_DATABASE_CONNECT_TIMEOUT_S,
        )

        return cls(
            values=MappingProxyType(values),
            host=host,
            port=port,
            tenant_id=tenant_id,
            audience=audience,
            issuer=issuer,
            jwks_uri=jwks_uri,
            group_ids=MappingProxyType(group_ids),
            cors_allow_origins=cors_allow_origins,
            database_url=database_url,
            database_role=database_role,
            database_statement_timeout_ms=database_statement_timeout_ms,
            database_connect_timeout_s=database_connect_timeout_s,
        )


def _require(environ: Mapping[str, str], key: str) -> str:
    value = environ.get(key, "").strip()
    if not value:
        raise OperatorServiceConfigurationError(f"{key} MUST be non-empty")
    return value


def _positive_int(environ: Mapping[str, str], key: str, default: int) -> int:
    raw = environ.get(key, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise OperatorServiceConfigurationError(f"{key} MUST be an integer") from exc
    if value < 1:
        raise OperatorServiceConfigurationError(f"{key} MUST be positive")
    return value


__all__ = [
    "AUDIENCE_ENV",
    "CORS_ORIGINS_ENV",
    "DATABASE_CONNECT_TIMEOUT_ENV",
    "DATABASE_ROLE_ENV",
    "DATABASE_STATEMENT_TIMEOUT_ENV",
    "DATABASE_URL_ENV",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "EXPECTED_DATABASE_ROLE",
    "GROUP_ENV",
    "HOST_ENV",
    "ISSUER_ENV",
    "JWKS_URI_ENV",
    "PORT_ENV",
    "TENANT_ENV",
    "OperatorEnvironment",
    "OperatorServiceConfigurationError",
]
