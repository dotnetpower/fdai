"""Runtime transport and workload identity binding helpers."""

from __future__ import annotations

import os
from collections.abc import Mapping

import httpx

from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.workload_identity import WorkloadIdentity


def operational_event_bus(primary: EventBus, auxiliary: EventBus | None) -> EventBus:
    """Select the isolated bus for raw inventory and canary traffic when configured."""

    return auxiliary or primary


def build_runtime_workload_identity(
    http_client: httpx.AsyncClient,
    *,
    client_id_env: str = "FDAI_MI_CLIENT_ID",
    require_client_id: bool = False,
) -> WorkloadIdentity:
    if (
        os.environ.get("RUNTIME_ENV", "").strip().lower() == "dev"
        and os.environ.get("FDAI_RUNTIME_LOCAL_AZURE_CLI", "").strip() == "1"
    ):
        from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity

        return AsyncAzureCliWorkloadIdentity.from_env()

    from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity

    if require_client_id and not os.environ.get(client_id_env, "").strip():
        raise RuntimeError(f"{client_id_env} MUST identify the dedicated workload identity")
    return ManagedIdentityWorkloadIdentity.from_env(
        http_client=http_client,
        client_id_env=client_id_env,
    )


def case_history_identity_client_id(environment: Mapping[str, str]) -> str:
    client_id = environment.get("FDAI_CASE_HISTORY_MI_CLIENT_ID", "").strip()
    if not client_id:
        raise RuntimeError(
            "FDAI_CASE_HISTORY_MI_CLIENT_ID MUST identify the dedicated workload identity"
        )
    executor_client_id = environment.get("FDAI_MI_CLIENT_ID", "").strip()
    if executor_client_id and client_id == executor_client_id:
        raise RuntimeError("case history and executor workload identities MUST be distinct")
    return client_id
