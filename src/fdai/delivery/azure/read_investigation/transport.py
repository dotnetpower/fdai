"""Internal raw-query seam for Azure read-investigation transports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from fdai.shared.providers.read_investigation import ReadToolLimits, ResourceSelector

AzureRow = Mapping[str, object]


@runtime_checkable
class AzureReadTransport(Protocol):
    @property
    def transport_id(self) -> str: ...

    async def resolve_resources(
        self,
        selector: ResourceSelector,
        *,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]: ...

    async def get_resource_state(
        self,
        provider_ref: str,
        *,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]: ...

    async def query_resource_activity(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]: ...

    async def query_resource_health(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]: ...

    async def query_guest_shutdown_events(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]: ...

    async def query_network_security(
        self,
        provider_ref: str,
        *,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]: ...

    async def query_network_peerings(
        self,
        provider_ref: str,
        *,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]: ...


__all__ = ["AzureReadTransport", "AzureRow"]
