"""Deterministic no-mutation rehearsal of the genesis state machine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fdai_deployment_cli.contracts import SubscriptionProvisioningManifest
from fdai_deployment_cli.state import (
    GENESIS_HASH,
    ProvisionEvent,
    RunState,
    append_event,
    read_journal,
)


def rehearse(
    manifest: SubscriptionProvisioningManifest,
    *,
    run_id: str,
    journal: Path,
    interrupt_after: str | None = None,
    started_at: datetime | None = None,
) -> tuple[ProvisionEvent, ...]:
    """Rehearse remaining stages and optionally stop after one completed stage."""

    events = read_journal(journal) if journal.exists() else ()
    if events and events[-1].run_id != run_id:
        raise ValueError("simulation run_id does not match the existing journal")
    if events and events[-1].context_digest != manifest.digest:
        raise ValueError("simulation manifest does not match the existing journal")
    if events and events[-1].state is RunState.READY:
        return events
    known_stages = {entry.entry_id for entry in manifest.entries}
    if interrupt_after is not None and interrupt_after not in known_stages:
        raise ValueError("simulation interrupt stage is not in the manifest")
    completed = {event.stage for event in events if event.state is RunState.COMPLETED}
    previous_digest = events[-1].digest if events else GENESIS_HASH
    sequence = len(events)
    base = started_at or datetime.now(UTC)
    for entry in manifest.entries:
        if entry.entry_id in completed:
            continue
        sequence += 1
        event = ProvisionEvent(
            run_id=run_id,
            context_digest=manifest.digest,
            sequence=sequence,
            stage=entry.entry_id,
            attempt=1,
            state=RunState.COMPLETED,
            occurred_at=(base + timedelta(microseconds=sequence)).isoformat(),
            previous_digest=previous_digest,
            reason_code="simulation-only",
        )
        append_event(journal, event)
        previous_digest = event.digest
        if entry.entry_id == interrupt_after:
            return read_journal(journal)
    sequence += 1
    ready = ProvisionEvent(
        run_id=run_id,
        context_digest=manifest.digest,
        sequence=sequence,
        stage="system-readiness",
        attempt=1,
        state=RunState.READY,
        occurred_at=(base + timedelta(microseconds=sequence)).isoformat(),
        previous_digest=previous_digest,
        reason_code="simulation-only",
    )
    append_event(journal, ready)
    return read_journal(journal)
