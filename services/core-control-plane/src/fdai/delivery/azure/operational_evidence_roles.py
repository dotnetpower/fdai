"""Azure Authorization readback for the operational evidence verifier identity."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
import jwt
from azure.identity.aio import ManagedIdentityCredential, WorkloadIdentityCredential

from fdai.core.operational_evidence.own_role_readback import (
    VerifierOwnRoleReadback,
    VerifierOwnRoleReadbackError,
    VerifierRoleAssignment,
)

_API_VERSION = "2022-04-01"
_MANAGEMENT_AUDIENCE = "https://management.azure.com/.default"


@dataclass(frozen=True, slots=True)
class AzureManagementToken:
    """One management token and the object id it proves for the running workload."""

    token: str
    oid: str


class AzureTokenProvider(Protocol):
    """Return one bounded Azure management-plane bearer token."""

    async def get_token(self, audience: str) -> AzureManagementToken: ...


class AzureCredential(Protocol):
    async def get_token(self, *scopes: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class AzureAuthorizationRoleAssignmentReader:
    """Read the verifier's own Azure role assignments through ARM."""

    client: httpx.AsyncClient
    token_provider: AzureTokenProvider
    principal_id: str
    scopes: tuple[str, ...]
    management_endpoint: str = "https://management.azure.com"
    role_definition_names: Mapping[str, str] | None = None

    async def read(self) -> VerifierOwnRoleReadback:
        if not self.principal_id.strip() or not self.scopes:
            raise VerifierOwnRoleReadbackError("role readback principal or scopes are unbound")
        token = await self.token_provider.get_token(_MANAGEMENT_AUDIENCE)
        if not token.token or token.oid != self.principal_id:
            raise VerifierOwnRoleReadbackError("Azure management token is unavailable")
        headers = {"Authorization": "Bearer " + token.token}
        observed: list[VerifierRoleAssignment] = []
        complete = True
        for scope in self.scopes:
            response = await self.client.get(
                self._url(
                    scope,
                    "/providers/Microsoft.Authorization/roleAssignments",
                    {
                        "api-version": _API_VERSION,
                        "$filter": f"assignedTo('{self.principal_id}')",
                    },
                ),
                headers=headers,
            )
            if response.status_code != 200:
                complete = False
                continue
            payload = response.json()
            items = payload.get("value")
            if not isinstance(items, list):
                complete = False
                continue
            for item in items:
                if isinstance(item, dict):
                    observed.append(await self._assignment(item, headers))
            if payload.get("nextLink"):
                complete = False
        return VerifierOwnRoleReadback(
            principal_id=token.oid,
            assignments=tuple(observed),
            complete=complete,
            observed_scopes=tuple(self.scopes),
        )

    async def _assignment(
        self, item: Mapping[str, object], headers: Mapping[str, str]
    ) -> VerifierRoleAssignment:
        properties = item.get("properties")
        if not isinstance(properties, Mapping):
            raise VerifierOwnRoleReadbackError("role assignment properties are malformed")
        role_definition_id = str(properties.get("roleDefinitionId", ""))
        scope = str(properties.get("scope", ""))
        role_name, actions, data_actions = await self._role_definition(role_definition_id, headers)
        return VerifierRoleAssignment(
            scope=scope,
            role_definition_id=role_definition_id,
            role_name=role_name,
            actions=actions,
            data_actions=data_actions,
        )

    async def _role_definition(
        self, role_definition_id: str, headers: Mapping[str, str]
    ) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
        if self.role_definition_names is not None:
            return self.role_definition_names.get(role_definition_id, ""), (), ()
        response = await self.client.get(
            f"{self.management_endpoint.rstrip('/')}{role_definition_id}?api-version={_API_VERSION}",
            headers=headers,
        )
        if response.status_code != 200:
            return "", (), ()
        properties = response.json().get("properties", {})
        if not isinstance(properties, Mapping):
            return "", (), ()
        permissions = properties.get("permissions", [])
        actions: list[str] = []
        data_actions: list[str] = []
        if isinstance(permissions, list):
            for permission in permissions:
                if isinstance(permission, Mapping):
                    raw_actions = permission.get("actions", [])
                    raw_data_actions = permission.get("dataActions", [])
                    if isinstance(raw_actions, list):
                        actions.extend(str(item) for item in raw_actions)
                    if isinstance(raw_data_actions, list):
                        data_actions.extend(str(item) for item in raw_data_actions)
        return str(properties.get("roleName", "")), tuple(actions), tuple(data_actions)

    def _url(self, scope: str, suffix: str, query: Mapping[str, str]) -> str:
        base = self.management_endpoint.rstrip("/")
        pairs = "&".join(f"{key}={value}" for key, value in query.items())
        return f"{base}{scope.rstrip('/')}{suffix}?{pairs}"


@dataclass(frozen=True, slots=True)
class StaticVerifierRoleAssignmentReader:
    """Deterministic fake used by tests and offline preflight fixtures."""

    readback: VerifierOwnRoleReadback | Exception

    async def read(self) -> VerifierOwnRoleReadback:
        if isinstance(self.readback, Exception):
            raise self.readback
        return self.readback


def role_assignments_from_json(
    items: Sequence[Mapping[str, object]], *, principal_id: str
) -> VerifierOwnRoleReadback:
    """Build a deterministic role readback from deployment preflight JSON."""

    return VerifierOwnRoleReadback(
        principal_id=principal_id,
        assignments=tuple(
            VerifierRoleAssignment(
                scope=str(item.get("scope", "")),
                role_definition_id=str(item.get("role_definition_id", "")),
                role_name=str(item.get("role_name", "")),
                actions=_string_tuple(item.get("actions", ())),
                data_actions=_string_tuple(item.get("data_actions", ())),
            )
            for item in items
        ),
        complete=True,
        observed_scopes=tuple(sorted({str(item.get("scope", "")) for item in items})),
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    return tuple(str(item) for item in value) if isinstance(value, list | tuple) else ()


@dataclass(slots=True)
class WorkloadIdentityAzureTokenProvider:
    """Azure management token provider backed by federated workload identity."""

    credential: AzureCredential

    async def get_token(self, audience: str) -> AzureManagementToken:
        token = await self.credential.get_token(audience)
        claims = jwt.decode(token.token, options={"verify_signature": False})
        oid = claims.get("oid")
        if not isinstance(oid, str) or not oid:
            raise VerifierOwnRoleReadbackError("managed identity token is missing oid")
        return AzureManagementToken(token=token.token, oid=oid)


def build_azure_management_token_provider(
    env: Mapping[str, str], *, client_id: str
) -> WorkloadIdentityAzureTokenProvider:
    """Select the Azure credential shape for the deployed runtime platform."""

    if not client_id.strip():
        raise VerifierOwnRoleReadbackError("verifier managed identity client id is unbound")
    token_file = env.get("AZURE_FEDERATED_TOKEN_FILE", "").strip()
    if token_file:
        return WorkloadIdentityAzureTokenProvider(
            WorkloadIdentityCredential(
                tenant_id=env.get("AZURE_TENANT_ID") or env.get("AZURE_AUTHORITY_TENANT_ID"),
                client_id=client_id,
                token_file_path=token_file,
            )
        )
    return WorkloadIdentityAzureTokenProvider(ManagedIdentityCredential(client_id=client_id))


__all__ = [
    "AzureAuthorizationRoleAssignmentReader",
    "AzureManagementToken",
    "AzureTokenProvider",
    "StaticVerifierRoleAssignmentReader",
    "WorkloadIdentityAzureTokenProvider",
    "build_azure_management_token_provider",
    "role_assignments_from_json",
]
