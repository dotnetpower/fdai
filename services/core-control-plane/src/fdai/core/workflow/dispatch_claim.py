"""Attempt-scoped workflow action dispatch claims."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.runbook.models import RunbookStep
from fdai.core.workflow.workflow_runtime import event_id
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessRuntimeStore,
)

DEFAULT_ACTION_DISPATCH_CLAIM_LEASE = timedelta(seconds=30)
"""Default lease for the pre-dispatch claim that fences workflow replicas."""


def dispatch_event(
    events: tuple[ProcessEvent, ...],
    step: RunbookStep,
    *,
    attempt: int,
) -> ProcessEvent | None:
    return next(
        (
            event
            for event in events
            if event.kind is ProcessEventKind.ACTION_DISPATCHED
            and event.step_id == step.id
            and event.attempt == attempt
        ),
        None,
    )


async def claim_action_dispatch(
    store: ProcessRuntimeStore,
    *,
    process_id: str,
    step: RunbookStep,
    attempt: int,
    correlation_id: str,
    proposal_ref: str,
    lease: timedelta,
) -> ProcessEvent | None:
    now = datetime.now(tz=UTC)
    events = await store.events(process_id)
    if dispatch_event(events, step, attempt=attempt) is not None:
        return None
    latest_claim = latest_dispatch_claim(events, step, attempt=attempt)
    if latest_claim is not None and not claim_expired(latest_claim, now):
        return None
    generation = claim_generation(latest_claim) + 1
    claim = ProcessEvent(
        event_id=event_id(
            process_id,
            f"step:{step.id}:attempt:{attempt}:action-dispatch-claim:{generation}",
        ),
        process_id=process_id,
        kind=ProcessEventKind.ACTION_DISPATCH_CLAIMED,
        idempotency_key=(
            f"{process_id}:step:{step.id}:attempt:{attempt}:action-dispatch-claim:{generation}"
        ),
        recorded_at=now,
        correlation_id=correlation_id,
        step_id=step.id,
        attempt=attempt,
        payload={
            "proposal_ref": proposal_ref,
            "generation": generation,
            "lease_expires_at": (now + lease).isoformat(),
        },
    )
    if not await store.append_event(claim):
        return None
    if not await claim_is_current(
        store, process_id=process_id, claim=claim, step=step, attempt=attempt
    ):
        return None
    return claim


async def claim_is_current(
    store: ProcessRuntimeStore,
    *,
    process_id: str,
    claim: ProcessEvent,
    step: RunbookStep,
    attempt: int,
) -> bool:
    events = await store.events(process_id)
    if dispatch_event(events, step, attempt=attempt) is not None:
        return False
    latest = latest_dispatch_claim(events, step, attempt=attempt)
    return latest is not None and latest.event_id == claim.event_id


async def record_action_dispatched(
    store: ProcessRuntimeStore,
    *,
    process_id: str,
    step: RunbookStep,
    attempt: int,
    correlation_id: str,
    proposal_ref: str,
    params: dict[str, object],
    claim: ProcessEvent,
) -> bool:
    return await store.append_event(
        ProcessEvent(
            event_id=event_id(process_id, f"step:{step.id}:attempt:{attempt}:action-dispatched"),
            process_id=process_id,
            kind=ProcessEventKind.ACTION_DISPATCHED,
            idempotency_key=f"{process_id}:step:{step.id}:attempt:{attempt}:action-dispatched",
            recorded_at=datetime.now(tz=UTC),
            correlation_id=correlation_id,
            causation_id=claim.event_id,
            step_id=step.id,
            attempt=attempt,
            payload={
                "proposal_ref": proposal_ref,
                "action_type": step.action_type,
                "params": params,
                "claim_event_id": claim.event_id,
                "claim_generation": claim_generation(claim),
            },
        )
    )


def latest_dispatch_claim(
    events: tuple[ProcessEvent, ...],
    step: RunbookStep,
    *,
    attempt: int,
) -> ProcessEvent | None:
    claims = [
        event
        for event in events
        if event.kind is ProcessEventKind.ACTION_DISPATCH_CLAIMED
        and event.step_id == step.id
        and event.attempt == attempt
    ]
    return claims[-1] if claims else None


def claim_generation(claim: ProcessEvent | None) -> int:
    if claim is None:
        return 0
    generation = claim.payload.get("generation")
    return generation if isinstance(generation, int) and generation >= 0 else 0


def claim_expired(claim: ProcessEvent, now: datetime) -> bool:
    raw = claim.payload.get("lease_expires_at")
    if not isinstance(raw, str):
        return True
    try:
        expires_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    return expires_at <= now


__all__ = [
    "DEFAULT_ACTION_DISPATCH_CLAIM_LEASE",
    "claim_action_dispatch",
    "claim_generation",
    "claim_is_current",
    "dispatch_event",
    "record_action_dispatched",
]
