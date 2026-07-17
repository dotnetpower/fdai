"""Production human identity and IAM directory assembly."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import httpx

from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.delivery.identity import EntraHumanIdentityDirectory
from fdai.delivery.read_api.auth import Authenticator, build_authenticator
from fdai.delivery.read_api.entra_verifier import EntraJwtVerifier
from fdai.delivery.read_api.production.config import (
    ProdReadApiConfigError,
    _build_group_mapping,
)

_IAM_DIRECTORY_PROVIDER_ENV = "FDAI_IAM_DIRECTORY_PROVIDER"
_IAM_ENTRA_BASE_URL_ENV = "FDAI_IAM_ENTRA_GRAPH_BASE_URL"


@dataclass(frozen=True, slots=True)
class ProductionIdentity:
    """Authentication, IAM projection, and owned shutdown callbacks."""

    authenticator: Authenticator
    group_mapping: GroupMapping
    iam_directory: EntraHumanIdentityDirectory | None
    iam_provider: str
    shutdown_callbacks: tuple[Callable[[], Awaitable[None]], ...]


def build_production_identity(environ: Mapping[str, str]) -> ProductionIdentity:
    """Build Entra authentication and the optional IAM directory adapter."""
    verifier = EntraJwtVerifier.from_env(environ)
    group_mapping = _build_group_mapping(environ)
    authenticator = build_authenticator(
        verifier=verifier,
        resolver=RoleResolver(group_mapping=group_mapping),
    )
    iam_provider = environ.get(_IAM_DIRECTORY_PROVIDER_ENV, "").strip().casefold()
    if not iam_provider:
        return ProductionIdentity(
            authenticator=authenticator,
            group_mapping=group_mapping,
            iam_directory=None,
            iam_provider="",
            shutdown_callbacks=(),
        )
    if iam_provider != "entra":
        raise ProdReadApiConfigError(
            f"{_IAM_DIRECTORY_PROVIDER_ENV}={iam_provider!r} is not implemented; "
            "supported value: 'entra'"
        )

    from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity

    iam_http = httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0))
    iam_directory = EntraHumanIdentityDirectory(
        client=iam_http,
        identity=ManagedIdentityWorkloadIdentity(http_client=iam_http),
        base_url=environ.get(_IAM_ENTRA_BASE_URL_ENV, "").strip()
        or "https://graph.microsoft.com/v1.0",
    )

    async def close_iam_http() -> None:
        await iam_http.aclose()

    return ProductionIdentity(
        authenticator=authenticator,
        group_mapping=group_mapping,
        iam_directory=iam_directory,
        iam_provider=iam_provider,
        shutdown_callbacks=(close_iam_http,),
    )


__all__ = ["ProductionIdentity", "build_production_identity"]
