"""Suppress setup recommendations only with exact, currently admitted observer evidence."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path

from fdai_service_contracts.cluster_connector import connector_time

from fdai.delivery.kubernetes_connector_runtime import FileConnectorRegistrations
from fdai.delivery.kubernetes_connector_snapshot import ConnectorSnapshotInbox
from fdai.shared.providers.state_store import StateStore

OBSERVER_REGISTRATIONS_ENV = "FDAI_OBSERVER_REGISTRATIONS_PATH"


class CurrentObserverEvidence:
    """Read the existing authenticated snapshot inbox; never infer graph promotion or health."""

    def __init__(
        self,
        store: StateStore,
        *,
        registrations: FileConnectorRegistrations,
        now: Callable[[], datetime],
    ) -> None:
        self._registrations = registrations
        self._now = now
        self._inbox = ConnectorSnapshotInbox(
            store,
            registrations=registrations,
            allow_cluster_resources=True,
            now=now,
        )

    async def observing(self, target_ref: str) -> bool:
        try:
            registration = await self._registrations.for_target(target_ref)
            if registration is None:
                return False
            snapshot = await self._inbox.current(principal_ref=registration.principal_ref)
            confirmed = await self._registrations.for_target(target_ref)
            if confirmed != registration:
                return False
            cutoff = connector_time(self._now())
            registration.admit(
                principal_ref=registration.principal_ref,
                scope=registration.scope,
                capability="inventory.snapshot",
                now=cutoff,
            )
            return snapshot.observed_at <= cutoff < snapshot.observed_at + timedelta(seconds=300)
        except (OSError, ValueError, TypeError, KeyError):
            return False


def build_observer_evidence(
    store: StateStore, *, now: Callable[[], datetime]
) -> Callable[[str], Awaitable[bool]] | None:
    path = os.environ.get(OBSERVER_REGISTRATIONS_ENV, "").strip()
    if not path:
        return None
    return CurrentObserverEvidence(
        store,
        registrations=FileConnectorRegistrations(Path(path)),
        now=now,
    ).observing
