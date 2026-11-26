"""Select one explicit Azure workload credential without a fallback identity chain."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import ManagedIdentityCredential, WorkloadIdentityCredential


def create_workload_credential(
    *, environment: Mapping[str, str], client_id: str | None = None
) -> AsyncTokenCredential:
    """Use AKS federation when declared, otherwise retain the attached MI contract.

    Incomplete federation or disagreement with the selected service identity fails
    at construction. Token acquisition failures never fall back to a node identity,
    Azure CLI, developer credential, or a different service's managed identity.
    The explicitly declared command identity may share the projected ServiceAccount
    subject through its own federated credential; it is never selected implicitly.
    The caller owns the returned credential and must close it at shutdown.
    """
    if "AZURE_FEDERATED_TOKEN_FILE" not in environment:
        return (
            ManagedIdentityCredential(client_id=client_id)
            if client_id
            else ManagedIdentityCredential()
        )
    tenant = environment.get("AZURE_TENANT_ID", "")
    workload_client = environment.get("AZURE_CLIENT_ID", "")
    selected_client = workload_client if client_id is None else client_id
    token_file = environment.get("AZURE_FEDERATED_TOKEN_FILE", "")
    try:
        UUID(tenant)
        UUID(workload_client)
        UUID(selected_client)
    except ValueError:
        raise ValueError(
            "AKS workload identity requires valid tenant and client identifiers"
        ) from None
    if not token_file or token_file != token_file.strip() or not Path(token_file).is_absolute():
        raise ValueError("AKS workload identity requires an absolute projected token path")
    declared_clients = {
        workload_client.casefold(),
        environment.get("FDAI_COMMAND_MI_CLIENT_ID", "").casefold(),
    }
    if selected_client.casefold() not in declared_clients:
        raise ValueError("AKS workload identity differs from the selected service identity")
    return WorkloadIdentityCredential(
        tenant_id=tenant,
        client_id=selected_client,
        token_file_path=token_file,
        **(
            {"authority": environment["AZURE_AUTHORITY_HOST"]}
            if environment.get("AZURE_AUTHORITY_HOST")
            else {}
        ),
    )
