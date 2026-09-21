"""Durable replay and publication lifecycle owned by Thor."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai.agents._framework.action_run_identity import action_run_identity_digest
from fdai.agents._framework.action_run_state import (
    TERMINAL_ACTION_RUN_STATES as _TERMINAL_STATES,
)
from fdai.agents._framework.action_run_state import ActionRunState
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.thor_action_run import ActionRun, ActionRunStore
from fdai.agents._framework.thor_effect_verification import effect_publication_fields
from fdai.shared.contracts.models import Autonomy


class ThorPersistenceHost(Protocol):
    bus: PantheonBus | None
    action_runs: dict[str, ActionRun]
    _idempotency_runs: dict[str, ActionRun]
    _resource_locks: set[str]
    _max_retained_runs: int
    _state_store: ActionRunStore | None

    async def _execute(self, run: ActionRun) -> None: ...

    def record_behavior(self, key: str) -> None: ...


async def rehydrate(host: ThorPersistenceHost) -> int:
    """Reload in-flight ActionRuns and safely resume their durable lifecycle."""
    if host._state_store is None:
        return 0
    active = await host._state_store.load_active()
    resource_counts: dict[str, int] = {}
    claimed_counts: dict[str, int] = {}
    for run in active:
        if run.resource_id and run.state not in _TERMINAL_STATES:
            resource_id = str(run.resource_id)
            resource_counts[resource_id] = resource_counts.get(resource_id, 0) + 1
            if run.resource_claimed:
                claimed_counts[resource_id] = claimed_counts.get(resource_id, 0) + 1
    for run in active:
        if run.state in _TERMINAL_STATES:
            host.action_runs[run.correlation_id] = run
            host._idempotency_runs[run.idempotency_key] = run
            await emit_action_run(host, run)
            await finalize_terminal_replay(host, run)
            continue
        if run.resource_claimed and run.state in {
            ActionRunState.VERDICTED,
            ActionRunState.APPROVED,
            ActionRunState.EXECUTING,
        }:
            run.transition(ActionRunState.EXECUTION_UNKNOWN)
            run.outcome = "claimed_execution_requires_reconciliation"
            run.shadow_mode = True
            host.action_runs[run.correlation_id] = run
            host._idempotency_runs[run.idempotency_key] = run
            if run.resource_id:
                host._resource_locks.add(str(run.resource_id))
            await emit_action_run(host, run)
            continue
        if (
            run.resource_id
            and resource_counts.get(str(run.resource_id), 0) > 1
            and (not run.resource_claimed or claimed_counts.get(str(run.resource_id), 0) > 1)
        ):
            if not run.resource_claimed:
                run.outcome = "resource_claim_contended_after_restart"
                host.action_runs[run.correlation_id] = run
                host._idempotency_runs[run.idempotency_key] = run
                host._resource_locks.add(str(run.resource_id))
                continue
            if run.state is not ActionRunState.EXECUTION_UNKNOWN:
                run.transition(ActionRunState.EXECUTION_UNKNOWN)
            run.outcome = "duplicate_active_resource_after_restart"
            run.shadow_mode = True
            host.action_runs[run.correlation_id] = run
            host._idempotency_runs[run.idempotency_key] = run
            host._resource_locks.add(str(run.resource_id))
            await emit_action_run(host, run)
            continue
        if run.state is ActionRunState.EXECUTING:
            run.transition(ActionRunState.EXECUTION_UNKNOWN)
            run.outcome = "execution_state_unknown_after_restart"
            run.shadow_mode = True
        if run.resolved_autonomy_ceiling is Autonomy.SHADOW_ONLY:
            run.shadow_mode = True
        host.action_runs[run.correlation_id] = run
        host._idempotency_runs[run.idempotency_key] = run
        if run.resource_id:
            host._resource_locks.add(str(run.resource_id))
        await resume_rehydrated(host, run)
    return len(active)


async def resume_rehydrated(host: ThorPersistenceHost, run: ActionRun) -> None:
    """Republish or safely continue one durable non-terminal state."""
    if run.state is ActionRunState.VERDICTED:
        await emit_action_run(host, run)
        if run.verdict == "deny":
            run.transition(ActionRunState.DENY_DROPPED)
            await emit_action_run(host, run)
            release_lock(host, run.resource_id)
        elif run.verdict == "hil":
            run.transition(ActionRunState.HIL_PENDING)
            await emit_action_run(host, run)
        else:
            await host._execute(run)
        return
    if run.state is ActionRunState.APPROVED:
        await host._execute(run)
        return
    if run.state is ActionRunState.EXECUTING:
        run.transition(ActionRunState.EXECUTION_UNKNOWN)
        run.outcome = "execution_publication_unknown"
        run.shadow_mode = True
    await emit_action_run(host, run)


def release_lock(host: ThorPersistenceHost, resource_id: Any) -> None:
    if not resource_id:
        return
    normalized = str(resource_id)
    if any(
        run.resource_id == normalized and run.state not in _TERMINAL_STATES
        for run in host.action_runs.values()
    ):
        return
    host._resource_locks.discard(normalized)


def evict_terminal_overflow(host: ThorPersistenceHost) -> None:
    """Bound retained runs without removing active or unresolved recovery state."""
    if len(host.action_runs) <= host._max_retained_runs:
        return
    overflow = len(host.action_runs) - host._max_retained_runs
    for correlation_id, run in list(host.action_runs.items()):
        if overflow <= 0:
            break
        if (
            run.state in _TERMINAL_STATES
            and run.state is not ActionRunState.ROLLBACK_FAILED
            and not run.resource_claimed
            and run.terminal_published
        ):
            del host.action_runs[correlation_id]
            if host._idempotency_runs.get(run.idempotency_key) is run:
                del host._idempotency_runs[run.idempotency_key]
            overflow -= 1


def find_active_run(host: ThorPersistenceHost, resource_id: str) -> ActionRun | None:
    return next(
        (
            run
            for run in host.action_runs.values()
            if run.resource_id == resource_id and run.state not in _TERMINAL_STATES
        ),
        None,
    )


async def emit_action_run(host: ThorPersistenceHost, run: ActionRun) -> None:
    """Write through one transition before publishing the owned ActionRun event."""
    if host._state_store is not None:
        await host._state_store.save(run)
    evict_terminal_overflow(host)
    if host.bus is None:
        if (
            host._state_store is not None
            and run.state in _TERMINAL_STATES
            and not run.resource_claimed
        ):
            await host._state_store.delete(run.correlation_id)
        if run.state in _TERMINAL_STATES:
            run.terminal_published = True
        return
    payload = {
        "producer_principal": "Thor",
        "correlation_id": run.correlation_id,
        "idempotency_key": f"{run.correlation_id}:{run.state.value}",
        "action_idempotency_key": run.idempotency_key,
        "action_type": run.action_type,
        "resource_id": run.resource_id,
        "state": run.state.value,
        "shadow_mode": run.shadow_mode,
        "resolved_autonomy_ceiling": run.resolved_autonomy_ceiling.value,
        "outcome": run.outcome,
        **effect_publication_fields(run),
        "verdict": run.verdict,
        "params": deepcopy(run.params),
        "quorum_required": run.quorum_required,
        "initiator_principal": run.initiator_principal,
        "rollback_contract": run.rollback_contract,
        "rollback_ref": run.rollback_ref,
        "decision_case": run.decision_case,
        "operational_context": deepcopy(run.operational_context),
        "workflow_action": deepcopy(run.workflow_action),
        "kinetic_proposal": deepcopy(run.kinetic_proposal),
        "prospective_lineage": deepcopy(run.prospective_lineage),
        "execution_audit_receipt": run.execution_audit_receipt,
        "approval_expires_at": (
            run.approval_expires_at.isoformat() if run.approval_expires_at is not None else None
        ),
    }
    if run.action_id is not None:
        payload["action_id"] = run.action_id
    payload["action_run_identity"] = action_run_identity_digest(payload)
    if run.state in _TERMINAL_STATES:
        payload["terminal_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    await host.bus.publish("Thor", "object.action-run", payload)
    if run.state in _TERMINAL_STATES:
        run.terminal_published = True
        if not run.resource_claimed:
            await delete_terminal_state(host, run)


async def delete_terminal_state(host: ThorPersistenceHost, run: ActionRun) -> None:
    if host._state_store is not None:
        await host._state_store.delete(run.correlation_id)


async def finalize_terminal_replay(host: ThorPersistenceHost, run: ActionRun) -> None:
    if run.state is ActionRunState.ROLLBACK_FAILED:
        return
    await release_resource_claim(host, run)
    if run.resource_claimed:
        return
    await delete_terminal_state(host, run)
    release_lock(host, run.resource_id)


async def release_resource_claim(host: ThorPersistenceHost, run: ActionRun) -> None:
    if not run.resource_claimed or not run.resource_id or host._state_store is None:
        return
    release = getattr(host._state_store, "release_resource", None)
    if not callable(release):
        return
    if run.state in _TERMINAL_STATES and run.terminal_published:
        refresh = getattr(host._state_store, "refresh_resource_claim", None)
        if not callable(refresh) or not await refresh(run):
            host.record_behavior("execution_resource_claim:refresh_failed")
            return
        await delete_terminal_state(host, run)
    if await release(str(run.resource_id), run.correlation_id):
        run.resource_claimed = False
    else:
        host.record_behavior("execution_resource_claim:retained")


__all__ = [
    "delete_terminal_state",
    "emit_action_run",
    "evict_terminal_overflow",
    "finalize_terminal_replay",
    "find_active_run",
    "rehydrate",
    "release_lock",
    "release_resource_claim",
    "resume_rehydrated",
]
