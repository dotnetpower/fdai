"""Compose independent Assurance Twin writers and durable outbox relays."""

from __future__ import annotations

from collections.abc import Collection
from typing import Literal

from fdai.delivery.assurance_twin_posture import AssuranceTwinPostureRecorder
from fdai.delivery.assurance_twin_publication import AssuranceTwinOutboxPublisher
from fdai.delivery.assurance_twin_writers import (
    AssuranceTwinAgentWriter,
    RetainedTwinEvidenceSource,
)
from fdai.delivery.persistence.state_store_assurance_twin_posture import (
    StateStoreAssuranceTwinPostureLedger,
)
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore


def build_assurance_twin_runtime_binding(
    *,
    state_store: StateStore | None,
    agents: Collection[str] | None,
    event_bus: EventBus,
    retained_source: RetainedTwinEvidenceSource | None,
) -> tuple[tuple[AssuranceTwinOutboxPublisher, ...], tuple[AssuranceTwinAgentWriter, ...]]:
    """Bind no writer without the durable store and all three accountable agents."""

    if (
        state_store is None
        or agents is None
        or not {"Heimdall", "Forseti", "Saga"}.issubset(agents)
    ):
        return (), ()

    ledger = StateStoreAssuranceTwinPostureLedger(store=state_store)
    publishers = tuple(
        AssuranceTwinOutboxPublisher(owner=owner, ledger=ledger, bus=event_bus)
        for owner in ("Heimdall", "Forseti")
    )
    if retained_source is None:
        return publishers, ()

    recorder = AssuranceTwinPostureRecorder(ledger=ledger)
    owners: tuple[Literal["Heimdall", "Forseti"], ...] = ("Heimdall", "Forseti")
    writers = tuple(
        AssuranceTwinAgentWriter(owner=owner, source=retained_source, recorder=recorder)
        for owner in owners
    )
    return publishers, writers


__all__ = ["build_assurance_twin_runtime_binding"]
