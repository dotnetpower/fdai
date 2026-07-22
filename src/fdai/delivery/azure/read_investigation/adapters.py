"""Named REST and typed-CLI facades over the shared Azure normalizer."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fdai.delivery.azure.read_investigation.provider import AzureReadInvestigationProvider
from fdai.delivery.azure.read_investigation.transport import AzureReadTransport


class AzureRestReadInvestigationAdapter(AzureReadInvestigationProvider):
    def __init__(
        self,
        transport: AzureReadTransport,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if transport.transport_id != "rest":
            raise ValueError("REST adapter requires the rest transport")
        super().__init__(transport, clock=clock)


class AzureCliReadInvestigationAdapter(AzureReadInvestigationProvider):
    def __init__(
        self,
        transport: AzureReadTransport,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if transport.transport_id != "cli":
            raise ValueError("CLI adapter requires the typed cli transport")
        super().__init__(transport, clock=clock)


__all__ = ["AzureCliReadInvestigationAdapter", "AzureRestReadInvestigationAdapter"]
