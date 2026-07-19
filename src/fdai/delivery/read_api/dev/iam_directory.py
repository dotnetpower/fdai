"""Human identity directory composition for the local read API."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from fdai.core.rbac.resolver import GroupMapping
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.identity import EntraHumanIdentityDirectory
from fdai.shared.providers.human_identity import (
    HumanIdentityDirectory,
    StaticHumanIdentityDirectory,
)


@dataclass(frozen=True, slots=True)
class LocalIamDirectory:
    directory: HumanIdentityDirectory
    role_group_ids: dict[str, str]
    shutdown_callbacks: tuple[Callable[[], Awaitable[None]], ...] = ()


def build_local_iam_directory(
    group_mapping: GroupMapping,
    *,
    use_graph: bool,
    application_id: str | None = None,
) -> LocalIamDirectory:
    role_group_ids = {
        "Reader": group_mapping.reader_group_id,
        "Contributor": group_mapping.contributor_group_id,
        "Approver": group_mapping.approver_group_id,
        "Owner": group_mapping.owner_group_id,
        "BreakGlass": group_mapping.break_glass_group_id,
    }
    if not use_graph:
        return LocalIamDirectory(
            directory=StaticHumanIdentityDirectory(),
            role_group_ids=role_group_ids,
        )

    client = httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0))
    directory = EntraHumanIdentityDirectory(
        client=client,
        identity=AsyncAzureCliWorkloadIdentity(),
        application_id=application_id,
    )

    async def close() -> None:
        await client.aclose()

    return LocalIamDirectory(
        directory=directory,
        role_group_ids=role_group_ids,
        shutdown_callbacks=(close,),
    )


__all__ = ["LocalIamDirectory", "build_local_iam_directory"]
