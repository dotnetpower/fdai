"""Durable replay and publication lifecycle owned by Thor."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

from fdai.agents._framework.action_run_identity import durable_correlation_reservation
from fdai.agents._framework.action_run_state import (
    TERMINAL_ACTION_RUN_STATES as _TERMINAL_STATES,
)
from fdai.agents._framework.action_run_state import ActionRunState
from fdai.agents._framework.advisory_verdicts import is_advisory_arbitration_verdict
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.thor_action_run import ActionRun, ActionRunStore
from fdai.agents._framework.thor_effect_verification import effect_publication_fields
from fdai.shared.contracts.models import Autonomy

_TIMESTAMPED_ACTION_RUN_STATES = _TERMINAL_STATES | frozenset({ActionRunState.FAILED})


class ThorPersistenceHost(Protocol):
    bus: PantheonBus | None
    action_runs: dict[str, ActionRun]
    _idempotency_runs: dict[str, ActionRun]
    _resource_locks: set[str]
    _max_retained_runs: int
    _state_store: ActionRunStore | None

    async def _execute(self, run: ActionRun) -> None: ...

    def _now(self) -> datetime: ...

    def record_behavior(self, key: str) -> None: ...


async def hold_advisory_correlation(
    host: ThorPersistenceHost,
    verdict: Mapping[str, Any],
) -> None:
    """Durably hold an advisory arbitration correlation without creating an ActionRun.

    The governed path records an ActionRun for an arbitration Verdict, and that record's
    durable correlation claim refuses any later Verdict on the correlation, including after
    a restart. The default-profile advisory Verdict creates no ActionRun, so Thor writes a
    terminal non-action claim in its own store instead. Nothing is emitted, approved, locked,
    or executed; an existing row for the correlation is left unchanged, and a store without
    reservation support keeps the in-process Forseti gate only, as the in-memory governed
    path does.
    """

    reserve = getattr(host._state_store, "reserve_correlation", None)
    correlation_id = str(verdict.get("correlation_id") or "")
    if not callable(reserve) or not correlation_id or not is_advisory_arbitration_verdict(verdict):
        return
    reserved = await reserve(
        durable_correlation_reservation(
            correlation_id=correlation_id,
            resource_id=str(verdict.get("resource_id") or ""),
            recorded_at=host._now(),
        )
    )
    host.record_behavior("advisory_correlation:" + ("reserved" if reserved else "already_claimed"))


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
            if not run.terminal_published:
                await emit_action_run(host, run)
            if not run.terminal_published:
                continue
            await finalize_terminal_replay(host, run)
            continue
        if not _valid_batch_target_set(run):
            run.transition(ActionRunState.DENY_DROPPED)
            run.outcome = "batch_target_set_digest_mismatch"
            run.shadow_mode = True
            host.action_runs[run.correlation_id] = run
            host._idempotency_runs[run.idempotency_key] = run
            if run.resource_id:
                host._resource_locks.add(str(run.resource_id))
            await _publish_rehydrate_hold_without_save(host, run)
            release_lock(host, run.resource_id)
            host.record_behavior("batch_target_set:digest_mismatch")
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
                run.shadow_mode = True
                host.action_runs[run.correlation_id] = run
                host._idempotency_runs[run.idempotency_key] = run
                host._resource_locks.add(str(run.resource_id))
                await emit_action_run(host, run)
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
        if (
            run.state is ActionRunState.HIL_PENDING
            and run.approval_expires_at is not None
            and host._now() >= run.approval_expires_at
        ):
            run.transition(ActionRunState.REJECTED)
            run.outcome = "approval_expired"
            host.action_runs[run.correlation_id] = run
            host._idempotency_runs[run.idempotency_key] = run
            if run.resource_id:
                host._resource_locks.add(str(run.resource_id))
            await emit_action_run(host, run)
            await release_resource_claim(host, run)
            release_lock(host, run.resource_id)
            host.record_behavior("approval:expired")
            continue
        if run.resolved_autonomy_ceiling is Autonomy.SHADOW_ONLY:
            run.shadow_mode = True
        host.action_runs[run.correlation_id] = run
        host._idempotency_runs[run.idempotency_key] = run
        if run.resource_id:
            host._resource_locks.add(str(run.resource_id))
        await resume_rehydrated(host, run)
    return len(active)


def _valid_batch_target_set(run: ActionRun) -> bool:
    if run.batch_role != "rollup":
        return True
    if run.target_set is None or run.target_set_digest is None:
        return False
    encoded = json.dumps(
        list(run.target_set),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest() == run.target_set_digest


async def _publish_rehydrate_hold_without_save(host: ThorPersistenceHost, run: ActionRun) -> None:
    if host.bus is None:
        return
    payload = {
        **run.publication_identity_payload(),
        "producer_principal": "Thor",
        "idempotency_key": f"{run.correlation_id}:{run.state.value}",
        "state": run.state.value,
        "shadow_mode": run.shadow_mode,
        "resolved_autonomy_ceiling": run.resolved_autonomy_ceiling.value,
        "outcome": run.outcome,
        "rollback_ref": run.rollback_ref,
        "dry_run_evidence": run.dry_run_evidence,
        "dry_run_receipt": run.dry_run_receipt,
        "preflight_simulation_receipt": run.preflight_simulation_receipt,
        "preflight_required": run.preflight_required,
        "execution_audit_receipt": run.execution_audit_receipt,
        "cost_annotation": run.cost_annotation,
        **({"batch_rollup": run.batch_rollup} if run.batch_rollup is not None else {}),
        "approval_expires_at": (
            run.approval_expires_at.isoformat() if run.approval_expires_at is not None else None
        ),
        "effect_verification_expires_at": (
            run.effect_verification_expires_at.isoformat()
            if run.effect_verification_expires_at is not None
            else None
        ),
        "action_run_identity": run.action_run_identity(),
        "terminal_at": host._now().isoformat().replace("+00:00", "Z"),
    }
    await host.bus.publish("Thor", "object.action-run", payload)


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
    terminal_state = run.state in _TERMINAL_STATES
    claimed_terminal_publication = (
        terminal_state and host.bus is not None and not run.terminal_published
    )
    already_terminal_published = terminal_state and run.terminal_published
    if claimed_terminal_publication:
        run.terminal_published = True
    if host._state_store is not None:
        await host._state_store.save(run)
    evict_terminal_overflow(host)
    if already_terminal_published and not claimed_terminal_publication:
        host.record_behavior("action_run:duplicate_publication_suppressed")
        return
    if host.bus is None:
        if run.state in _TERMINAL_STATES:
            if host._state_store is None:
                run.terminal_published = True
            host.record_behavior("action_run:terminal_publication_pending")
        return
    payload = {
        **run.publication_identity_payload(),
        "producer_principal": "Thor",
        "idempotency_key": f"{run.correlation_id}:{run.state.value}",
        "state": run.state.value,
        "shadow_mode": run.shadow_mode,
        "resolved_autonomy_ceiling": run.resolved_autonomy_ceiling.value,
        "outcome": run.outcome,
        **effect_publication_fields(run),
        "rollback_ref": run.rollback_ref,
        "dry_run_evidence": run.dry_run_evidence,
        "dry_run_receipt": run.dry_run_receipt,
        "preflight_simulation_receipt": run.preflight_simulation_receipt,
        "preflight_required": run.preflight_required,
        "execution_audit_receipt": run.execution_audit_receipt,
        "cost_annotation": run.cost_annotation,
        **({"batch_rollup": run.batch_rollup} if run.batch_rollup is not None else {}),
        "approval_expires_at": (
            run.approval_expires_at.isoformat() if run.approval_expires_at is not None else None
        ),
        "effect_verification_expires_at": (
            run.effect_verification_expires_at.isoformat()
            if run.effect_verification_expires_at is not None
            else None
        ),
        "action_run_identity": run.action_run_identity(),
    }
    if run.evidence_rejection_ref is not None:
        payload["evidence_rejection_ref"] = run.evidence_rejection_ref
    if run.state in _TIMESTAMPED_ACTION_RUN_STATES:
        payload["terminal_at"] = host._now().isoformat().replace("+00:00", "Z")
    try:
        await host.bus.publish("Thor", "object.action-run", payload)
    except Exception:
        if claimed_terminal_publication:
            run.terminal_published = False
            if host._state_store is not None:
                await host._state_store.save(run)
        raise
    if terminal_state:
        await asyncio.shield(_checkpoint_terminal_publication(host, run))


async def _checkpoint_terminal_publication(host: ThorPersistenceHost, run: ActionRun) -> None:
    run.terminal_published = True
    if host._state_store is not None:
        await host._state_store.save(run)
    if not run.resource_claimed:
        await delete_terminal_state(host, run)


async def delete_terminal_state(host: ThorPersistenceHost, run: ActionRun) -> None:
    if host._state_store is not None:
        await host._state_store.delete(run.correlation_id)


async def finalize_terminal_replay(host: ThorPersistenceHost, run: ActionRun) -> None:
    if run.state in {ActionRunState.ROLLBACK_FAILED, ActionRunState.ROLLBACK_REFUSED}:
        await release_resource_claim(host, run)
        release_lock(host, run.resource_id)
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
    if await release(str(run.resource_id), run.correlation_id):
        run.resource_claimed = False
        if run.state in _TERMINAL_STATES and run.terminal_published:
            await delete_terminal_state(host, run)
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
