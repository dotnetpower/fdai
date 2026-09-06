"""Bind read-only model metadata discovery without deployment or inference authority."""

from __future__ import annotations

from azure.core.exceptions import AzureError
from azure.identity.aio import ManagedIdentityCredential
from fdai_service_contracts.venue import ExecutionVenue, resolve_execution_venue

from fdai_operator_service.adapters.azure_cli_token import azure_cli_token
from fdai_operator_service.adapters.model_catalog import (
    AzureModelCatalogReader,
    ModelCatalogUnavailableError,
)
from fdai_operator_service.environment import OperatorEnvironment
from fdai_operator_service.families.conversation.contracts import ConversationBoundaryError


def build_model_catalog_reader(environment: OperatorEnvironment) -> AzureModelCatalogReader | None:
    """Bind only configured account metadata, using the existing venue's read identity."""
    subscription_id = environment.values.get("AZURE_SUBSCRIPTION_ID", "").strip()
    endpoint = environment.values.get("FDAI_LLM_ENDPOINT", "").strip()
    if not subscription_id or not endpoint:
        return None
    local = resolve_execution_venue(environment.values) is ExecutionVenue.LOCAL

    async def token_provider() -> str:
        try:
            if local:
                return await azure_cli_token("https://management.azure.com/")
            async with ManagedIdentityCredential(
                client_id=environment.managed_identity_client_id
            ) as credential:
                return str(
                    (await credential.get_token("https://management.azure.com/.default")).token
                )
        except (AzureError, ConversationBoundaryError) as exc:
            raise ModelCatalogUnavailableError("catalog_identity_unavailable") from exc

    return AzureModelCatalogReader(
        subscription_id=subscription_id,
        endpoint=endpoint,
        token_provider=token_provider,
    )
