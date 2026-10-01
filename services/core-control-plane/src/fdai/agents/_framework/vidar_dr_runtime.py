"""DR contract and rollback rehearsal mixin for Vidar."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from fdai.agents._framework import vidar_dr, vidar_rehearsal
from fdai.agents._framework.bounded import BoundedLruDict
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.agents._framework.vidar_rollback_records import (
    _DR_CONTRACT_DECISION_PREFIX,
    _REHEARSAL_STATE_PREFIX,
    RollbackExecutor,
    RollbackRecord,
    RollbackRehearsalPort,
    _clock_now,
    _dr_contract_decision_key,
    _parse_rollback_timestamp,
)
from fdai.shared.providers.state_store import StateStore

if TYPE_CHECKING:
    from fdai.agents._framework.bus import PantheonBus


class VidarDrRuntimeMixin:
    """Handle DR failover decisions and dry-run rehearsal receipts."""

    _clock: Callable[[], datetime]
    _dr_contract_decisions: BoundedLruDict[str, dict[str, object]]
    _rollback_path_validations: BoundedLruDict[str, dict[str, object]]
    _state_store: StateStore | None
    _MAX_RECORDS: int
    _dr_outcomes: BoundedLruDict[str, dict[str, object]]
    bus: PantheonBus | None
    _rollback_contracts_by_action_type: dict[str, str]
    _max_rehearsals_per_tick: int
    _last_rehearsal_by_action_type: BoundedLruDict[str, datetime]
    _rollback_rehearsal_cadence: timedelta
    _rollback_rehearsal_port: RollbackRehearsalPort | None
    _rollback_rehearsal_timeout_seconds: float
    _rehearsal_receipts: BoundedLruDict[str, dict[str, object]]
    _last_dr_readiness: dict[str, object]

    if TYPE_CHECKING:

        def record_behavior(self, name: str, amount: int = 1) -> None: ...

        async def rollback(self, action_run: dict[str, Any]) -> RollbackRecord | None: ...

        def _validate_rollback_paths(self) -> None: ...

        def _rollback_executor(
            self,
            action_type: str,
            contract: str,
        ) -> RollbackExecutor | None: ...

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        # Vidar reacts on failed and ambiguous ActionRuns.
        if topic != "object.action-run":
            self.record_behavior("typed_message:ignored")
            return
        if require_topic_owner(
            self,
            topic,
            payload,
            behavior="rollback:rejected_owner",
        ):
            return
        if vidar_dr.is_failover_action_type(payload.get("action_type")):
            await self._handle_dr_failover_action_run(payload)
        if payload.get("state") not in {"failed", "execution_unknown"}:
            self.record_behavior("action_run:ignored")
            return
        try:
            await self.rollback(payload)
        except ValueError:
            self.record_behavior("rollback:action_identity_mismatch")

    async def _handle_dr_failover_action_run(self, payload: dict[str, Any]) -> None:
        state = str(payload.get("state") or "")
        if state in {"verdicted", "hil_pending", "approved"}:
            decision = vidar_dr.build_contract_decision(
                payload,
                contract_ready=self._dr_contract_ready(payload),
                failback_executor_bound=self._dr_failback_executor_bound(payload),
                now=_clock_now(self._clock),
            )
            if decision is None:
                self.record_behavior("dr_failover_contract:invalid")
                return
            await self._publish_dr_contract_decision(decision)
            return
        if state == "succeeded" and payload.get("effect_verification_ref") is not None:
            identity = str(payload.get("action_run_identity") or "")
            accepted = self._dr_contract_decisions.get(identity)
            if accepted is None:
                accepted = await self._read_dr_contract_decision(identity)
            outcome = vidar_dr.build_outcome(
                payload,
                accepted_decision=accepted or {},
                now=_clock_now(self._clock),
            )
            if outcome is None:
                self.record_behavior("dr_failover_outcome:unbound")
                return
            await self._publish_dr_outcome(outcome)

    def _dr_contract_ready(self, payload: Mapping[str, Any]) -> bool:
        action_type = str(payload.get("action_type") or "")
        validation = self._rollback_path_validations.get(action_type)
        if validation is None:
            self._validate_rollback_paths()
            validation = self._rollback_path_validations.get(action_type)
        return bool(validation and validation.get("ready"))

    def _dr_failback_executor_bound(self, payload: Mapping[str, Any]) -> bool:
        contract = str(payload.get("rollback_contract") or "scripted")
        action_type = str(payload.get("action_type") or "")
        return self._rollback_executor(action_type, contract) is not None

    async def _publish_dr_contract_decision(self, decision: dict[str, Any]) -> None:
        if decision.get("decision") == "accepted":
            identity = str(decision.get("action_run_identity") or "")
            if identity:
                self._dr_contract_decisions.set(identity, dict(decision))
                stored = await self._read_dr_contract_decision_record(identity)
                if stored is not None and stored.get("published") is True:
                    self.record_behavior("dr_failover_contract:duplicate")
                    return
                await self._persist_dr_contract_decision(identity, decision, published=False)
        published = await self._publish_typed_rollback_event(decision)
        if not published:
            self.record_behavior(
                f"dr_failover_contract_publication_unavailable:{decision['decision']}"
            )
            return
        if decision.get("decision") == "accepted":
            identity = str(decision.get("action_run_identity") or "")
            if identity:
                await self._persist_dr_contract_decision(identity, decision, published=True)
        self.record_behavior(f"dr_failover_contract:{decision['decision']}")

    async def _persist_dr_contract_decision(
        self, identity: str, decision: Mapping[str, Any], *, published: bool
    ) -> None:
        if self._state_store is None:
            return
        await self._state_store.write_state(
            _dr_contract_decision_key(identity),
            {
                "schema_version": "1.0.0",
                "revision": 1,
                "action_run_identity": identity,
                "decision": dict(decision),
                "published": published,
                "recorded_at": _clock_now(self._clock).isoformat(),
            },
        )
        await self._state_store.delete_states_beyond(
            _DR_CONTRACT_DECISION_PREFIX,
            retain_newest=self._MAX_RECORDS,
        )

    async def _read_dr_contract_decision(self, identity: str) -> dict[str, object] | None:
        stored = await self._read_dr_contract_decision_record(identity)
        if stored is None:
            return None
        decision = stored.get("decision")
        if not isinstance(decision, Mapping) or decision.get("decision") != "accepted":
            return None
        recovered = dict(decision)
        self._dr_contract_decisions.set(identity, recovered)
        return recovered

    async def _read_dr_contract_decision_record(self, identity: str) -> dict[str, object] | None:
        if self._state_store is None or not identity:
            return None
        stored = await self._state_store.read_state(_dr_contract_decision_key(identity))
        if not isinstance(stored, Mapping):
            return None
        return dict(stored)

    async def _publish_dr_outcome(self, outcome: dict[str, Any]) -> None:
        identity = str(outcome.get("action_run_identity") or "")
        if identity and self._dr_outcomes.get(identity) == outcome:
            self.record_behavior("dr_failover_outcome:duplicate")
            return
        published = await self._publish_typed_rollback_event(outcome)
        if not published:
            self.record_behavior("dr_failover_outcome:publication_unavailable")
            return
        if identity:
            self._dr_outcomes.set(identity, dict(outcome))
        self.record_behavior("dr_failover_outcome:published")

    async def _publish_typed_rollback_event(self, payload: dict[str, Any]) -> bool:
        if self.bus is None:
            self.record_behavior("publication:unavailable")
            return False
        await self.bus.publish("Vidar", "object.rollback", payload)
        return True

    async def _run_rollback_rehearsals(self) -> None:
        now = _clock_now(self._clock)
        ran = 0
        for action_type, contract in sorted(self._rollback_contracts_by_action_type.items()):
            if ran >= self._max_rehearsals_per_tick:
                break
            last = self._last_rehearsal_by_action_type.get(action_type)
            if last is not None and now - last < self._rollback_rehearsal_cadence:
                continue
            receipt = await self._unpublished_rehearsal_receipt(action_type)
            if receipt is None:
                receipt = await self._rehearse_contract(action_type, contract, now=now)
                await self._persist_rehearsal_receipt(receipt, published=False)
            if await self._publish_rehearsal_receipt(receipt):
                ran += 1
        if ran:
            self._apply_rehearsal_readiness()

    async def _rehearse_contract(
        self,
        action_type: str,
        contract: str,
        *,
        now: datetime,
    ) -> dict[str, Any]:
        if self._rollback_rehearsal_port is None:
            self.record_behavior("rollback_rehearsal:unbound")
            return vidar_rehearsal.unbound_receipt(
                action_type=action_type,
                contract=contract,
                recorded_at=now,
            )
        try:
            async with asyncio.timeout(self._rollback_rehearsal_timeout_seconds):
                result = await self._rollback_rehearsal_port.rehearse(
                    vidar_rehearsal.command(action_type=action_type, contract=contract)
                )
        except TimeoutError:
            self.record_behavior("rollback_rehearsal:timeout")
            return vidar_rehearsal.build_receipt(
                action_type=action_type,
                contract=contract,
                outcome="held",
                reason="rehearsal_port_timeout",
                recorded_at=now,
                rehearsal_version="1.0.0",
            )
        except Exception as exc:  # noqa: BLE001 - provider boundary; rehearsal lowers readiness
            self.record_behavior("rollback_rehearsal:failed")
            return vidar_rehearsal.build_receipt(
                action_type=action_type,
                contract=contract,
                outcome="failed",
                reason=f"rehearsal_port_raised_{type(exc).__name__}",
                recorded_at=now,
                rehearsal_version="1.0.0",
            )
        outcome: vidar_rehearsal.RehearsalOutcome = (
            "passed" if result.get("outcome") == "passed" else "failed"
        )
        self.record_behavior(f"rollback_rehearsal:{outcome}")
        return vidar_rehearsal.build_receipt(
            action_type=action_type,
            contract=contract,
            outcome=outcome,
            reason=str(result.get("reason") or outcome),
            recorded_at=now,
            rehearsal_version=str(result.get("rehearsal_version") or "1.0.0"),
        )

    async def _publish_rehearsal_receipt(self, receipt: Mapping[str, Any]) -> bool:
        published = await self._publish_typed_rollback_event(dict(receipt))
        if not published:
            self.record_behavior("rollback_rehearsal:publication_unavailable")
            return False
        await self._persist_rehearsal_receipt(receipt, published=True)
        action_type = str(receipt.get("action_type") or "")
        recorded_at = _parse_rollback_timestamp(receipt.get("recorded_at"))
        if action_type:
            self._rehearsal_receipts.set(action_type, dict(receipt))
            if recorded_at is not None:
                self._last_rehearsal_by_action_type.set(action_type, recorded_at)
        return True

    async def _persist_rehearsal_receipt(
        self,
        receipt: Mapping[str, Any],
        *,
        published: bool,
    ) -> None:
        if self._state_store is None:
            return
        stored = await self._state_store.read_state(vidar_rehearsal.durable_key(receipt))
        revision = int(stored.get("revision", 0)) + 1 if isinstance(stored, Mapping) else 1
        await self._state_store.write_state(
            vidar_rehearsal.durable_key(receipt),
            {
                **dict(receipt),
                "revision": revision,
                "published": published,
            },
        )
        await self._state_store.delete_states_beyond(
            _REHEARSAL_STATE_PREFIX,
            retain_newest=self._MAX_RECORDS,
        )

    async def _unpublished_rehearsal_receipt(self, action_type: str) -> dict[str, Any] | None:
        if self._state_store is None:
            return None
        rows, _total = await self._state_store.read_state_page(
            _REHEARSAL_STATE_PREFIX,
            limit=self._MAX_RECORDS,
            field="published",
            value="false",
        )
        for row in rows:
            if row.get("action_type") == action_type and self._rehearsal_row_valid(row):
                return dict(row)
        return None

    async def _rehydrate_rehearsal_receipts(self) -> int:
        if self._state_store is None:
            return 0
        rows, total = await self._state_store.read_state_page(
            _REHEARSAL_STATE_PREFIX,
            limit=self._MAX_RECORDS,
        )
        if total > self._MAX_RECORDS:
            self.record_behavior("rollback_rehearsal:rehydrate_overflow")
        seen: set[str] = set()
        restored = 0
        for row in rows:
            if not self._rehearsal_row_valid(row):
                continue
            action_type = str(row.get("action_type") or "")
            if action_type in seen:
                continue
            if row.get("published") is not True:
                if await self._publish_rehearsal_receipt(row):
                    restored += 1
                seen.add(action_type)
                continue
            recorded_at = _parse_rollback_timestamp(row.get("recorded_at"))
            self._rehearsal_receipts.set(action_type, dict(row))
            if recorded_at is not None:
                self._last_rehearsal_by_action_type.set(action_type, recorded_at)
            seen.add(action_type)
            restored += 1
        if restored:
            self._apply_rehearsal_readiness()
            self.record_behavior("rollback_rehearsal:rehydrated", restored)
        return restored

    def _rehearsal_row_valid(self, row: Mapping[str, Any]) -> bool:
        action_type = str(row.get("action_type") or "")
        contract = str(row.get("rollback_contract") or "")
        receipt_digest = str(row.get("receipt_digest") or "")
        return (
            bool(action_type)
            and len(action_type) <= 256
            and bool(contract)
            and len(contract) <= 128
            and row.get("kind") == vidar_rehearsal.REHEARSAL_KIND
            and receipt_digest == vidar_rehearsal.digest(row)
        )

    def _apply_rehearsal_readiness(self) -> None:
        receipts = [receipt for _, receipt in self._rehearsal_receipts.items()]
        failures = sum(1 for receipt in receipts if receipt.get("outcome") == "failed")
        held = sum(1 for receipt in receipts if receipt.get("outcome") == "held")
        if failures:
            self._last_dr_readiness["evidence_state"] = "measured_with_rehearsal_failures"
            self._last_dr_readiness["coverage_ratio"] = 0.0
            self._last_dr_readiness["rehearsal_failures"] = failures
        elif held:
            self._last_dr_readiness["rehearsal_evidence_state"] = "unbound"
        else:
            self._last_dr_readiness["rehearsal_evidence_state"] = "measured"


__all__ = ["VidarDrRuntimeMixin"]
