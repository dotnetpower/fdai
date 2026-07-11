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

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    capability_facts,
    mentioned,
)
from fdai.agents._framework.pantheon import _THOR


class ActionRunState(StrEnum):
    PROPOSED = "proposed"
    VERDICTED = "verdicted"
    HIL_PENDING = "hil_pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DENY_DROPPED = "deny_dropped"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


# Terminal states: an ActionRun in one of these is finished, so a durable
# store drops it (only in-flight runs are rehydrated on restart).
_TERMINAL_STATES: frozenset[ActionRunState] = frozenset(
    {
        ActionRunState.SUCCEEDED,
        ActionRunState.FAILED,
        ActionRunState.REJECTED,
        ActionRunState.DENY_DROPPED,
        ActionRunState.ROLLED_BACK,
    }
)


ActionExecutor = Callable[[dict[str, Any]], Awaitable[bool]]
"""Callable that mutates the target and returns True on success."""


@dataclass
class ActionRun:
    correlation_id: str
    action_type: str
    resource_id: str | None
    state: ActionRunState
    verdict: str  # auto | hil | deny
    shadow_mode: bool = False
    quorum_required: int = 1
    outcome: str | None = None
    initiator_principal: str | None = None
    rollback_ref: str | None = None
    history: list[ActionRunState] = field(default_factory=list)

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
            "shadow_mode": self.shadow_mode,
            "quorum_required": self.quorum_required,
            "outcome": self.outcome,
            "initiator_principal": self.initiator_principal,
            "rollback_ref": self.rollback_ref,
            "history": [s.value for s in self.history],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActionRun:
        run = cls(
            correlation_id=str(data["correlation_id"]),
            action_type=str(data["action_type"]),
            resource_id=data.get("resource_id"),
            state=ActionRunState(data["state"]),
            verdict=str(data["verdict"]),
            shadow_mode=bool(data.get("shadow_mode", False)),
            quorum_required=int(data.get("quorum_required", 1)),
            outcome=data.get("outcome"),
            initiator_principal=data.get("initiator_principal"),
            rollback_ref=data.get("rollback_ref"),
        )
        run.history = [ActionRunState(s) for s in data.get("history", [])]
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


