# mypy: disable-error-code="attr-defined,arg-type,no-any-return,misc"
"""DR contract and rollback rehearsal mixin for Vidar."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fdai.agents._framework import vidar_dr, vidar_rehearsal
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.agents._framework.vidar_rollback_records import (
    _DR_CONTRACT_DECISION_PREFIX,
    _REHEARSAL_STATE_PREFIX,
    _clock_now,
    _dr_contract_decision_key,
    _parse_rollback_timestamp,
)


class VidarDrRuntimeMixin:
    """Handle DR failover decisions and dry-run rehearsal receipts."""

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
                await self._persist_dr_contract_decision(identity, decision)
        await self._publish_typed_rollback_event(decision)
        self.record_behavior(f"dr_failover_contract:{decision['decision']}")

    async def _persist_dr_contract_decision(
        self, identity: str, decision: Mapping[str, Any]
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
                "recorded_at": _clock_now(self._clock).isoformat(),
            },
        )
        await self._state_store.delete_states_beyond(
            _DR_CONTRACT_DECISION_PREFIX,
            retain_newest=self._MAX_RECORDS,
        )

    async def _read_dr_contract_decision(self, identity: str) -> dict[str, object] | None:
        if self._state_store is None or not identity:
            return None
        stored = await self._state_store.read_state(_dr_contract_decision_key(identity))
        if not isinstance(stored, Mapping):
            return None
        decision = stored.get("decision")
        if not isinstance(decision, Mapping) or decision.get("decision") != "accepted":
            return None
        recovered = dict(decision)
        self._dr_contract_decisions.set(identity, recovered)
        return recovered

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
            receipt = await self._rehearse_contract(action_type, contract, now=now)
            self._rehearsal_receipts.set(action_type, receipt)
            self._last_rehearsal_by_action_type.set(action_type, now)
            await self._persist_rehearsal_receipt(receipt)
            await self._publish_typed_rollback_event(receipt)
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

    async def _persist_rehearsal_receipt(self, receipt: Mapping[str, Any]) -> None:
        if self._state_store is None:
            return
        await self._state_store.write_state(vidar_rehearsal.durable_key(receipt), dict(receipt))
        await self._state_store.delete_states_beyond(
            _REHEARSAL_STATE_PREFIX,
            retain_newest=self._MAX_RECORDS,
        )

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
            action_type = str(row.get("action_type") or "")
            contract = str(row.get("rollback_contract") or "")
            receipt_digest = str(row.get("receipt_digest") or "")
            if (
                not action_type
                or len(action_type) > 256
                or not contract
                or len(contract) > 128
                or action_type in seen
                or row.get("kind") != vidar_rehearsal.REHEARSAL_KIND
                or receipt_digest != vidar_rehearsal.digest(row)
            ):
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
