"""Thor - Responder (Wave 3 behavior).

Thor dispatches verdicts. It enforces per-resource mutex, tracks
ActionRun state through the lifecycle, requests HIL approval via Var,
and triggers rollback via Vidar on failure.

Hard dependencies (per pantheon 4.3):
- Saga must be reachable (audit chain must accept appends) - degrades
  new mutations to shadow when absent.
- Vidar must be reachable - degrades new mutations to shadow when
  absent.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable
from weakref import WeakValueDictionary

from pydantic import ValidationError

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    capability_facts,
    mentioned,
)
from fdai.agents._framework.pantheon import _THOR
from fdai.core.executor.safeguards import resource_lock_key
from fdai.core.operational_planning import KineticActionProposal
from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.resource_lock import ResourceLock


class ActionRunState(StrEnum):
    PROPOSED = "proposed"
    VERDICTED = "verdicted"
    HIL_PENDING = "hil_pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DENY_DROPPED = "deny_dropped"
    EXECUTING = "executing"
    EXECUTION_UNKNOWN = "execution_unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"


# Terminal states: an ActionRun in one of these is finished, so a durable
# store drops it (only in-flight runs are rehydrated on restart).
_TERMINAL_STATES: frozenset[ActionRunState] = frozenset(
    {
        ActionRunState.SUCCEEDED,
        ActionRunState.REJECTED,
        ActionRunState.DENY_DROPPED,
        ActionRunState.ROLLED_BACK,
        ActionRunState.ROLLBACK_FAILED,
    }
)


ActionExecutor = Callable[[dict[str, Any]], Awaitable[bool]]
"""Callable that mutates the target and returns True on success."""

ExecutionAuditRecorder = Callable[["ActionRun"], Awaitable[str]]
"""Persist one Saga-owned pre-execution intent and return its receipt id."""


class _ReentrantAsyncLock:
    """Serialize a correlation while allowing synchronous bus callbacks in one task."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task[Any] | None = None
        self._depth = 0

    async def __aenter__(self) -> None:
        current = asyncio.current_task()
        if current is not None and current is self._owner:
            self._depth += 1
            return
        await self._lock.acquire()
        self._owner = current
        self._depth = 1

    async def __aexit__(self, *_args: object) -> None:
        if asyncio.current_task() is not self._owner:
            raise RuntimeError("correlation lock released by a non-owner task")
        self._depth -= 1
        if self._depth == 0:
            self._owner = None
            self._lock.release()


class _ExecutionResourceUnavailableError(RuntimeError):
    """The cross-replica mutation lock could not be acquired."""


