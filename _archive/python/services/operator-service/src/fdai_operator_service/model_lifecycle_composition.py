"""Compose the Operator resolved-model revision owner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import httpx
from azure.identity.aio import ManagedIdentityCredential

from fdai_operator_service.adapters.resolved_models_key_vault import (
    KeyVaultResolvedModelsConfig,
    KeyVaultResolvedModelsSource,
)
from fdai_operator_service.environment import OperatorEnvironment
from fdai_operator_service.model_lifecycle_startup import (
    AsyncResolvedModelsSource,
    ConfiguredResolvedModelsSource,
    OperatorResolvedModelsRevisionOwner,
)


def build_model_revision_owner(
    environment: OperatorEnvironment,
    *,
    source: AsyncResolvedModelsSource | None,
) -> OperatorResolvedModelsRevisionOwner | None:
    """Bind one configured source and require its deployment digest."""

    expected_digest = environment.values.get("LLM_RESOLVED_MODELS_SHA256", "").strip()
    configured_path = environment.values.get("LLM_RESOLVED_MODELS_PATH", "").strip()
    vault_url = environment.values.get(
        "FDAI_RESOLVED_MODELS_KEY_VAULT_URL",
        "",
    ).strip()
    secret_name = environment.values.get(
        "FDAI_RESOLVED_MODELS_KEY_VAULT_SECRET_NAME",
        "",
    ).strip()
    source_configured = source is not None or bool(vault_url or secret_name or configured_path)
    if not source_configured and not expected_digest:
        return None
    if len(expected_digest) != 64 or any(
        character not in "0123456789abcdef" for character in expected_digest
    ):
        raise RuntimeError("Operator requires LLM_RESOLVED_MODELS_SHA256")
    if source is not None:
        return OperatorResolvedModelsRevisionOwner(
            source=source,
            expected_digest=expected_digest,
        )
    if vault_url or secret_name:
        if not vault_url or not secret_name:
            raise RuntimeError(
                "Operator resolved-model Key Vault URL and secret name are both required"
            )
        credential = (
            ManagedIdentityCredential(client_id=environment.managed_identity_client_id)
            if environment.managed_identity_client_id is not None
            else ManagedIdentityCredential()
        )
        http_client = httpx.AsyncClient()

        async def token_provider(audience: str) -> str:
            return cast(str, (await credential.get_token(audience)).token)

        async def close() -> None:
            try:
                await http_client.aclose()
            finally:
                await credential.close()

        return OperatorResolvedModelsRevisionOwner(
            source=KeyVaultResolvedModelsSource(
                config=KeyVaultResolvedModelsConfig(
                    vault_url=vault_url,
                    secret_name=secret_name,
                    secret_version=environment.values.get(
                        "FDAI_RESOLVED_MODELS_KEY_VAULT_SECRET_VERSION",
                        "",
                    ).strip()
                    or None,
                ),
                token_provider=token_provider,
                http_client=_KeyVaultHttpClient(http_client),
            ),
            expected_digest=expected_digest,
            close=close,
        )
    if not configured_path:
        raise RuntimeError("Operator resolved-model source is not configured")
    return OperatorResolvedModelsRevisionOwner(
        source=ConfiguredResolvedModelsSource(configured_path),
        expected_digest=expected_digest,
    )


@dataclass(frozen=True, slots=True)
class _KeyVaultHttpClient:
    client: httpx.AsyncClient

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.client.get(url, **kwargs)


__all__ = [
    "AsyncResolvedModelsSource",
    "OperatorResolvedModelsRevisionOwner",
    "build_model_revision_owner",
]
