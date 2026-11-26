"""One bounded observer cycle: recover pending evidence before collecting new data."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from fdai_service_contracts.cluster_connector import ConnectorEvidence, ConnectorRegistration

from fdai.delivery.kubernetes_connector import ConnectorAdmissionReceipt
from fdai.delivery.kubernetes_connector_snapshot import ConnectorRegistrationReader
from fdai.delivery.kubernetes_connector_spool import ConnectorSnapshotSpool
from fdai.delivery.kubernetes_inventory import KubernetesRuntimeInventorySource


class SnapshotSender(Protocol):
    async def send_snapshot(
        self,
        packet: ConnectorEvidence,
        content: bytes,
        *,
        allow_cluster_resources: bool,
    ) -> ConnectorAdmissionReceipt: ...


class ConnectorObserverWorker:
    """Recover persisted snapshots without replacing source clocks or losing acknowledgments.

    The scheduler invokes one cycle at a time. A storage failure, stale pending packet or
    network failure stops this cycle; it never resets a stream, drops data, or retries a
    provider inside the cycle. The same persisted packet is safe to retry after uncertain
    delivery because the central inbox binds its complete bytes to a single sequence.
    """

    def __init__(
        self,
        *,
        source: KubernetesRuntimeInventorySource,
        spool: ConnectorSnapshotSpool,
        sender: SnapshotSender,
        registrations: ConnectorRegistrationReader,
        principal_ref: str,
        producer_revision: str,
        allow_cluster_resources: bool,
        now: Callable[[], datetime],
        deadline_seconds: float = 120,
        max_age_seconds: int = 300,
    ) -> None:
        if (
            isinstance(deadline_seconds, bool)
            or not math.isfinite(deadline_seconds)
            or not 1 <= deadline_seconds <= 600
        ):
            raise ValueError("connector cycle deadline must be in [1, 600]")
        if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 3600:
            raise ValueError("connector freshness limit must be in [1, 3600]")
        self._source, self._spool, self._sender = source, spool, sender
        self._registrations, self._principal = registrations, principal_ref
        self._revision, self._cluster_resources = producer_revision, allow_cluster_resources
        self._now, self._deadline, self._max_age = now, deadline_seconds, max_age_seconds
        self._lock = asyncio.Lock()

    async def run_once(self) -> ConnectorAdmissionReceipt:
        """Return delivery acceptance only, not a graph promotion or operational success."""
        async with asyncio.timeout(self._deadline):
            async with self._lock:
                registration = await self._registration()
                pending = await self._spool.oldest()
                if pending is None:
                    snapshot = await self._source.collect()
                    current_registration = await self._registration()
                    if current_registration != registration:
                        raise ValueError("connector registration changed during collection")
                    pending = await self._spool.enqueue(
                        snapshot,
                        registration=current_registration,
                        producer_revision=self._revision,
                        now=self._now(),
                    )
                registration = await self._registration()
                pending.evidence.admit(
                    registration,
                    principal_ref=self._principal,
                    now=self._now(),
                    max_age_seconds=self._max_age,
                )
                receipt = await self._sender.send_snapshot(
                    pending.evidence,
                    pending.content,
                    allow_cluster_resources=self._cluster_resources,
                )
                await self._spool.acknowledge(receipt)
                return receipt

    async def _registration(self) -> ConnectorRegistration:
        registration = await self._registrations.read(self._principal)
        if registration is None:
            raise ValueError("connector enrollment is unavailable")
        registration = ConnectorRegistration.model_validate_json(registration.model_dump_json())
        registration.admit(
            principal_ref=self._principal,
            scope=registration.scope,
            capability="inventory.snapshot",
            now=self._now(),
        )
        return registration