class Thor(Agent):
    """Wave-3 Thor: dispatcher + per-resource mutex + lifecycle owner."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        executor: ActionExecutor | None = None,
        shadow_by_default: bool = False,
        saga_available: bool = True,
        vidar_available: bool = True,
        state_store: ActionRunStore | None = None,
    ) -> None:
        super().__init__(spec=_THOR)
        self.bus = bus
        self._executor = executor or _default_executor
        self._shadow_by_default = shadow_by_default
        self._saga_available = saga_available
        self._vidar_available = vidar_available
        self._state_store = state_store
        self.action_runs: dict[str, ActionRun] = {}
        self._resource_locks: set[str] = set()
        # Cap the in-memory run map so a long-running dispatcher cannot leak
        # one entry per correlation id forever. Only TERMINAL runs are
        # evicted (oldest first) once over the cap; active runs are always
        # retained (they back the per-resource mutex and approval lookup).
        self._max_retained_runs = 10_000

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    def set_state_store(self, store: ActionRunStore) -> None:
        """Attach a durable ActionRun store (composition-root seam)."""
        self._state_store = store

    async def rehydrate(self) -> int:
        """Reload in-flight ActionRuns from the durable store on startup.

        Restores the per-resource locks so a restart cannot start a second
        run on a resource that already had one in flight. Returns the
        number of runs restored. No-op without a store.
        """
        if self._state_store is None:
            return 0
        active = await self._state_store.load_active()
        for run in active:
            self.action_runs[run.correlation_id] = run
            if run.resource_id:
                self._resource_locks.add(str(run.resource_id))
        return len(active)

    def set_shadow(self, enabled: bool) -> None:
        """Force shadow mode on / off for every future dispatch.

        The composition root (:class:`~fdai.agents.runtime.PantheonRuntime`)
        calls this to keep the pantheon Thor judge-and-log only, so it
        never double-executes alongside the P1 control loop. Enforce is an
        explicit, separately reviewed promotion - never the default.
        """
        self._shadow_by_default = enabled

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
            await self.dispatch_verdict(payload)
        elif topic == "object.approval":
            await self._handle_approval(payload)

    # ---- lifecycle -----------------------------------------------------

    async def dispatch_verdict(self, verdict: dict[str, Any]) -> ActionRun:
        correlation = str(verdict.get("correlation_id", ""))
        action_type = str(verdict.get("action_type", ""))
        risk_verdict = str(verdict.get("risk_verdict", "hil"))
        resource_id = verdict.get("resource_id")

        # Idempotency: at-least-once delivery means the same verdict can arrive
        # twice. Keying the run by correlation is not enough - a re-delivery
        # after the first run terminated (lock released) would start a SECOND
        # run and re-execute. Return the existing run for a correlation we have
        # already dispatched, so a duplicate verdict is a no-op (defense in
        # depth with the event idempotency_key dedup at ingress).
        existing_by_corr = self.action_runs.get(correlation)
        if existing_by_corr is not None:
            self.record_behavior("dispatch:duplicate")
            return existing_by_corr

        # Per-resource mutex: refuse to start a new run while another is
        # active on the same resource. Second dispatcher waits for the
        # first to terminate before starting.
        if resource_id and resource_id in self._resource_locks:
            existing = self._find_active_run(str(resource_id))
            if existing is not None:
                self.record_behavior("dispatch:lock_contention")
                return existing

        # Degrade to shadow when hard dependencies are missing.
        shadow_mode = self._shadow_by_default or not (
            self._saga_available and self._vidar_available
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
            shadow_mode=shadow_mode,
            quorum_required=quorum_required,
            initiator_principal=verdict.get("initiator_principal"),
        )
        self.action_runs[correlation] = run
        if resource_id:
            self._resource_locks.add(str(resource_id))
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

        if risk_verdict == "deny":
            run.transition(ActionRunState.DENY_DROPPED)
            await self._emit_action_run(run)
            self._release_lock(resource_id)
            return run

        if risk_verdict == "hil":
            run.transition(ActionRunState.HIL_PENDING)
            await self._emit_action_run(run)
            return run

        # auto path
        await self._execute(run)
        return run

    async def _execute(self, run: ActionRun) -> None:
        run.transition(ActionRunState.EXECUTING)
        await self._emit_action_run(run)
        if run.shadow_mode:
            # Shadow-mode: judge and log without mutating.
            run.transition(ActionRunState.SUCCEEDED)
            run.outcome = "shadow_success"
            await self._emit_action_run(run)
            self.record_behavior("executed:shadow")
            self._release_lock(run.resource_id)
            return
        try:
            success = await self._executor({"run": run})
        except Exception as exc:  # noqa: BLE001 (surface adapter errors)
            success = False
            run.outcome = f"executor error: {exc}"
        run.transition(ActionRunState.SUCCEEDED if success else ActionRunState.FAILED)
        if not success and run.outcome is None:
            run.outcome = "executor returned false"
        await self._emit_action_run(run)
        self.record_behavior("executed:success" if success else "executed:failed")
        if not success:
            run.rollback_ref = f"rollback:{run.correlation_id}"
            run.transition(ActionRunState.ROLLED_BACK)
            await self._emit_action_run(run)
            self.record_behavior("rolled_back")
        self._release_lock(run.resource_id)

    async def _handle_approval(self, approval: dict[str, Any]) -> None:
        correlation = str(approval.get("correlation_id", ""))
        run = self.action_runs.get(correlation)
        if run is None:
            return
        if approval.get("state") == "approved":
            run.transition(ActionRunState.APPROVED)
            await self._execute(run)
        else:
            run.transition(ActionRunState.REJECTED)
            await self._emit_action_run(run)
            self._release_lock(run.resource_id)

    # ---- helpers -------------------------------------------------------

    def _release_lock(self, resource_id: Any) -> None:
        if resource_id:
            self._resource_locks.discard(str(resource_id))

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
            if run.state in _TERMINAL_STATES:
                del self.action_runs[cid]
                overflow -= 1

    def _find_active_run(self, resource_id: str) -> ActionRun | None:
        for run in self.action_runs.values():
            if run.resource_id == resource_id and run.state not in {
                ActionRunState.SUCCEEDED,
                ActionRunState.FAILED,
                ActionRunState.REJECTED,
                ActionRunState.DENY_DROPPED,
                ActionRunState.ROLLED_BACK,
            }:
                return run
        return None

    async def _emit_action_run(self, run: ActionRun) -> None:
        # Durable write-through: persist in-flight runs, drop terminal ones
        # so load_active() only ever returns work still in progress. Done
        # before the publish so a crash between persist and publish still
        # leaves the run recoverable.
        if self._state_store is not None:
            if run.state in _TERMINAL_STATES:
                await self._state_store.delete(run.correlation_id)
            else:
                await self._state_store.save(run)
        self._evict_terminal_overflow()
        if self.bus is None:
            return
        payload = {
            "producer_principal": "Thor",
            "correlation_id": run.correlation_id,
            "action_type": run.action_type,
            "resource_id": run.resource_id,
            "state": run.state.value,
            "shadow_mode": run.shadow_mode,
            "outcome": run.outcome,
            "verdict": run.verdict,
            "quorum_required": run.quorum_required,
            "initiator_principal": run.initiator_principal,
        }
        await self.bus.publish("Thor", "object.action-run", payload)

    # ---- conversational port -------------------------------------------

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
                    "verdict": target.verdict,
                    "shadow_mode": target.shadow_mode,
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


__all__ = ["Thor", "ActionRun", "ActionRunState", "ActionExecutor", "ActionRunStore"]
