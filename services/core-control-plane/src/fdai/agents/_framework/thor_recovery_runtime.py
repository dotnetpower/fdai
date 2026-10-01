# mypy: disable-error-code="attr-defined,arg-type,no-any-return,misc,has-type"
"""Approval, rollback, and DR failover mixin for Thor."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.agents._framework import vidar_dr
from fdai.agents._framework.action_run_identity import (
    approval_matches_action_run,
    bounded_rollback_ref,
    rollback_matches_action_run,
)
from fdai.agents._framework.action_run_state import (
    TERMINAL_ACTION_RUN_STATES as _TERMINAL_STATES,
)
from fdai.agents._framework.action_run_state import ActionRunState
from fdai.agents._framework.approval_readback import read_current_action_approval
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.agents._framework.thor_action_run import ActionRun
from fdai.agents._framework.thor_locks import _ReentrantAsyncLock


class ThorRecoveryMixin:
    """Handle Var approvals, Vidar rollbacks, and DR contract decisions."""

    async def _handle_approval(self, approval: dict[str, Any]) -> None:
        correlation = str(approval.get("correlation_id", ""))
        lock = self._correlation_locks.setdefault(correlation, _ReentrantAsyncLock())
        async with lock:
            run_to_execute = await self._handle_approval_locked(approval, correlation=correlation)
        if run_to_execute is not None:
            if run_to_execute.batch_role == "rollup":
                if self._batch_has_attempts(run_to_execute.correlation_id):
                    self.record_behavior("approval:batch_duplicate")
                    return
                await self._execute_batch_rollup(run_to_execute)
                return
            await self._execute(run_to_execute)

    async def _handle_approval_locked(
        self,
        approval: dict[str, Any],
        *,
        correlation: str,
    ) -> ActionRun | None:
        run = self.action_runs.get(correlation)
        if run is None:
            self.record_behavior("approval:unknown_run")
            return None
        if require_topic_owner(
            self,
            "object.approval",
            approval,
            behavior="approval:rejected_owner",
        ):
            return None
        run_identity = run.to_dict()
        run_identity["action_run_identity"] = run.action_run_identity()
        run_identity["_action_run_identity_verified"] = True
        if not approval_matches_action_run(approval, run_identity):
            self.record_behavior("approval:identity_mismatch")
            raise ValueError("approval identity does not match the current ActionRun")
        self._validate_development_approval(run, approval)
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
                return run
            if run.state in _TERMINAL_STATES and not run.terminal_published:
                await self._emit_action_run(run)
                await self._finalize_terminal_replay(run)
            elif run.state in _TERMINAL_STATES:
                await self._finalize_terminal_replay(run)
            return None
        if run.approval_expires_at is None or self._now() >= run.approval_expires_at:
            await self._expire_approval(run)
            return None
        if approval.get("state") == "approved":
            if not run.shadow_mode and self._approval_state_store is not None:
                if self._approver_authorizer is None:
                    run.transition(ActionRunState.REJECTED)
                    run.outcome = "approval_readback_unavailable"
                    await self._emit_action_run(run)
                    self.record_behavior("approval:readback_unavailable")
                    self._release_lock(run.resource_id)
                    return None
                try:
                    await read_current_action_approval(
                        store=self._approval_state_store,
                        action_run=run.to_dict(),
                        can_approve=self._approver_authorizer,
                        clock=self._now,
                        development_profile=self._development_profile,
                        development_executor_principal=self._development_executor_principal,
                        development_binding_source=self._development_binding_source,
                        can_own=self._owner_authorizer,
                    )
                except (PermissionError, ValueError):
                    run.transition(ActionRunState.REJECTED)
                    run.outcome = "approval_readback_rejected"
                    await self._emit_action_run(run)
                    self.record_behavior("approval:readback_rejected")
                    self._release_lock(run.resource_id)
                    return None
            run.transition(ActionRunState.APPROVED)
            if vidar_dr.is_failover_action_type(run.action_type):
                await self._emit_action_run(run)
            return run
        else:
            if not run.resource_claimed and not await self._claim_execution_resource(run):
                run.transition(ActionRunState.DENY_DROPPED)
                run.outcome = "duplicate_execution_already_completed"
                await self._emit_action_run(run)
                self._release_lock(run.resource_id)
                return None
            try:
                run.transition(ActionRunState.REJECTED)
                await self._emit_action_run(run)
                await self._release_resource_claim(run)
            finally:
                self._release_lock(run.resource_id)
        return None

    async def expire_pending_approvals(self) -> int:
        """Expire bounded HIL and effect-verification waits."""

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
        expired_effects = [
            run
            for run in self.action_runs.values()
            if run.state is ActionRunState.EFFECT_PENDING
            and (
                run.effect_verification_expires_at is None
                or self._now() >= run.effect_verification_expires_at
            )
        ]
        for run in expired_effects:
            lock = self._correlation_locks.setdefault(
                run.correlation_id,
                _ReentrantAsyncLock(),
            )
            async with lock:
                if run.state is ActionRunState.EFFECT_PENDING and (
                    run.effect_verification_expires_at is None
                    or self._now() >= run.effect_verification_expires_at
                ):
                    run.transition(ActionRunState.FAILED)
                    run.outcome = "effect_verification_expired"
                    await self._emit_action_run(run)
                    self.record_behavior("effect_verification:expired")
        expired_dr_contracts = [
            run
            for run in self.action_runs.values()
            if run.state is ActionRunState.APPROVED
            and vidar_dr.is_failover_action_type(run.action_type)
            and run.outcome == "dr_failover_contract_pending"
            and (run.approval_expires_at is None or self._now() >= run.approval_expires_at)
        ]
        for run in expired_dr_contracts:
            lock = self._correlation_locks.setdefault(
                run.correlation_id,
                _ReentrantAsyncLock(),
            )
            async with lock:
                if (
                    run.state is ActionRunState.APPROVED
                    and run.outcome == "dr_failover_contract_pending"
                    and (run.approval_expires_at is None or self._now() >= run.approval_expires_at)
                ):
                    await self._deny_dr_failover_contract(run, "dr_failover_contract_timeout")
                    self.record_behavior("dr_failover_contract:timeout")
        return len(expired) + len(expired_effects) + len(expired_dr_contracts)

    async def _expire_approval(self, run: ActionRun) -> None:
        await asyncio.shield(self._expire_approval_critical(run))

    async def _expire_approval_critical(self, run: ActionRun) -> None:
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
        if require_topic_owner(
            self,
            "object.rollback",
            rollback,
            behavior="rollback:rejected_owner",
        ):
            return
        if rollback.get("kind") == vidar_dr.DR_CONTRACT_KIND:
            await self._handle_dr_failover_contract_decision(rollback)
            return
        if rollback.get("kind") == vidar_dr.DR_OUTCOME_KIND:
            self.record_behavior("dr_failover_outcome:observed")
            return
        if rollback.get("kind") == "rollback_rehearsal_receipt":
            self.record_behavior("rollback_rehearsal:observed")
            return
        run = self.action_runs.get(correlation)
        if run is not None:
            run_identity = run.to_dict()
            run_identity["action_run_identity"] = run.action_run_identity()
            run_identity["_action_run_identity_verified"] = True
        if run is not None and not rollback_matches_action_run(rollback, run_identity):
            self.record_behavior("rollback:identity_mismatch")
            return
        rollback_ref = bounded_rollback_ref(rollback.get("rollback_ref"))
        rollback_state = str(rollback.get("state") or "")
        succeeded = rollback_state == "succeeded" and rollback_ref is not None
        if run is not None and run.state is ActionRunState.ROLLBACK_FAILED and succeeded:
            run.rollback_ref = rollback_ref
            run.outcome = "rollback_succeeded"
            run.transition(ActionRunState.ROLLED_BACK)
            await self._emit_action_run(run)
            await self._release_resource_claim(run)
            self._release_lock(run.resource_id)
            if run.rollup_correlation_id is not None:
                await self._refresh_batch_rollup(run.rollup_correlation_id)
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
        run.rollback_ref = rollback_ref if succeeded else None
        if succeeded:
            run.outcome = "rollback_succeeded"
            next_state = ActionRunState.ROLLED_BACK
        elif rollback_state == "refused":
            run.outcome = "rollback_refused"
            next_state = ActionRunState.ROLLBACK_REFUSED
        else:
            run.outcome = "rollback_failed"
            next_state = ActionRunState.ROLLBACK_FAILED
        run.transition(next_state)
        await self._emit_action_run(run)
        self.record_behavior(run.outcome)
        await self._release_resource_claim(run)
        self._release_lock(run.resource_id)
        if run.rollup_correlation_id is not None:
            await self._refresh_batch_rollup(run.rollup_correlation_id)

    async def _handle_effect_observation(self, observation: dict[str, Any]) -> None:
        correlation = str(observation.get("correlation_id") or "")
        await super()._handle_effect_observation(observation)
        run = self.action_runs.get(correlation)
        if run is not None and run.rollup_correlation_id is not None:
            await self._refresh_batch_rollup(run.rollup_correlation_id)

    async def _handle_dr_failover_contract_decision(self, decision: Mapping[str, Any]) -> None:
        identity = decision.get("action_run_identity")
        if not isinstance(identity, str):
            self.record_behavior("dr_failover_contract:invalid")
            return
        run = self._find_run_by_identity(identity)
        if run is None:
            self._dr_failover_contract_decisions.set(identity, dict(decision))
            self.record_behavior("dr_failover_contract:unknown_run")
            return
        if run.state in _TERMINAL_STATES or run.state in {
            ActionRunState.EXECUTING,
            ActionRunState.EFFECT_PENDING,
        }:
            self.record_behavior("dr_failover_contract:late_ignored")
            return
        if decision.get("decision") == "held" and decision.get("reason") == "approval_required":
            self.record_behavior("dr_failover_contract:awaiting_approval")
            return
        if run.state in {ActionRunState.VERDICTED, ActionRunState.HIL_PENDING}:
            self.record_behavior("dr_failover_contract:awaiting_approval")
            return
        self._dr_failover_contract_decisions.set(identity, dict(decision))
        self.record_behavior(f"dr_failover_contract:{decision.get('decision') or 'unknown'}")
        run.dr_failover_contract_decision = dict(decision)
        if self._state_store is not None:
            await self._state_store.save(run)
        if decision.get("decision") == "held":
            await self._deny_dr_failover_contract(
                run,
                f"dr_failover_contract_held:{vidar_dr.decision_hold_reason(decision)}",
            )
            return
        if (
            run.state is ActionRunState.APPROVED
            and run.outcome == "dr_failover_contract_pending"
            and vidar_dr.decision_allows_executor_io(decision)
        ):
            run.outcome = None
            await self._execute(run)

    async def _wait_for_dr_failover_contract(self, run: ActionRun) -> bool:
        if not vidar_dr.is_failover_action_type(run.action_type) or run.shadow_mode:
            return False
        decision = run.dr_failover_contract_decision or self._dr_failover_contract_decisions.get(
            run.action_run_identity()
        )
        if vidar_dr.decision_allows_executor_io(decision):
            run.dr_failover_contract_decision = dict(decision or {})
            return False
        if (
            decision is not None
            and decision.get("decision") == "held"
            and decision.get("reason") != "approval_required"
        ):
            await self._deny_dr_failover_contract(
                run,
                f"dr_failover_contract_held:{vidar_dr.decision_hold_reason(decision)}",
            )
            return True
        if run.approval_expires_at is not None and self._now() >= run.approval_expires_at:
            await self._deny_dr_failover_contract(run, "dr_failover_contract_timeout")
            self.record_behavior("dr_failover_contract:timeout")
            return True
        if run.state is not ActionRunState.APPROVED:
            run.transition(ActionRunState.APPROVED)
        run.outcome = "dr_failover_contract_pending"
        await self._emit_action_run(run)
        self.record_behavior("dr_failover_contract:waiting")
        return True

    async def _deny_dr_failover_contract(self, run: ActionRun, outcome: str) -> None:
        if run.state in _TERMINAL_STATES:
            return
        run.transition(ActionRunState.DENY_DROPPED)
        run.outcome = outcome
        await self._emit_action_run(run)
        await self._release_resource_claim(run)
        self._release_lock(run.resource_id)

    def _find_run_by_identity(self, identity: str) -> ActionRun | None:
        for run in self.action_runs.values():
            if run.action_run_identity() == identity:
                return run
        return None


__all__ = ["ThorRecoveryMixin"]
