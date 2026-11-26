"""Publish Core's resolved entitlement notice for the Console watermark.

Responsibility: resolve the shared license authority on a fixed cadence and record
the derived notice with its observation time.
Boundary: resolution runs in a worker thread because a Trial observation commits to
storage, and a failed publication is logged and retried at the next tick.
Authority and state: the notice grants nothing. Acting requests still pass the
shared execution ceiling, and nothing here can switch the watermark off.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, Protocol

from fdai.core.licensing import LicenseEntitlementAuthority
from fdai.core.licensing.entitlement_notice import EntitlementNotice, entitlement_notice
from fdai.delivery.persistence.postgres_licensing_entitlement_state import (
    PostgresEntitlementStateWriter,
)

_LOGGER = logging.getLogger("fdai.startup")

PUBLISH_INTERVAL_SECONDS: Final = 60.0
"""How often Core republishes its notice; the Operator treats five minutes as stale."""


class EntitlementStateWriter(Protocol):
    """Durable storage for the latest notice and its observation time."""

    async def publish(self, notice: EntitlementNotice, *, observed_at: datetime) -> None: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class EntitlementStatePublisher:
    """Resolve the entitlement and record its notice until Core stops."""

    authority: LicenseEntitlementAuthority
    writer: EntitlementStateWriter
    clock: Callable[[], datetime] = field(default=_utc_now)
    interval_seconds: float = PUBLISH_INTERVAL_SECONDS

    async def publish_once(self) -> EntitlementNotice:
        """Resolve at the current time and record the derived notice."""

        observed_at = self.clock()
        entitlement = await asyncio.to_thread(self.authority.resolve, now=observed_at)
        notice = entitlement_notice(entitlement)
        await self.writer.publish(notice, observed_at=observed_at)
        return notice

    async def run(self, stop: asyncio.Event) -> None:
        """Publish immediately, then every interval, until ``stop`` is set.

        A failed tick only ages the stored notice, and the Operator renders a stale
        notice as not activated, so failure never hides the watermark.
        """

        while not stop.is_set():
            try:
                await self.publish_once()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - a missed tick must not stop Core
                _LOGGER.warning(
                    "license_entitlement_state_publish_failed",
                    extra={"error_type": type(error).__name__},
                )
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                continue


def build_entitlement_state_publisher(
    *,
    authority: LicenseEntitlementAuthority,
    environment: Mapping[str, str],
) -> EntitlementStatePublisher | None:
    """Bind publication to the Core state store, or return None when it is absent.

    Without a state store no notice is published, and the Operator stamps the
    missing state as not activated.
    """

    dsn = (environment.get("FDAI_STATE_STORE_DSN") or "").strip()
    if not dsn:
        _LOGGER.warning(
            "license_entitlement_state_unpublished",
            extra={"reason": "state_store_unconfigured"},
        )
        return None
    return EntitlementStatePublisher(
        authority=authority,
        writer=PostgresEntitlementStateWriter(dsn=dsn),
    )


__all__ = [
    "PUBLISH_INTERVAL_SECONDS",
    "EntitlementStatePublisher",
    "EntitlementStateWriter",
    "build_entitlement_state_publisher",
]
