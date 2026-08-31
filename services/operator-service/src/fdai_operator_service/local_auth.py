"""Local-only Azure CLI principal projection for the Operator Service."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

import jwt
from fdai_service_contracts import OperatorPrincipal, OperatorPrincipalKind, OperatorRole

_ARM_RESOURCE = "https://management.azure.com"
_AZ_TIMEOUT_SECONDS = 20

AzRunner = Callable[[tuple[str, ...]], str]


class AzureCliIdentityError(RuntimeError):
    """The active Azure CLI session cannot produce a local user identity."""


@dataclass(frozen=True, slots=True)
class LocalAzureCliIdentity:
    """Hold the bounded browser-safe projection of the current CLI user."""

    principal: OperatorPrincipal
    username: str
    name: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return only the local profile fields accepted by the Console."""

        return {
            "oid": self.principal.subject_id,
            "username": self.username,
            "name": self.name,
            "roles": sorted(role.value for role in self.principal.roles),
            "source": "azure-cli",
        }


def resolve_azure_cli_identity(*, runner: AzRunner | None = None) -> LocalAzureCliIdentity:
    """Resolve the active CLI user with a fixed Contributor development ceiling."""

    run = runner or _run_az
    account = _parse_json(run(("account", "show", "--output", "json")), "account")
    if account.get("state") != "Enabled":
        raise AzureCliIdentityError("the active Azure subscription is not enabled")

    user = account.get("user")
    if not isinstance(user, Mapping) or user.get("type") != "user":
        raise AzureCliIdentityError("local Azure CLI auth requires an interactive user login")

    token_result = _parse_json(
        run(
            (
                "account",
                "get-access-token",
                "--resource",
                _ARM_RESOURCE,
                "--output",
                "json",
            )
        ),
        "access token",
    )
    token = token_result.get("accessToken")
    if not isinstance(token, str) or not token:
        raise AzureCliIdentityError("Azure CLI returned no access token; run 'az login'")
    claims = _decode_claims(token)

    account_tenant = account.get("tenantId")
    token_tenant = claims.get("tid")
    if not isinstance(account_tenant, str) or token_tenant != account_tenant:
        raise AzureCliIdentityError("Azure CLI account and access-token tenants do not match")

    oid = claims.get("oid")
    if not isinstance(oid, str) or not oid:
        raise AzureCliIdentityError("Azure CLI user token has no stable Entra object id")
    username = _first_string(claims, "preferred_username", "upn")
    if username is None:
        raw_username = user.get("name")
        username = raw_username if isinstance(raw_username, str) and raw_username else None
    if username is None:
        raise AzureCliIdentityError("Azure CLI user has no displayable username")

    return LocalAzureCliIdentity(
        principal=OperatorPrincipal(
            subject_id=oid,
            roles=frozenset({OperatorRole.CONTRIBUTOR}),
            principal_kind=OperatorPrincipalKind.HUMAN,
        ),
        username=username,
        name=_first_string(claims, "name"),
    )


def _run_az(args: tuple[str, ...]) -> str:
    executable = shutil.which("az")
    if executable is None:
        raise AzureCliIdentityError(
            "could not read the local Azure CLI session; install Azure CLI and run 'az login'"
        )
    try:
        completed = subprocess.run(  # noqa: S603 - executable and arguments are fixed
            (executable, *args),
            check=True,
            capture_output=True,
            text=True,
            timeout=_AZ_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise AzureCliIdentityError(
            "could not read the local Azure CLI session; install Azure CLI and run 'az login'"
        ) from exc
    return completed.stdout


def _parse_json(raw: str, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AzureCliIdentityError(f"Azure CLI returned invalid {label} JSON") from exc
    if not isinstance(value, Mapping):
        raise AzureCliIdentityError(f"Azure CLI returned invalid {label} data")
    return value


def _decode_claims(token: str) -> Mapping[str, Any]:
    try:
        claims = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_aud": False,
                "verify_exp": False,
                "verify_iss": False,
            },
        )
    except jwt.PyJWTError as exc:
        raise AzureCliIdentityError("Azure CLI returned a malformed access token") from exc
    return cast(Mapping[str, Any], claims)


def _first_string(values: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value:
            return value
    return None


__all__ = [
    "AzureCliIdentityError",
    "LocalAzureCliIdentity",
    "resolve_azure_cli_identity",
]