@dataclass
class ActionRun:
    correlation_id: str
    action_type: str
    resource_id: str | None
    state: ActionRunState
    verdict: str  # auto | hil | deny
    idempotency_key: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    shadow_mode: bool = False
    resolved_autonomy_ceiling: Autonomy = Autonomy.SHADOW_ONLY
    quorum_required: int = 1
    outcome: str | None = None
    initiator_principal: str | None = None
    rollback_contract: str = "state_forward_only"
    rollback_ref: str | None = None
    decision_case: dict[str, Any] | None = None
    operational_context: dict[str, Any] | None = None
    workflow_action: dict[str, str] | None = None
    kinetic_proposal: dict[str, Any] | None = None
    execution_audit_receipt: str | None = None
    approval_expires_at: datetime | None = None
    terminal_published: bool = False
    resource_claimed: bool = False
    history: list[ActionRunState] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.idempotency_key:
            self.idempotency_key = self.correlation_id

    def transition(self, new_state: ActionRunState) -> None:
        self.history.append(self.state)
        self.state = new_state

    def to_dict(self) -> dict[str, Any]:
        """Serialize for a durable :class:`ActionRunStore` backend."""
        return {
            "correlation_id": self.correlation_id,
            "action_type": self.action_type,
            "resource_id": self.resource_id,
            "state": self.state.value,
            "verdict": self.verdict,
            "idempotency_key": self.idempotency_key,
            "params": deepcopy(self.params),
            "shadow_mode": self.shadow_mode,
            "resolved_autonomy_ceiling": self.resolved_autonomy_ceiling.value,
            "quorum_required": self.quorum_required,
            "outcome": self.outcome,
            "initiator_principal": self.initiator_principal,
            "rollback_contract": self.rollback_contract,
            "rollback_ref": self.rollback_ref,
            "decision_case": self.decision_case,
            "operational_context": deepcopy(self.operational_context),
            "workflow_action": deepcopy(self.workflow_action),
            "kinetic_proposal": deepcopy(self.kinetic_proposal),
            "execution_audit_receipt": self.execution_audit_receipt,
            "approval_expires_at": (
                self.approval_expires_at.isoformat()
                if self.approval_expires_at is not None
                else None
            ),
            "terminal_published": False,
            "resource_claimed": self.resource_claimed,
            "history": [s.value for s in self.history],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActionRun:
        operational_context = _bounded_operational_context(data.get("operational_context"))
        resolved_autonomy_ceiling = Autonomy(
            data.get("resolved_autonomy_ceiling", Autonomy.SHADOW_ONLY.value)
        )
        if data.get("operational_context") is not None and operational_context is None:
            resolved_autonomy_ceiling = Autonomy.SHADOW_ONLY
        run = cls(
            correlation_id=str(data["correlation_id"]),
            action_type=str(data["action_type"]),
            resource_id=data.get("resource_id"),
            state=ActionRunState(data["state"]),
            verdict=str(data["verdict"]),
            idempotency_key=str(data.get("idempotency_key") or data["correlation_id"]),
            params=deepcopy(dict(data.get("params") or {})),
            shadow_mode=bool(data.get("shadow_mode", False)),
            resolved_autonomy_ceiling=resolved_autonomy_ceiling,
            quorum_required=int(data.get("quorum_required", 1)),
            outcome=data.get("outcome"),
            initiator_principal=data.get("initiator_principal"),
            rollback_contract=str(data.get("rollback_contract", "state_forward_only")),
            rollback_ref=data.get("rollback_ref"),
            decision_case=_bounded_decision_case(data.get("decision_case")),
            operational_context=operational_context,
            workflow_action=_bounded_workflow_action(data.get("workflow_action")),
            kinetic_proposal=_durable_kinetic_proposal(data.get("kinetic_proposal")),
            execution_audit_receipt=_optional_bounded_text(
                data.get("execution_audit_receipt"),
                field_name="execution_audit_receipt",
            ),
            approval_expires_at=_optional_datetime(
                data.get("approval_expires_at"),
                field_name="approval_expires_at",
            ),
            terminal_published=bool(data.get("terminal_published", False)),
            resource_claimed=bool(data.get("resource_claimed", False)),
        )
        run.history = [ActionRunState(s) for s in data.get("history", [])]
        _require_bound_kinetic_proposal(run)
        return run


@runtime_checkable
class ActionRunStore(Protocol):
    """Durable persistence seam for in-flight ActionRuns.

    Upstream default is in-memory (no store); a fork injects a
    StateStore-backed implementation so an enforce-mode pantheon does not
    lose track of in-progress mutations across a restart. Terminal runs
    are deleted, so :meth:`load_active` returns only in-flight work.
    """

    async def save(self, run: ActionRun) -> None: ...

    async def load_active(self) -> list[ActionRun]: ...

    async def delete(self, correlation_id: str) -> None: ...

    async def claim_resource(
        self,
        run: ActionRun,
    ) -> Literal["acquired", "contended", "completed"]: ...

    async def release_resource(self, resource_id: str, correlation_id: str) -> bool: ...

    async def refresh_resource_claim(self, run: ActionRun) -> bool: ...

    async def validate_resource_claim(self, run: ActionRun) -> bool: ...


class Thor(Agent):
    """Wave-3 Thor: dispatcher + per-resource mutex + lifecycle owner."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        executor: ActionExecutor | None = None,
        shadow_required: Callable[[], bool] | None = None,
        shadow_by_default: bool = False,
        saga_available: bool = True,
        vidar_available: bool = True,
        state_store: ActionRunStore | None = None,
        execution_audit_recorder: ExecutionAuditRecorder | None = None,
        require_execution_audit: bool = False,
        hil_timeout_seconds: int = 3_600,
        executor_timeout_seconds: float = 300.0,
        clock: Callable[[], datetime] | None = None,
        execution_resource_lock: ResourceLock | None = None,
        require_execution_resource_lock: bool = False,
    ) -> None:
        if isinstance(hil_timeout_seconds, bool) or hil_timeout_seconds < 1:
            raise ValueError("hil_timeout_seconds MUST be a positive integer")
        if executor_timeout_seconds <= 0:
            raise ValueError("executor_timeout_seconds MUST be > 0")
        super().__init__(spec=_THOR)
        self.bus = bus
        self._executor = executor or _default_executor
        self._shadow_required = shadow_required or (lambda: False)
        self._shadow_by_default = shadow_by_default
        self._saga_available = saga_available
        self._vidar_available = vidar_available
        self._state_store = state_store
        self._execution_audit_recorder = execution_audit_recorder
        self._require_execution_audit = require_execution_audit
        self._hil_timeout_seconds = hil_timeout_seconds
        self._executor_timeout_seconds = executor_timeout_seconds
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._execution_resource_lock = execution_resource_lock
        self._require_execution_resource_lock = require_execution_resource_lock
        self.action_runs: dict[str, ActionRun] = {}
        self._idempotency_runs: dict[str, ActionRun] = {}
        self._resource_locks: set[str] = set()
        self._correlation_locks: WeakValueDictionary[str, _ReentrantAsyncLock] = (
            WeakValueDictionary()
        )
        self._resource_dispatch_locks: WeakValueDictionary[str, asyncio.Lock] = (
            WeakValueDictionary()
        )
        # Cap the in-memory run map so a long-running dispatcher cannot leak
        # one entry per correlation id forever. Only TERMINAL runs are
        # evicted (oldest first) once over the cap; active runs are always
        # retained (they back the per-resource mutex and approval lookup).
        self._max_retained_runs = 10_000

    def set_executor(self, executor: ActionExecutor) -> None:
        """Bind the composition root's privileged action executor."""
        self._executor = executor

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    def set_state_store(self, store: ActionRunStore) -> None:
        """Attach a durable ActionRun store (composition-root seam)."""
        self._state_store = store

    def set_execution_audit_recorder(
        self,
        recorder: ExecutionAuditRecorder | None,
        *,
        required: bool,
    ) -> None:
        """Bind the durable Saga-owned intent recorder used before executor I/O."""

        self._execution_audit_recorder = recorder
        self._require_execution_audit = required

    def set_execution_resource_lock(
        self,
        resource_lock: ResourceLock | None,
        *,
        required: bool,
    ) -> None:
        """Bind the cross-replica mutation lock required by enforce mode."""

        self._execution_resource_lock = resource_lock
        self._require_execution_resource_lock = required

    async def rehydrate(self) -> int:
        """Reload in-flight ActionRuns from the durable store on startup.

        Restores the per-resource locks so a restart cannot start a second
        run on a resource that already had one in flight. Returns the
        number of runs restored. No-op without a store.
        """
        if self._state_store is None:
            return 0
        active = await self._state_store.load_active()
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
                self.action_runs[run.correlation_id] = run
                self._idempotency_runs[run.idempotency_key] = run
                await self._emit_action_run(run)
                await self._finalize_terminal_replay(run)
                continue
            if run.resource_claimed and run.state in {
                ActionRunState.VERDICTED,
                ActionRunState.APPROVED,
                ActionRunState.EXECUTING,
            }:
                run.transition(ActionRunState.EXECUTION_UNKNOWN)
                run.outcome = "claimed_execution_requires_reconciliation"
                run.shadow_mode = True
                self.action_runs[run.correlation_id] = run
                self._idempotency_runs[run.idempotency_key] = run
                if run.resource_id:
                    self._resource_locks.add(str(run.resource_id))
                await self._emit_action_run(run)
                continue
            if (
                run.resource_id
                and resource_counts.get(str(run.resource_id), 0) > 1
                and (not run.resource_claimed or claimed_counts.get(str(run.resource_id), 0) > 1)
            ):
                if not run.resource_claimed:
                    run.outcome = "resource_claim_contended_after_restart"
                    self.action_runs[run.correlation_id] = run
                    self._idempotency_runs[run.idempotency_key] = run
                    self._resource_locks.add(str(run.resource_id))
                    continue
                if run.state is not ActionRunState.EXECUTION_UNKNOWN:
                    run.transition(ActionRunState.EXECUTION_UNKNOWN)
                run.outcome = "duplicate_active_resource_after_restart"
                run.shadow_mode = True
                self.action_runs[run.correlation_id] = run
                self._idempotency_runs[run.idempotency_key] = run
                self._resource_locks.add(str(run.resource_id))
                await self._emit_action_run(run)
                continue
            if run.state is ActionRunState.EXECUTING:
                run.transition(ActionRunState.EXECUTION_UNKNOWN)
                run.outcome = "execution_state_unknown_after_restart"
                run.shadow_mode = True
            if run.resolved_autonomy_ceiling is Autonomy.SHADOW_ONLY:
                run.shadow_mode = True
            self.action_runs[run.correlation_id] = run
            self._idempotency_runs[run.idempotency_key] = run
            if run.resource_id:
                self._resource_locks.add(str(run.resource_id))
            await self._resume_rehydrated(run)
        return len(active)

    async def _resume_rehydrated(self, run: ActionRun) -> None:
        """Republish or safely continue one durable non-terminal state."""

        if run.state is ActionRunState.VERDICTED:
            await self._emit_action_run(run)
            if run.verdict == "deny":
                run.transition(ActionRunState.DENY_DROPPED)
                await self._emit_action_run(run)
                self._release_lock(run.resource_id)
            elif run.verdict == "hil":
                run.transition(ActionRunState.HIL_PENDING)
                await self._emit_action_run(run)
            else:
                await self._execute(run)
            return
        if run.state is ActionRunState.APPROVED:
            await self._execute(run)
            return
        if run.state is ActionRunState.EXECUTING:
            run.transition(ActionRunState.EXECUTION_UNKNOWN)
            run.outcome = "execution_publication_unknown"
            run.shadow_mode = True
        await self._emit_action_run(run)

    def set_shadow(self, enabled: bool) -> None:
        """Force shadow mode on / off for every future dispatch.

        The composition root (:class:`~fdai.agents.runtime.PantheonRuntime`)
        calls this to keep the pantheon Thor judge-and-log only, so it
        never double-executes alongside the P1 control loop. Enforce is an
        explicit, separately reviewed promotion - never the default.
        """
        self._shadow_by_default = enabled

    def set_shadow_required(self, predicate: Callable[[], bool]) -> None:
        """Bind a live fail-closed authority predicate for future execution."""
        self._shadow_required = predicate

    def _must_shadow(self) -> bool:
        if self._shadow_by_default:
            return True
        try:
            return self._shadow_required()
        except Exception:  # noqa: BLE001 - authority-provider failure must fail closed
            self.record_behavior("authority:unavailable")
            return True

    def health(self) -> dict[str, Any]:
        """Expose dispatcher state for Heimdall's probe / runtime health."""
        active = sum(1 for r in self.action_runs.values() if r.state not in _TERMINAL_STATES)
        return {
            "agent": "Thor",
            "status": "ok",
            "active_runs": active,
            "retained_runs": len(self.action_runs),
            "locked_resources": len(self._resource_locks),
            "shadow_forced": self._shadow_by_default,
            "behavior": self.behavior_snapshot(),
        }

    # ---- typed port ----------------------------------------------------

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == "object.verdict":
            if payload.get("kind") == "document_ingestion":
                self.record_behavior("document_verdict_ignored")
                return
            if payload.get("kind") == "architecture_review":
                self.record_behavior("architecture_review_verdict_ignored")
                return
            await self.dispatch_verdict(payload)
        elif topic == "object.approval":
            if payload.get("kind") == "document_ingestion":
                self.record_behavior("document_approval_ignored")
                return
            await self._handle_approval(payload)
        elif topic == "object.rollback":
            await self._handle_rollback(payload)

    # ---- lifecycle -----------------------------------------------------

    async def dispatch_verdict(self, verdict: dict[str, Any]) -> ActionRun:
        """Serialize duplicate delivery for one correlation before dispatch."""

        correlation = str(verdict.get("correlation_id", ""))
        lock = self._correlation_locks.setdefault(correlation, _ReentrantAsyncLock())
        async with lock:
            resource_id = str(verdict.get("resource_id") or "")
            if resource_id:
                resource_lock = self._resource_dispatch_locks.setdefault(
                    resource_id,
                    asyncio.Lock(),
                )
                async with resource_lock:
                    return await self._dispatch_verdict_once(verdict)
            return await self._dispatch_verdict_once(verdict)

    async def _dispatch_verdict_once(self, verdict: dict[str, Any]) -> ActionRun:
        correlation = str(verdict.get("correlation_id", ""))
        action_type = str(verdict.get("action_type", ""))
        risk_verdict = str(verdict.get("risk_verdict", "hil"))
        resolved_autonomy_ceiling = _resolved_autonomy_ceiling(verdict)
        if resolved_autonomy_ceiling is Autonomy.ENFORCE_HIL and risk_verdict == "auto":
            risk_verdict = "hil"
        resource_id = verdict.get("resource_id")
        raw_decision_case = verdict.get("decision_case")
        decision_case = _bounded_decision_case(raw_decision_case)
        raw_params = verdict.get("params")
        params = deepcopy(dict(raw_params)) if isinstance(raw_params, Mapping) else {}
        operational_context = _bounded_operational_context(verdict.get("operational_context"))
        if verdict.get("operational_context") is not None and operational_context is None:
            resolved_autonomy_ceiling = Autonomy.SHADOW_ONLY
        raw_kinetic_proposal = verdict.get("kinetic_proposal")
        kinetic_proposal = _kinetic_proposal(raw_kinetic_proposal)
        semantic_arbitration = verdict.get("reason") in {
            "arbitration_resolved",
            "arbitration_unresolved",
        }
        invalid_decision_case = raw_decision_case is not None and (
            decision_case is None
            or not action_type
            or not _selected_action_matches(decision_case, action_type)
        )
        invalid_kinetic_proposal = raw_kinetic_proposal is not None and (
            kinetic_proposal is None
            or not _kinetic_proposal_matches(
                kinetic_proposal,
                correlation_id=correlation,
                action_type=action_type,
                resource_id=resource_id,
                params=params,
                decision_case=decision_case,
            )
        )
        if (
            (semantic_arbitration and decision_case is None)
            or invalid_decision_case
            or invalid_kinetic_proposal
        ):
            risk_verdict = "deny"
            action_type = ""
            kinetic_proposal = None
            if invalid_kinetic_proposal:
                self.record_behavior("kinetic_proposal:invalid")
        elif kinetic_proposal is not None:
            self.record_behavior("kinetic_proposal:validated")

        # Idempotency: at-least-once delivery means the same verdict can arrive
        # twice. Keying the run by correlation is not enough - a re-delivery
        # after the first run terminated (lock released) would start a SECOND
        # run and re-execute. Return the existing run for a correlation we have
        # already dispatched, so a duplicate verdict is a no-op (defense in
        # depth with the event idempotency_key dedup at ingress).
        existing_by_corr = self.action_runs.get(correlation)
        if existing_by_corr is not None:
            self.record_behavior("dispatch:duplicate")
            if existing_by_corr.state not in _TERMINAL_STATES:
                await self._resume_rehydrated(existing_by_corr)
            elif not existing_by_corr.terminal_published:
                await self._emit_action_run(existing_by_corr)
                await self._finalize_terminal_replay(existing_by_corr)
            else:
                await self._finalize_terminal_replay(existing_by_corr)
            return existing_by_corr
        idempotency_key = str(verdict.get("idempotency_key") or correlation)
        existing_by_idempotency = self._idempotency_runs.get(idempotency_key)
        if existing_by_idempotency is not None:
            self.record_behavior("dispatch:idempotent_duplicate")
            return existing_by_idempotency

        # Per-resource mutex: refuse to start a new run while another is
        # active on the same resource. Second dispatcher waits for the
        # first to terminate before starting.
        if resource_id and resource_id in self._resource_locks:
            existing = self._find_active_run(str(resource_id))
            if existing is not None:
                self.record_behavior("dispatch:lock_contention")
                raise RuntimeError("resource already has an active ActionRun")
            retained = next(
                (
                    run
                    for run in self.action_runs.values()
                    if run.resource_id == str(resource_id) and run.state in _TERMINAL_STATES
                ),
                None,
            )
            if retained is not None:
                self.record_behavior("dispatch:terminal_fence")
                if retained.terminal_published:
                    await self._finalize_terminal_replay(retained)
                else:
                    await self._emit_action_run(retained)
                    await self._finalize_terminal_replay(retained)
            else:
                raise RuntimeError("resource mutation fence has no recoverable ActionRun")

        # Degrade to shadow when hard dependencies are missing.
        shadow_mode = (
            resolved_autonomy_ceiling is Autonomy.SHADOW_ONLY
            or self._must_shadow()
            or not (self._saga_available and self._vidar_available)
        )

        # Propagate the approval quorum the judge set (2 for irreversible
        # actions, agent-pantheon.md 4.6). Floor at 1 so a forged / malformed
        # verdict can never yield a zero-or-negative quorum that would let an
        # action execute with no approver; Thor MUST NOT hard-code 1 and drop
        # the judge's two-approver requirement.
        quorum_required = max(1, int(verdict.get("quorum_required", 1)))
        run = ActionRun(
            correlation_id=correlation,
            action_type=action_type,
            resource_id=resource_id,
            state=ActionRunState.VERDICTED,
            verdict=risk_verdict,
            idempotency_key=str(verdict.get("idempotency_key") or correlation),
            params=params,
            shadow_mode=shadow_mode,
            resolved_autonomy_ceiling=resolved_autonomy_ceiling,
            quorum_required=quorum_required,
            initiator_principal=verdict.get("initiator_principal"),
            rollback_contract=str(verdict.get("rollback_contract", "state_forward_only")),
            decision_case=decision_case,
            operational_context=operational_context,
            workflow_action=_bounded_workflow_action(verdict.get("workflow_action")),
            kinetic_proposal=(
                kinetic_proposal.model_dump(mode="json") if kinetic_proposal is not None else None
            ),
            approval_expires_at=(
                self._now() + timedelta(seconds=self._hil_timeout_seconds)
                if risk_verdict == "hil"
                else None
            ),
        )
        self.action_runs[correlation] = run
        self._idempotency_runs[run.idempotency_key] = run
        if resource_id:
            self._resource_locks.add(str(resource_id))
        try:
            if risk_verdict == "auto" and not shadow_mode:
                if not await self._claim_execution_resource(run):
                    run.transition(ActionRunState.DENY_DROPPED)
                    run.outcome = "duplicate_execution_already_completed"
                    await self._emit_action_run(run)
                    self._release_lock(resource_id)
                    return run
            # Emit the initial VERDICTED state so downstream consumers
            # (audit chain, Var) see the lifecycle start.
            await self._emit_action_run(run)
            # Measurable behaviour: the dispatch verdict split (+ shadow), so a
            # scenario test reads dispatch:auto / dispatch:hil / dispatch:deny
            # and dispatch:shadow to assert 'shadow never mutates' and 'deny
            # never reaches Var' without touching private state.
            self.record_behavior(f"dispatch:{risk_verdict}")
            if shadow_mode:
                self.record_behavior("dispatch:shadow")
                # Distinguish a policy shadow (forced) from a degraded shadow (a
                # hard dependency - Saga/Vidar - is down), so a scenario can see
                # a safety-relevant degradation, not just "shadow".
                if not (self._saga_available and self._vidar_available):
                    self.record_behavior("dispatch:degraded")

            if risk_verdict == "deny":
                run.transition(ActionRunState.DENY_DROPPED)
                await self._emit_action_run(run)
                self._release_lock(resource_id)
                return run

            if risk_verdict == "hil":
                run.transition(ActionRunState.HIL_PENDING)
                await self._emit_action_run(run)
                # Lock is held intentionally across the HIL wait; released
                # when _execute (on approval) or the reject path terminates.
                return run

            # auto path (releases the lock via _execute's own finally)
            await self._execute(run)
            return run
        except Exception:
            # Fail-safe: a lifecycle emit (bus hiccup) MUST NOT leave the
            # resource locked forever - that would deadlock every future
            # action on it (permanent dispatch:lock_contention). Release and
            # re-raise. The HIL path returns normally, so its intentional lock
            # hold is unaffected by this guard.
            self.record_behavior("dispatch:publication_failed")
            if run.state is ActionRunState.VERDICTED and not run.resource_claimed:
                self.action_runs.pop(run.correlation_id, None)
                if self._idempotency_runs.get(run.idempotency_key) is run:
                    self._idempotency_runs.pop(run.idempotency_key, None)
                self._release_lock(resource_id)
            raise

    async def _execute(self, run: ActionRun) -> None:
        # The per-resource lock MUST be released no matter how _execute exits:
        # it always drives the run to a terminal state, so even if a lifecycle
        # emit raises (a bus hiccup), leaving the resource locked would
        # deadlock every future action on it (permanent dispatch:lock_contention).
        release_lock = False
        try:
            run.shadow_mode = (
                run.shadow_mode
                or run.resolved_autonomy_ceiling is Autonomy.SHADOW_ONLY
                or self._must_shadow()
            )
            if not run.shadow_mode and self._require_execution_audit:
                recorder = self._execution_audit_recorder
                if recorder is None:
                    run.transition(ActionRunState.DENY_DROPPED)
                    run.outcome = "execution_audit_unavailable"
                    await self._emit_action_run(run)
                    await self._release_resource_claim(run)
                    self.record_behavior("execution_audit:unavailable")
                    release_lock = True
                    return
                try:
                    receipt = await recorder(run)
                except Exception:  # noqa: BLE001 - audit failure blocks executor I/O
                    run.transition(ActionRunState.DENY_DROPPED)
                    run.outcome = "execution_audit_failed"
                    await self._emit_action_run(run)
                    await self._release_resource_claim(run)
                    self.record_behavior("execution_audit:failed")
                    release_lock = True
                    return
                if not receipt.strip() or len(receipt) > 512:
                    run.transition(ActionRunState.DENY_DROPPED)
                    run.outcome = "execution_audit_invalid"
                    await self._emit_action_run(run)
                    await self._release_resource_claim(run)
                    self.record_behavior("execution_audit:invalid")
                    release_lock = True
                    return
                run.execution_audit_receipt = receipt
                self.record_behavior("execution_audit:recorded")
            if not run.shadow_mode and not run.resource_claimed:
                if not await self._claim_execution_resource(run):
                    run.transition(ActionRunState.DENY_DROPPED)
                    run.outcome = "duplicate_execution_already_completed"
                    await self._emit_action_run(run)
                    self._release_lock(run.resource_id)
                    return
            run.transition(ActionRunState.EXECUTING)
            await self._emit_action_run(run)
            if run.shadow_mode:
                # Shadow-mode: judge and log without mutating.
                run.transition(ActionRunState.SUCCEEDED)
                run.outcome = "shadow_success"
                await self._emit_action_run(run)
                await self._release_resource_claim(run)
                self.record_behavior("executed:shadow")
                release_lock = True
                return
            try:
                async with asyncio.timeout(self._executor_timeout_seconds):
                    success = await self._invoke_executor(run)
            except _ExecutionResourceUnavailableError as exc:
                retry_state = (
                    ActionRunState.APPROVED if run.verdict == "hil" else ActionRunState.VERDICTED
                )
                run.transition(retry_state)
                run.outcome = "execution_resource_temporarily_unavailable"
                await self._emit_action_run(run)
                self.record_behavior("execution_resource_lock:unavailable")
                raise RuntimeError("execution resource is temporarily unavailable") from exc
            except TimeoutError:
                run.transition(ActionRunState.EXECUTION_UNKNOWN)
                run.outcome = "executor_timeout"
                await self._emit_action_run(run)
                self.record_behavior("executed:unknown")
                release_lock = False
                return
            except Exception as exc:  # noqa: BLE001 (surface adapter errors)
                success = False
                run.outcome = f"executor_error:{type(exc).__name__}"
            if run.outcome == "command_accepted_lock_release_unknown":
                run.transition(ActionRunState.EXECUTION_UNKNOWN)
                await self._emit_action_run(run)
                self.record_behavior("executed:unknown")
                return
            run.transition(ActionRunState.SUCCEEDED if success else ActionRunState.FAILED)
            if success and run.outcome is None:
                run.outcome = "command_accepted_verification_pending"
            if not success and run.outcome is None:
                run.outcome = "executor returned false"
            await self._emit_action_run(run)
            self.record_behavior("executed:success" if success else "executed:failed")
            if success:
                await self._release_resource_claim(run)
            release_lock = success
        finally:
            if release_lock:
                self._release_lock(run.resource_id)

    async def _invoke_executor(self, run: ActionRun) -> bool:
        resource_id = str(run.resource_id or "")
        if not resource_id:
            raise ValueError("execution resource_id MUST be non-empty")
        resource_lock = self._execution_resource_lock
        if resource_lock is None:
            if self._require_execution_resource_lock:
                raise RuntimeError("cross-replica execution resource lock is unavailable")
            return await self._executor({"run": run})
        context = resource_lock.acquire(resource_lock_key(resource_id))
        try:
            await context.__aenter__()
        except Exception as exc:
            raise _ExecutionResourceUnavailableError from exc
        if run.resource_claimed:
            try:
                lease_seconds = getattr(self._state_store, "claim_lease_seconds", None)
                refresh_claim = getattr(self._state_store, "refresh_resource_claim", None)
                if (
                    isinstance(lease_seconds, bool)
                    or not isinstance(lease_seconds, int)
                    or lease_seconds <= self._executor_timeout_seconds
                    or not callable(refresh_claim)
                    or not await refresh_claim(run)
                ):
                    raise _ExecutionResourceUnavailableError
                validate_claim = getattr(self._state_store, "validate_resource_claim", None)
                if not callable(validate_claim) or not await validate_claim(run):
                    raise _ExecutionResourceUnavailableError
            except asyncio.CancelledError:
                try:
                    await context.__aexit__(None, None, None)
                except Exception:  # noqa: BLE001 - preserve cancellation semantics
                    self.record_behavior("execution_resource_lock:release_unknown")
                raise
            except Exception as exc:
                try:
                    await context.__aexit__(None, None, None)
                except Exception:  # noqa: BLE001 - preserve non-execution classification
                    self.record_behavior("execution_resource_lock:release_unknown")
                raise _ExecutionResourceUnavailableError from exc
        if run.outcome == "execution_resource_temporarily_unavailable":
            run.outcome = None
        try:
            result = await self._executor({"run": run})
        except BaseException as exc:
            try:
                await context.__aexit__(type(exc), exc, exc.__traceback__)
            except Exception:  # noqa: BLE001 - preserve cancellation/timeout ambiguity
                self.record_behavior("execution_resource_lock:release_unknown")
            raise
        try:
            await context.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001 - mutation result remains unknown, never failed
            run.outcome = "command_accepted_lock_release_unknown"
            self.record_behavior("execution_resource_lock:release_unknown")
        return result

    async def _claim_execution_resource(self, run: ActionRun) -> bool:
        if run.resource_claimed:
            return True
        state_store = self._state_store
        claim = getattr(state_store, "claim_resource", None)
        if not callable(claim):
            if self._require_execution_resource_lock:
                raise _ExecutionResourceUnavailableError
            return True
        result = await claim(run)
        if result == "completed":
            run.resource_claimed = False
            return False
        if result != "acquired":
            run.resource_claimed = False
            raise _ExecutionResourceUnavailableError
        run.resource_claimed = True
        return True

    async def _handle_approval(self, approval: dict[str, Any]) -> None:
        correlation = str(approval.get("correlation_id", ""))
        lock = self._correlation_locks.setdefault(correlation, _ReentrantAsyncLock())
        async with lock:
            await self._handle_approval_locked(approval, correlation=correlation)

    async def _handle_approval_locked(
        self,
        approval: dict[str, Any],
        *,
        correlation: str,
    ) -> None:
        run = self.action_runs.get(correlation)
        if run is None:
            return
        # Idempotency: only a run still awaiting its HIL decision may act on an
        # approval. At-least-once delivery can redeliver the same object.approval
        # (or a duplicate can arrive), and without this guard an approval for a
        # run already approved / executing / terminal would re-enter _execute -
        # double-executing a completed mutation via the privileged executor, or
        # re-running rollback. dispatch_verdict has its own idempotency guard;
        # this is the matching one for the approval path.
        if run.state != ActionRunState.HIL_PENDING:
            self.record_behavior("approval:duplicate")
            if run.state is ActionRunState.APPROVED:
                await self._execute(run)
                return
            if run.state in _TERMINAL_STATES and not run.terminal_published:
                await self._emit_action_run(run)
                await self._finalize_terminal_replay(run)
            elif run.state in _TERMINAL_STATES:
                await self._finalize_terminal_replay(run)
            return
        if run.approval_expires_at is None or self._now() >= run.approval_expires_at:
            await self._expire_approval(run)
            return
        if approval.get("state") == "approved":
            run.transition(ActionRunState.APPROVED)
            await self._execute(run)
        else:
            if not run.resource_claimed and not await self._claim_execution_resource(run):
                run.transition(ActionRunState.DENY_DROPPED)
                run.outcome = "duplicate_execution_already_completed"
                await self._emit_action_run(run)
                self._release_lock(run.resource_id)
                return
            try:
                run.transition(ActionRunState.REJECTED)
                await self._emit_action_run(run)
                await self._release_resource_claim(run)
            finally:
                self._release_lock(run.resource_id)

    async def expire_pending_approvals(self) -> int:
        """Expire HIL runs whose bounded approval window has elapsed."""

        expired = [
            run
            for run in self.action_runs.values()
            if run.state is ActionRunState.HIL_PENDING
            and (run.approval_expires_at is None or self._now() >= run.approval_expires_at)
        ]
        for run in expired:
            lock = self._correlation_locks.setdefault(
                run.correlation_id,
                _ReentrantAsyncLock(),
            )
            async with lock:
                if run.state is ActionRunState.HIL_PENDING and (
                    run.approval_expires_at is None or self._now() >= run.approval_expires_at
                ):
                    await self._expire_approval(run)
        return len(expired)

    async def _expire_approval(self, run: ActionRun) -> None:
        if not run.resource_claimed and not await self._claim_execution_resource(run):
            run.transition(ActionRunState.DENY_DROPPED)
            run.outcome = "duplicate_execution_already_completed"
            await self._emit_action_run(run)
            self._release_lock(run.resource_id)
            return
        try:
            run.transition(ActionRunState.REJECTED)
            run.outcome = "approval_expired"
            await self._emit_action_run(run)
            await self._release_resource_claim(run)
            self.record_behavior("approval:expired")
        finally:
            self._release_lock(run.resource_id)

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise RuntimeError("Thor clock MUST be timezone-aware")
        return now.astimezone(UTC)

    async def _handle_rollback(self, rollback: dict[str, Any]) -> None:
        correlation = str(rollback.get("correlation_id", ""))
        lock = self._correlation_locks.setdefault(correlation, _ReentrantAsyncLock())
        async with lock:
            await self._handle_rollback_locked(rollback, correlation=correlation)

    async def _handle_rollback_locked(
        self,
        rollback: dict[str, Any],
        *,
        correlation: str,
    ) -> None:
        run = self.action_runs.get(correlation)
        if (
            run is not None
            and run.state is ActionRunState.ROLLBACK_FAILED
            and rollback.get("state") == "succeeded"
        ):
            run.rollback_ref = str(rollback.get("rollback_ref") or "") or None
            run.outcome = "rollback_succeeded"
            run.transition(ActionRunState.ROLLED_BACK)
            await self._emit_action_run(run)
            await self._release_resource_claim(run)
            self._release_lock(run.resource_id)
            return
        if run is not None and run.state in _TERMINAL_STATES:
            if run.terminal_published:
                await self._finalize_terminal_replay(run)
            else:
                await self._emit_action_run(run)
                await self._finalize_terminal_replay(run)
            return
        if run is None or run.state not in {
            ActionRunState.FAILED,
            ActionRunState.EXECUTION_UNKNOWN,
        }:
            return
        succeeded = rollback.get("state") == "succeeded"
        run.rollback_ref = str(rollback.get("rollback_ref") or "") or None
        run.outcome = "rollback_succeeded" if succeeded else "rollback_failed"
        run.transition(ActionRunState.ROLLED_BACK if succeeded else ActionRunState.ROLLBACK_FAILED)
        await self._emit_action_run(run)
        self.record_behavior(run.outcome)
        if succeeded:
            await self._release_resource_claim(run)
            self._release_lock(run.resource_id)

    # ---- helpers -------------------------------------------------------

    def _release_lock(self, resource_id: Any) -> None:
        if not resource_id:
            return
        normalized = str(resource_id)
        if any(
            run.resource_id == normalized and run.state not in _TERMINAL_STATES
            for run in self.action_runs.values()
        ):
            return
        self._resource_locks.discard(normalized)

    def _evict_terminal_overflow(self) -> None:
        """Bound ``action_runs`` by evicting the oldest terminal runs.

        Active (non-terminal) runs are never evicted - they back the
        per-resource mutex and HIL approval lookup. Only once the map
        exceeds the retention cap are the oldest *terminal* runs dropped
        (dict-insertion order), so recent history stays inspectable while
        memory stays bounded over a long-running dispatcher.
        """
        if len(self.action_runs) <= self._max_retained_runs:
            return
        overflow = len(self.action_runs) - self._max_retained_runs
        for cid, run in list(self.action_runs.items()):
            if overflow <= 0:
                break
            if (
                run.state in _TERMINAL_STATES
                and run.state is not ActionRunState.ROLLBACK_FAILED
                and not run.resource_claimed
                and run.terminal_published
            ):
                del self.action_runs[cid]
                if self._idempotency_runs.get(run.idempotency_key) is run:
                    del self._idempotency_runs[run.idempotency_key]
                overflow -= 1

    def _find_active_run(self, resource_id: str) -> ActionRun | None:
        for run in self.action_runs.values():
            if run.resource_id == resource_id and run.state not in _TERMINAL_STATES:
                return run
        return None

    async def _emit_action_run(self, run: ActionRun) -> None:
        # Durable write-through records every transition before publication.
        # Terminal rows are deleted only after publish succeeds, so a restart
        # can replay a terminal transition that the broker never accepted.
        if self._state_store is not None:
            await self._state_store.save(run)
        self._evict_terminal_overflow()
        if self.bus is None:
            if (
                self._state_store is not None
                and run.state in _TERMINAL_STATES
                and not run.resource_claimed
            ):
                await self._state_store.delete(run.correlation_id)
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
            "operational_success": False,
            "effect_verification_status": (
                "pending"
                if run.outcome == "command_accepted_verification_pending"
                else "not_applicable"
            ),
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
            "execution_audit_receipt": run.execution_audit_receipt,
            "approval_expires_at": (
                run.approval_expires_at.isoformat() if run.approval_expires_at is not None else None
            ),
        }
        if run.state in _TERMINAL_STATES:
            payload["terminal_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
        await self.bus.publish("Thor", "object.action-run", payload)
        if run.state in _TERMINAL_STATES:
            run.terminal_published = True
            if not run.resource_claimed:
                await self._delete_terminal_state(run)

    async def _delete_terminal_state(self, run: ActionRun) -> None:
        if self._state_store is not None:
            await self._state_store.delete(run.correlation_id)

    async def _finalize_terminal_replay(self, run: ActionRun) -> None:
        if run.state is ActionRunState.ROLLBACK_FAILED:
            return
        await self._release_resource_claim(run)
        if run.resource_claimed:
            return
        await self._delete_terminal_state(run)
        self._release_lock(run.resource_id)

    async def _release_resource_claim(self, run: ActionRun) -> None:
        if not run.resource_claimed or not run.resource_id or self._state_store is None:
            return
        release = getattr(self._state_store, "release_resource", None)
        if not callable(release):
            return
        if run.state in _TERMINAL_STATES and run.terminal_published:
            refresh = getattr(self._state_store, "refresh_resource_claim", None)
            if not callable(refresh) or not await refresh(run):
                self.record_behavior("execution_resource_claim:refresh_failed")
                return
            await self._delete_terminal_state(run)
        if await release(str(run.resource_id), run.correlation_id):
            run.resource_claimed = False
        else:
            self.record_behavior("execution_resource_claim:retained")

    # ---- conversational port -------------------------------------------

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Thor answers from dispatched runs; before the first one there are none."""
        return bool(self.action_runs)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        runs = self.action_runs
        active = [r for r in runs.values() if r.state not in _TERMINAL_STATES]
        facts = {
            **capability_facts(self.spec),
            "total_runs": len(runs),
            "active_runs": len(active),
            "shadow_forced": self._shadow_by_default,
        }
        selectors = list(runs) + [r.resource_id for r in runs.values() if r.resource_id]
        keys = set(mentioned(question, selectors))
        target = None
        for run in runs.values():
            if run.correlation_id in keys or (run.resource_id and run.resource_id in keys):
                target = run
                break
        if target is not None:
            facts.update(
                {
                    "correlation_id": target.correlation_id,
                    "action_type": target.action_type,
                    "resource_id": target.resource_id,
                    "state": target.state.value,
                    # The attempt chain the charter promises: every state this
                    # run passed through, in order, then its current state.
                    "state_history": [s.value for s in target.history],
                    "verdict": target.verdict,
                    "quorum_required": target.quorum_required,
                    "outcome": target.outcome,
                    "shadow_mode": target.shadow_mode,
                    "rollback_contract": target.rollback_contract,
                    "rollback_ref": target.rollback_ref,
                }
            )
            location = f" on {target.resource_id}" if target.resource_id else ""
            answer = (
                f"ActionRun {target.correlation_id!r} ({target.action_type}) is "
                f"{target.state.value}{location}."
            )
            return IntrospectionResult(answer=answer, facts=facts)
        if not runs:
            answer = (
                "No action runs dispatched yet; I am the sole executor and track "
                "each run's lifecycle."
            )
        else:
            answer = f"{len(active)} active run(s) of {len(runs)} tracked."
        return IntrospectionResult(answer=answer, facts=facts)


async def _default_executor(context: dict[str, Any]) -> bool:
    """Default executor for tests: always succeed. Fork overrides."""
    return True


__all__ = [
    "Thor",
    "ActionRun",
    "ActionRunState",
    "ActionExecutor",
    "ActionRunStore",
    "ExecutionAuditRecorder",
]


def _bounded_decision_case(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    required_strings = (
        "case_id",
        "correlation_id",
        "context_snapshot_id",
        "created_at",
        "selected_option_id",
    )
    if any(
        not isinstance(raw.get(field), str) or not str(raw[field]).strip()
        for field in required_strings
    ):
        return None
    required_arrays = (
        "protected_objective_ids",
        "active_constraint_ids",
        "no_action_effects",
        "options",
        "evidence_refs",
    )
    if any(not isinstance(raw.get(field), list) for field in required_arrays):
        return None
    if not raw["no_action_effects"] or not raw["options"] or not raw["evidence_refs"]:
        return None
    try:
        encoded = json.dumps(raw, allow_nan=False, ensure_ascii=True, sort_keys=True)
    except (TypeError, ValueError):
        return None
    if len(encoded) > 16_384:
        return None
    return dict(raw)


def _bounded_operational_context(raw: object) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        return None
    required_lists = {
        "service_ids",
        "workload_ids",
        "objective_ids",
        "constraint_ids",
        "stale_sources",
        "conflicts",
    }
    if (
        not isinstance(raw.get("snapshot_id"), str)
        or not str(raw["snapshot_id"]).strip()
        or not isinstance(raw.get("autonomy_ceiling"), str)
        or any(not isinstance(raw.get(field), list) for field in required_lists)
    ):
        return None
    try:
        encoded = json.dumps(raw, allow_nan=False, ensure_ascii=True, sort_keys=True)
    except (TypeError, ValueError):
        return None
    if len(encoded) > 16_384:
        return None
    return deepcopy(dict(raw))


def _resolved_autonomy_ceiling(verdict: Mapping[str, Any]) -> Autonomy:
    """Return the restrictive typed ceiling carried by one verdict."""

    values: list[Autonomy] = []
    raw = verdict.get("resolved_autonomy_ceiling")
    if raw is not None:
        if not isinstance(raw, str):
            return Autonomy.SHADOW_ONLY
        try:
            values.append(Autonomy(raw))
        except ValueError:
            return Autonomy.SHADOW_ONLY
    operational_context = verdict.get("operational_context")
    if operational_context is not None:
        if not isinstance(operational_context, Mapping):
            return Autonomy.SHADOW_ONLY
        context_ceiling = operational_context.get("autonomy_ceiling")
        if not isinstance(context_ceiling, str):
            return Autonomy.SHADOW_ONLY
        try:
            values.append(Autonomy(context_ceiling))
        except ValueError:
            return Autonomy.SHADOW_ONLY
    if not values:
        return Autonomy.SHADOW_ONLY
    rank = {
        Autonomy.SHADOW_ONLY: 0,
        Autonomy.ENFORCE_HIL: 1,
        Autonomy.ENFORCE_AUTO: 2,
    }
    return min(values, key=rank.__getitem__)


def _optional_bounded_text(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"durable ActionRun {field_name} MUST be bounded text")
    return value


def _optional_datetime(value: object, *, field_name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"durable ActionRun {field_name} MUST be text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"durable ActionRun {field_name} is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"durable ActionRun {field_name} MUST be timezone-aware")
    return parsed.astimezone(UTC)


def _bounded_workflow_action(raw: object) -> dict[str, str] | None:
    if not isinstance(raw, Mapping):
        return None
    required = {"process_id", "step_id", "proposal_ref"}
    if set(raw) != required:
        return None
    bounded = {key: str(raw[key]).strip() for key in required}
    if any(not item or len(item) > 512 for item in bounded.values()):
        return None
    return bounded


def _kinetic_proposal(raw: object) -> KineticActionProposal | None:
    if raw is None:
        return None
    try:
        return KineticActionProposal.model_validate(raw)
    except (TypeError, ValueError, ValidationError):
        return None


def _durable_kinetic_proposal(raw: object) -> dict[str, Any] | None:
    proposal = _kinetic_proposal(raw)
    if raw is not None and proposal is None:
        raise ValueError("durable ActionRun kinetic proposal is invalid")
    return proposal.model_dump(mode="json") if proposal is not None else None


def _require_bound_kinetic_proposal(run: ActionRun) -> None:
    """Reject rehydrated exact-argument evidence that belongs to another run.

    ``dispatch_verdict`` denies a verdict whose proposal is not bound to it.
    Rehydration reads the same untrusted durable boundary, so it MUST apply the
    same binding; otherwise a tampered row restores another correlation's exact
    arguments into an in-flight run and republishes them to the executor.
    """
    if run.kinetic_proposal is None:
        return
    proposal = _kinetic_proposal(run.kinetic_proposal)
    if proposal is None or not _kinetic_proposal_matches(
        proposal,
        correlation_id=run.correlation_id,
        action_type=run.action_type,
        resource_id=run.resource_id,
        params=run.params,
        decision_case=run.decision_case,
    ):
        raise ValueError("durable ActionRun kinetic proposal is not bound to its run")


def _kinetic_proposal_matches(
    proposal: KineticActionProposal,
    *,
    correlation_id: str,
    action_type: str,
    resource_id: object,
    params: Mapping[str, Any],
    decision_case: Mapping[str, Any] | None,
) -> bool:
    if (
        proposal.correlation_id != correlation_id
        or proposal.plan.action_type_ref.name != action_type
        or proposal.target_resource_ref != str(resource_id or "")
        or proposal.arguments() != dict(params)
        or decision_case is None
    ):
        return False
    operational_plan = decision_case.get("operational_plan")
    return bool(
        decision_case.get("correlation_id") == proposal.correlation_id
        and decision_case.get("process_id") == proposal.process_id
        and decision_case.get("selected_option_id") == proposal.selected_option_id
        and isinstance(operational_plan, Mapping)
        and operational_plan.get("complete") is True
        and operational_plan.get("plan_id") == proposal.operational_plan_id
    )


def _selected_action_matches(decision_case: Mapping[str, Any], action_type: str) -> bool:
    selected = decision_case.get("selected_option_id")
    options = decision_case.get("options")
    if not isinstance(selected, str) or not isinstance(options, list):
        return False
    return any(
        isinstance(option, Mapping)
        and option.get("option_id") == selected
        and option.get("action_type") == action_type
        and isinstance(option.get("effects"), list)
        and bool(option["effects"])
        for option in options
    )
