"""Dependencies for the Operator AKS commerce family."""

from __future__ import annotations

from typing import Protocol

from fdai_service_contracts import AksCommerceProjection


class AksCommerceProjectionReader(Protocol):
    """Read the latest exact assessment for one business service."""

    async def read_latest(self, service_id: str) -> AksCommerceProjection | None: ...


__all__ = ["AksCommerceProjectionReader"]
