"""Select the narrator token source from the explicit execution venue."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from fdai_service_contracts.venue import ExecutionVenue, resolve_execution_venue

from fdai_operator_service.adapters.azure_cli_token import azure_cli_token
from fdai_operator_service.adapters.azure_identity import create_workload_credential

TokenProvider = Callable[[str], Awaitable[str]]


def build_narrator_token_provider(
    values: Mapping[str, str],
    *,
    client_id: str | None,
) -> TokenProvider:
    """Use Azure CLI locally and the selected workload identity when deployed."""

    if resolve_execution_venue(values) is ExecutionVenue.LOCAL:
        return azure_cli_token

    async def managed_token(audience: str) -> str:
        credential = create_workload_credential(environment=values, client_id=client_id)
        try:
            scope = f"{audience.rstrip('/')}/.default"
            return str((await credential.get_token(scope)).token)
        finally:
            await credential.close()

    return managed_token


__all__ = ["TokenProvider", "build_narrator_token_provider"]
