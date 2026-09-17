"""Projection readers for the AKS commerce family."""

from __future__ import annotations

from typing import Protocol

from fdai_service_contracts import AksCommerceProjection


class OperatorStateReader(Protocol):
    """Read one authoritative tracked-state value."""

    async def read_state(self, key: str) -> dict[str, object] | None: ...


class StateStoreAksCommerceProjectionReader:
    """Validate Core's latest tracked-state projection before disclosure."""

    def __init__(self, store: OperatorStateReader) -> None:
        self._store = store

    async def read_latest(self, service_id: str) -> AksCommerceProjection | None:
        value = await self._store.read_state(f"aks-commerce:projection:v1:{service_id}:latest")
        return AksCommerceProjection.model_validate(value) if value is not None else None


class UnavailableAksCommerceProjectionReader:
    """Represent a deployment without an authoritative state store."""

    async def read_latest(self, service_id: str) -> AksCommerceProjection | None:
        del service_id
        return None


__all__ = [
    "StateStoreAksCommerceProjectionReader",
    "UnavailableAksCommerceProjectionReader",
]
