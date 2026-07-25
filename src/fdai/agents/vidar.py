"""Vidar - Recovery (Wave 3 behavior).

Vidar performs rollback per an ActionType's `rollback_contract` and
DR failover. Contract-specific rollback executors are injected by the
composition root; an unbound contract fails closed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruSet
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import IntrospectionResult, capability_facts
from fdai.agents._framework.pantheon import _VIDAR


@dataclass
class RollbackRecord:
    correlation_id: str
    action_type: str
    resource_id: str | None
    contract: str
    state: str  # succeeded | failed
    notes: str = ""
    rollback_ref: str | None = None


RollbackExecutor = Callable[[dict[str, Any]], Awaitable[str | None]]


class Vidar(Agent):
    """Wave-3 Vidar: rollback executor. Hard dependency for Thor."""

    #: Cap the in-process ledger so a long-running pantheon replica does
    #: not leak. The durable rollback trail is Saga's audit-chain; this
    #: list is only a shadow / observability convenience so callers can
    #: `snapshot()` recent rollback decisions in tests. FIFO eviction on
    #: overflow keeps the tail (most recent) while the durable chain
    #: retains full history.
    _MAX_RECORDS: int = 10_000

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        executors: Mapping[str, RollbackExecutor] | None = None,
    ) -> None:
        super().__init__(spec=_VIDAR)
        self.bus = bus
        self._executors = dict(executors or {})
        self.records: list[RollbackRecord] = []
        # Idempotency guard: at-least-once delivery means the same failed
        # ActionRun can arrive twice. Rolling a resource back twice is not a
        # no-op for a real rollback contract (double PITR restore, double
        # revert), so a correlation is rolled back at most once. Bounded so
        # the guard cannot leak on a long-lived recovery principal.
        self._rolled_back: BoundedLruSet[str] = BoundedLruSet(self._MAX_RECORDS)

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        # Vidar only reacts on failed ActionRuns.
        if topic != "object.action-run":
            return
        if payload.get("state") != "failed":
            return
        await self.rollback(payload)

    async def rollback(self, action_run: dict[str, Any]) -> RollbackRecord | None:
        correlation_id = str(action_run.get("correlation_id", ""))
        # Skip a duplicate rollback for a correlation already handled. An
        # empty correlation cannot be deduped, so it falls through (a rollback
        # is safer than silently skipping recovery).
        if correlation_id and correlation_id in self._rolled_back:
            return None
        contract = str(action_run.get("rollback_contract", "state_forward_only"))
        executor = self._executors.get(contract)
        state = "failed"
        notes = f"no rollback executor registered for contract {contract}"
        rollback_ref: str | None = None
        if not correlation_id:
            notes = "rollback refused because correlation_id is empty"
        elif executor is not None:
            try:
                rollback_ref = await executor(dict(action_run))
            except Exception as exc:  # noqa: BLE001 - provider boundary; fail closed
                notes = f"rollback executor raised {type(exc).__name__}"
            else:
                if rollback_ref:
                    state = "succeeded"
                    notes = "rollback executor completed"
                else:
                    notes = "rollback executor returned no receipt"
        rec = RollbackRecord(
            correlation_id=correlation_id,
            action_type=str(action_run.get("action_type", "")),
            resource_id=action_run.get("resource_id"),
            contract=contract,
            state=state,
            notes=notes,
            rollback_ref=rollback_ref,
        )
        if correlation_id:
            self._rolled_back.add(correlation_id)
        self.records.append(rec)
        # FIFO cap - drop the oldest 25% in one shot to amortise the cost.
        if len(self.records) > self._MAX_RECORDS:
            keep_from = len(self.records) - (self._MAX_RECORDS * 3 // 4)
            del self.records[:keep_from]
        if self.bus is not None:
            await self.bus.publish(
                "Vidar",
                "object.rollback",
                {
                    "producer_principal": "Vidar",
                    "correlation_id": rec.correlation_id,
                    "idempotency_key": (f"{rec.correlation_id}:rollback:{rec.state}"),
                    "action_type": rec.action_type,
                    "resource_id": rec.resource_id,
                    "contract": rec.contract,
                    "state": rec.state,
                    "rollback_ref": rec.rollback_ref,
                },
            )
        return rec

    # ---- conversational port -------------------------------------------

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        recs = self.records
        facts = {
            **capability_facts(self.spec),
            "rollbacks_recorded": len(recs),
        }
        if recs:
            last = recs[-1]
            facts.update(
                {
                    "last_correlation_id": last.correlation_id,
                    "last_action_type": last.action_type,
                    "last_state": last.state,
                    "last_contract": last.contract,
                }
            )
            answer = (
                f"{len(recs)} rollback(s) recorded; latest: {last.action_type} "
                f"-> {last.state} via {last.contract}."
            )
        else:
            answer = (
                "No rollbacks performed; I am the recovery principal (a hard "
                "dependency for any mutation)."
            )
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["Vidar", "RollbackExecutor", "RollbackRecord"]
