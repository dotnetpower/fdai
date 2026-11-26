"""Explicit workload federation for outbound Hub calls, never Azure management."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Protocol

from fdai_lifecycle_agent.hub_client import HubProtocolError


class AccessToken(Protocol):
    @property
    def token(self) -> str: ...


class Credential(Protocol):
    def get_token(self, *scopes: str) -> AccessToken: ...

    def close(self) -> None: ...


def _credential() -> Credential:
    from azure.identity import WorkloadIdentityCredential

    required = ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_FEDERATED_TOKEN_FILE")
    if not all(os.environ.get(name, "").strip() for name in required):
        raise ValueError(
            "Workload identity requires tenant, client and projected token-file bindings."
        )
    return WorkloadIdentityCredential(
        tenant_id=os.environ["AZURE_TENANT_ID"],
        client_id=os.environ["AZURE_CLIENT_ID"],
        token_file_path=os.environ["AZURE_FEDERATED_TOKEN_FILE"],
        connection_timeout=5,
        read_timeout=5,
        retry_total=0,
    )


class WorkloadIdentityAuthorization:
    """Acquire only the selected Hub API scope; no CLI, secret or developer fallback."""

    def __init__(self, scope: str, *, connect: Callable[[], Credential] = _credential) -> None:
        if (
            not scope.startswith("api://")
            or not scope.endswith("/.default")
            or not scope.removeprefix("api://").removesuffix("/.default")
            or any(character.isspace() for character in scope)
            or "?" in scope
            or "#" in scope
        ):
            raise ValueError("Workload identity requires one explicit api:// Hub /.default scope.")
        self._scope = scope
        self._credential = connect()

    def __call__(self) -> str:
        from azure.core.exceptions import AzureError

        try:
            return self._credential.get_token(self._scope).token
        except (AzureError, OSError, ValueError) as error:
            raise HubProtocolError("Hub workload identity authentication failed.") from error

    def close(self) -> None:
        self._credential.close()
