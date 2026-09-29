"""Azure role readback binds the token principal and role definitions."""

from __future__ import annotations

import httpx
import pytest
from fdai.core.operational_evidence.own_role_readback import VerifierOwnRoleReadbackError
from fdai.delivery.azure.operational_evidence_roles import (
    AzureAuthorizationRoleAssignmentReader,
    AzureManagementToken,
    build_azure_management_token_provider,
)


class _Token:
    def __init__(self, oid: str) -> None:
        self.oid = oid

    async def get_token(self, _audience: str) -> AzureManagementToken:
        return AzureManagementToken(token="token", oid=self.oid)


async def test_azure_role_reader_requires_token_oid_to_match_principal() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200))
    ) as client:
        reader = AzureAuthorizationRoleAssignmentReader(
            client=client,
            token_provider=_Token("other-principal"),
            principal_id="verifier-principal",
            scopes=("scope",),
        )
        with pytest.raises(VerifierOwnRoleReadbackError, match="token"):
            await reader.read()


async def test_azure_role_reader_marks_unresolved_role_definition_partial() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "roleAssignments" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "properties": {
                                "scope": "scope",
                                "roleDefinitionId": "/roleDefinitions/missing",
                            }
                        }
                    ]
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = AzureAuthorizationRoleAssignmentReader(
            client=client,
            token_provider=_Token("verifier-principal"),
            principal_id="verifier-principal",
            scopes=("scope",),
        )
        readback = await reader.read()
    assert readback.principal_id == "verifier-principal"
    assert readback.assignments[0].role_name == ""


def test_token_provider_uses_managed_identity_in_container_apps() -> None:
    provider = build_azure_management_token_provider({}, client_id="client-id")
    assert provider.credential.__class__.__name__ == "ManagedIdentityCredential"


def test_token_provider_uses_workload_identity_in_aks() -> None:
    provider = build_azure_management_token_provider(
        {
            "AZURE_FEDERATED_TOKEN_FILE": "/var/run/secrets/azure/tokens/azure-identity-token",
            "AZURE_TENANT_ID": "00000000-0000-0000-0000-000000000000",
        },
        client_id="client-id",
    )
    assert provider.credential.__class__.__name__ == "WorkloadIdentityCredential"
