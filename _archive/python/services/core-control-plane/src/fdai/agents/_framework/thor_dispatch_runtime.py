"""Dispatch and batch lifecycle mixin for Thor."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from weakref import WeakValueDictionary

from fdai.agents._framework import (
    action_run_lineage,
    action_semantics,
    thor_batch,
    thor_dispatch_validation,
    thor_execution,
    thor_preflight,
)
from fdai.agents._framework.action_run_lineage import (
    bounded_operational_context as _bounded_operational_context,
)
from fdai.agents._framework.action_run_state import (
    TERMINAL_ACTION_RUN_STATES as _TERMINAL_STATES,
)
from fdai.agents._framework.action_run_state import ActionRunState
from fdai.agents._framework.thor_action_run import (
    ActionRun,
    ActionRunStore,
)
from fdai.agents._framework.thor_action_run import (
    kinetic_proposal as _kinetic_proposal,
)
from fdai.agents._framework.thor_action_run import (
    kinetic_proposal_matches as _kinetic_proposal_matches,
)
from fdai.agents._framework.thor_action_run import (
    prospective_lineage as _prospective_lineage,
)
from fdai.agents._framework.thor_correlation import resolve_correlation_claim
from fdai.agents._framework.thor_execution import (
    ExecutionResourceUnavailableError as _ExecutionResourceUnavailableError,
)
from fdai.agents._framework.thor_locks import _ReentrantAsyncLock
from fdai.core.operational_context.test_context_dispatch import (
    TestContextDispatchBinding,
    TestContextDispatchGuard,
)
from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.resource_lock import ResourceLock

_resolved_autonomy_ceiling = thor_dispatch_validation.resolved_autonomy_ceiling
_selected_action_matches = thor_dispatch_validation.selected_action_matches
_bounded_params = thor_dispatch_validation.bounded_params
_missing_wire_safeguards = thor_dispatch_validation.missing_wire_safeguards
_dry_run_obligation_only = thor_dispatch_validation.dry_run_obligation_only
_ACCEPTED_RISK_VERDICTS = frozenset({"auto", "hil", "deny", "shadow"})

if TYPE_CHECKING:
    from fdai.agents._framework.thor_development_authority import DevelopmentVerdictAuthority
    from fdai.agents.thor import ActionExecutor, ExecutionAuditRecorder


def _positive_quorum(value: object) -> int:
    if isinstance(value, bool):
        raise TypeError("quorum MUST be an integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        parsed = int(value)
    else:
        raise TypeError("quorum MUST be an integer")
    return max(1, parsed)


class ThorDispatchMixin:
    """Dispatch verdicts and multi-target batches without judging them."""

    _correlation_locks: WeakValueDictionary[str, _ReentrantAsyncLock]
    _resource_dispatch_locks: WeakValueDictionary[str, asyncio.Lock]
    action_runs: dict[str, ActionRun]
    _batch_rollup_targets: dict[str, tuple[str, ...]]
    _batch_rollup_verdicts: dict[str, dict[str, Any]]
    _idempotency_runs: dict[str, ActionRun]
    _resource_locks: set[str]
    _saga_available: bool
    _vidar_available: bool
    _action_semantics: action_semantics.ActionSemanticsCatalog | None
    _hil_timeout_seconds: int
    _state_store: ActionRunStore | None
    _batch_attempt_rollups: dict[str, str]
    _batch_rollup_attempts: dict[str, tuple[str, ...]]
    _executor: ActionExecutor
    _executor_timeout_seconds: float
    _effect_verification_timeout_seconds: int
    _execution_audit_timeout_seconds: float
    _execution_audit_recorder: ExecutionAuditRecorder | None
    _require_execution_audit: bool
    _preflight_simulator: thor_preflight.ThorPreflightSimulator | None
    _preflight_timeout_seconds: float
    _preflight_receipt_ttl_seconds: int
    _execution_resource_lock: ResourceLock | None
    _require_execution_resource_lock: bool
    _test_context_dispatch_guard: TestContextDispatchGuard | None

    if TYPE_CHECKING:

        async def _execute(self, run: ActionRun) -> None: ...

        def record_behavior(self, name: str, amount: int = 1) -> None: ...

        async def _emit_action_run(self, run: ActionRun) -> None: ...

        async def _resume_rehydrated(self, run: ActionRun) -> None: ...

        async def _finalize_terminal_replay(self, run: ActionRun) -> None: ...

        def _find_active_run(self, resource_id: str) -> ActionRun | None: ...

        def _must_shadow(self) -> bool: ...

        def _admit_development_verdict(
            self,
            *,
            evidence: object,
            action: Mapping[str, Any],
            risk_verdict: str,
            original_quorum: int,
            effective_quorum: int,
        ) -> DevelopmentVerdictAuthority: ...

        def _now(self) -> datetime: ...

        def _release_lock(self, resource_id: object) -> None: ...

        def _unavailable_dependencies(self) -> frozenset[str]: ...

        def _approver_unavailable(self) -> bool: ...

        async def _release_resource_claim(self, run: ActionRun) -> None: ...

        async def _wait_for_dr_failover_contract(self, run: ActionRun) -> bool: ...

        def _revalidate_development_authority(self, run: ActionRun) -> None: ...

        async def _handle_effect_observation(self, observation: dict[str, Any]) -> None: ...

    async def dispatch_verdict(self, verdict: dict[str, Any]) -> ActionRun:
        """Serialize duplicate delivery for one correlation before dispatch."""

        correlation = str(verdict.get("correlation_id", ""))
        lock = self._correlation_locks.setdefault(correlation, _ReentrantAsyncLock())
        async with lock:
            batch_target_set = thor_batch.parse_batch_target_set(verdict)
            if batch_target_set is not None:
                return await self._dispatch_batch_verdict(
                    verdict,
                    batch_target_set=batch_target_set,
                )
            resource_id = str(verdict.get("resource_id") or "")
            if resource_id:
                resource_lock = self._resource_dispatch_locks.setdefault(
                    resource_id,
                    asyncio.Lock(),
                )
                async with resource_lock:
                    run = await self._dispatch_verdict_once(
                        verdict,
                        defer_auto_execution=True,
                    )
            else:
                run = await self._dispatch_verdict_once(
                    verdict,
                    defer_auto_execution=True,
                )
        if run.verdict == "auto" and run.state is ActionRunState.VERDICTED:
            await self._execute(run)
        return run

    async def _dispatch_batch_verdict(
        self,
        verdict: dict[str, Any],
        *,
        batch_target_set: thor_batch.BatchTargetSet | thor_batch.BatchHold,
    ) -> ActionRun:
        if isinstance(batch_target_set, thor_batch.BatchHold):
            held_verdict = deepcopy(dict(verdict))
            held_verdict["resource_id"] = (
                "target-set:held:"
                + str(verdict.get("correlation_id") or "unknown").replace(":", "-")[:64]
            )
            return await self._emit_terminal_rejection(
                held_verdict,
                outcome=batch_target_set.outcome,
                params_extra={
                    "target_count": batch_target_set.target_count,
                    "max_targets": batch_target_set.max_targets,
                },
            )
        rollup_verdict = deepcopy(dict(verdict))
        rollup_verdict.pop("targets", None)
        rollup_verdict.pop("target_set", None)
        rollup_verdict["resource_id"] = thor_batch.rollup_resource_id(batch_target_set)
        rollup_verdict["batch_role"] = "rollup"
        rollup_verdict["target_set_digest"] = batch_target_set.digest
        rollup_verdict["target_set"] = list(batch_target_set.targets)
        rollup_verdict["target_count"] = len(batch_target_set.targets)
        existing = self.action_runs.get(str(verdict.get("correlation_id", "")))
        if existing is not None:
            self.record_behavior("dispatch:batch_duplicate")
            if existing.verdict == "auto" and existing.state is ActionRunState.VERDICTED:
                await self._execute_batch_rollup(existing)
            return existing
        rollup = await self._dispatch_verdict_once(rollup_verdict, defer_auto_execution=True)
        rollup.batch_role = "rollup"
        rollup.target_set_digest = batch_target_set.digest
        rollup.target_set = batch_target_set.targets
        rollup.target_count = len(batch_target_set.targets)
        rollup.batch_rollup = thor_batch.build_rollup_fields(batch_target_set)["batch_rollup"]
        self._batch_rollup_targets[rollup.correlation_id] = batch_target_set.targets
        self._batch_rollup_verdicts[rollup.correlation_id] = deepcopy(dict(verdict))
        await self._emit_action_run(rollup)
        self.record_behavior("dispatch:batch_rollup")
        if rollup.state is ActionRunState.HIL_PENDING:
            return rollup
        if rollup.verdict == "auto" and rollup.state is ActionRunState.VERDICTED:
            await self._execute_batch_rollup(
                rollup, targets=batch_target_set.targets, verdict=verdict
            )
        return rollup

    async def _dispatch_verdict_once(
        self,
        verdict: dict[str, Any],
        *,
        defer_auto_execution: bool = False,
    ) -> ActionRun:
        correlation = str(verdict.get("correlation_id", ""))
        action_type = str(verdict.get("action_type", ""))
        risk_verdict = str(verdict.get("risk_verdict", "hil"))
        if risk_verdict not in _ACCEPTED_RISK_VERDICTS:
            self.record_behavior("dispatch:invalid_risk_verdict")
            return await self._emit_terminal_rejection(
                verdict,
                outcome="invalid_risk_verdict",
            )
        resolved_autonomy_ceiling = _resolved_autonomy_ceiling(verdict)
        if resolved_autonomy_ceiling is Autonomy.ENFORCE_HIL and risk_verdict == "auto":
            risk_verdict = "hil"
        if risk_verdict == "shadow":
            resolved_autonomy_ceiling = Autonomy.SHADOW_ONLY
        resource_id = verdict.get("resource_id")
        raw_decision_case = verdict.get("decision_case")
        decision_case = action_run_lineage.bounded_decision_case(raw_decision_case)
        raw_params = verdict.get("params")
        params = _bounded_params(raw_params)
        if params is None:
            self.record_behavior("dispatch:invalid_params")
            return await self._emit_terminal_rejection(
                verdict,
                outcome="invalid_params",
            )
        operational_context = _bounded_operational_context(verdict.get("operational_context"))
        if verdict.get("operational_context") is not None and operational_context is None:
            resolved_autonomy_ceiling = Autonomy.SHADOW_ONLY
        raw_kinetic_proposal = verdict.get("kinetic_proposal")
        kinetic_proposal = _kinetic_proposal(raw_kinetic_proposal)
        raw_prospective_lineage = verdict.get("prospective_lineage")
        prospective_lineage = _prospective_lineage(raw_prospective_lineage)
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
        invalid_prospective_lineage = raw_prospective_lineage is not None and (
            prospective_lineage is None
            or kinetic_proposal is None
            or prospective_lineage.correlation_id != correlation
            or prospective_lineage.proposal_id != kinetic_proposal.proposal_id
            or prospective_lineage.operational_plan_id != kinetic_proposal.operational_plan_id
            or prospective_lineage.mutation_plan_digest != kinetic_proposal.plan.digest
        )
        if (
            (semantic_arbitration and decision_case is None)
            or invalid_decision_case
            or invalid_kinetic_proposal
            or invalid_prospective_lineage
        ):
            risk_verdict = "deny"
            action_type = ""
            kinetic_proposal = None
            prospective_lineage = None
            if invalid_kinetic_proposal:
                self.record_behavior("kinetic_proposal:invalid")
            if invalid_prospective_lineage:
                self.record_behavior("prospective_lineage:invalid")
        elif kinetic_proposal is not None:
            self.record_behavior("kinetic_proposal:validated")

        if risk_verdict in {"auto", "hil"} and not action_type:
            self.record_behavior("dispatch:action_unavailable")
            return await self._emit_terminal_rejection(
                verdict,
                outcome="triage_action_unavailable",
            )

        # Idempotency: at-least-once redelivery after a terminated run would
        # re-execute unless an already dispatched correlation is a no-op.
        raw_idempotency_key = verdict.get("idempotency_key")
        if (
            not isinstance(raw_idempotency_key, str) or not raw_idempotency_key.strip()
        ) and verdict.get("producer_principal") is not None:
            self.record_behavior("dispatch:missing_idempotency_key")
            return await self._emit_terminal_rejection(
                verdict,
                outcome="missing_verdict_idempotency_key",
            )
        idempotency_key = (
            raw_idempotency_key.strip()
            if isinstance(raw_idempotency_key, str) and raw_idempotency_key.strip()
            else correlation
        )
        action_idempotency_key = str(verdict.get("action_idempotency_key") or idempotency_key)
        existing_by_corr = self.action_runs.get(correlation)
        if existing_by_corr is not None:
            if existing_by_corr.idempotency_key != action_idempotency_key:
                self.record_behavior("dispatch:correlation_reuse_rejected")
                return await self._emit_terminal_rejection(
                    verdict,
                    outcome="correlation_reuse_rejected",
                    correlation_id=f"{correlation}:rejected:{idempotency_key}",
                    params_extra={"rejected_correlation_id": correlation},
                )
            self.record_behavior("dispatch:duplicate")
            if existing_by_corr.state not in _TERMINAL_STATES:
                await self._resume_rehydrated(existing_by_corr)
            elif not existing_by_corr.terminal_published:
                await self._emit_action_run(existing_by_corr)
                await self._finalize_terminal_replay(existing_by_corr)
            else:
                await self._finalize_terminal_replay(existing_by_corr)
            return existing_by_corr
        existing_by_idempotency = self._idempotency_runs.get(action_idempotency_key)
        if existing_by_idempotency is not None:
            self.record_behavior("dispatch:idempotent_duplicate")
            existing_idempotency_run: ActionRun = existing_by_idempotency
            return existing_idempotency_run

        # Per-resource mutex: refuse to start a new run while another is
        # active on the same resource. Second dispatcher waits for the
        # first to terminate before starting.
        if resource_id and resource_id in self._resource_locks:
            existing = self._find_active_run(str(resource_id))
            if existing is not None:
                self.record_behavior("dispatch:lock_contention")
                return await self._emit_terminal_rejection(
                    verdict,
                    outcome="resource_active_action_run_contention",
                    params_extra={"blocking_correlation_id": existing.correlation_id},
                )
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
        wire_safeguard_required = verdict.get("producer_principal") is not None
        dry_run_evidence = None
        dry_run_receipt = None
        safeguards = verdict.get("safeguards")
        if isinstance(safeguards, Mapping):
            dry_run_evidence = str(safeguards.get("dry_run_evidence") or "").strip() or None
            raw_dry_run = safeguards.get("dry_run_receipt") or verdict.get("dry_run_receipt")
            dry_run_receipt = str(raw_dry_run).strip() if raw_dry_run is not None else None
            if dry_run_receipt and dry_run_evidence is None:
                dry_run_evidence = "upstream_receipt"
        elif verdict.get("dry_run_receipt") is not None:
            dry_run_evidence = "upstream_receipt"
            dry_run_receipt = str(verdict.get("dry_run_receipt")).strip()
        if risk_verdict in {"auto", "hil"} and wire_safeguard_required:
            missing_safeguards = _missing_wire_safeguards(verdict)
            if missing_safeguards:
                self.record_behavior("dispatch:missing_safeguards")
                if not shadow_mode:
                    return await self._emit_terminal_rejection(
                        verdict,
                        outcome="missing_safeguards",
                        params_extra={"missing_safeguards": list(missing_safeguards)},
                    )
            elif not shadow_mode and _dry_run_obligation_only(verdict):
                self.record_behavior("dispatch:dry_run_obligation_only")

        # Propagate the judge's quorum. Floor at 1 so a malformed verdict cannot
        # execute with no approver or drop a two-approver requirement.
        try:
            required_quorum = (
                action_semantics.quorum_for(action_type, self._action_semantics)
                if self._action_semantics is not None
                or (verdict.get("producer_principal") is not None and "safeguards" in verdict)
                else 1
            )
            original_quorum = _positive_quorum(
                verdict.get(
                    "original_quorum_required",
                    verdict.get("quorum_required", 1),
                )
            )
            if verdict.get("development_authority") is None:
                original_quorum = max(original_quorum, required_quorum)
            effective_quorum = _positive_quorum(
                verdict.get("effective_quorum_required", original_quorum),
            )
            effective_quorum = max(effective_quorum, original_quorum)
        except (TypeError, ValueError):
            self.record_behavior("dispatch:invalid_quorum")
            return await self._emit_terminal_rejection(
                verdict,
                outcome="invalid_quorum",
            )
        if risk_verdict == "auto" and original_quorum >= 2 and not shadow_mode:
            risk_verdict = "hil"
            self.record_behavior("dispatch:auto_quorum_lowered")
        action_id = action_run_lineage.optional_bounded_text(
            verdict.get("action_id"),
            field_name="action_id",
        )
        rollback_contract = (
            action_semantics.rollback_contract_for(action_type, self._action_semantics)
            if self._action_semantics is not None
            else str(verdict.get("rollback_contract", "state_forward_only"))
        )
        authority = self._admit_development_verdict(
            evidence=verdict.get("development_authority"),
            action={
                "action_type": action_type,
                "action_id": action_id,
                "resource_id": resource_id,
                "params": params,
                "idempotency_key": action_idempotency_key,
                "rollback_contract": rollback_contract,
                "initiator_principal": verdict.get("initiator_principal"),
            },
            risk_verdict=risk_verdict,
            original_quorum=original_quorum,
            effective_quorum=effective_quorum,
        )
        risk_verdict = authority.risk_verdict
        effective_quorum = authority.effective_quorum
        approval_profile = verdict.get("approval_profile")
        run = ActionRun(
            correlation_id=correlation,
            action_type=action_type,
            resource_id=resource_id,
            state=ActionRunState.VERDICTED,
            verdict=risk_verdict,
            action_id=action_id,
            idempotency_key=action_idempotency_key,
            params=params,
            shadow_mode=shadow_mode,
            resolved_autonomy_ceiling=resolved_autonomy_ceiling,
            quorum_required=effective_quorum,
            original_quorum_required=original_quorum,
            effective_quorum_required=effective_quorum,
            development_authority=authority.evidence,
            approval_profile=dict(approval_profile) if isinstance(approval_profile, dict) else None,
            initiator_principal=verdict.get("initiator_principal"),
            rollback_contract=rollback_contract,
            decision_case=decision_case,
            operational_context=operational_context,
            cost_annotation=(
                dict(verdict["cost_annotation"])
                if isinstance(verdict.get("cost_annotation"), dict)
                else None
            ),
            test_context_guard=(
                TestContextDispatchBinding.model_validate(verdict["test_context_guard"])
                if verdict.get("test_context_guard") is not None
                else None
            ),
            workflow_action=action_run_lineage.bounded_workflow_action(
                verdict.get("workflow_action")
            ),
            kinetic_proposal=(
                kinetic_proposal.model_dump(mode="json") if kinetic_proposal is not None else None
            ),
            prospective_lineage=(
                prospective_lineage.model_dump(mode="json")
                if prospective_lineage is not None
                else None
            ),
            dry_run_evidence=dry_run_evidence,
            dry_run_receipt=dry_run_receipt,
            approval_expires_at=(
                min(
                    self._now() + timedelta(seconds=self._hil_timeout_seconds),
                    authority.grant.valid_until,
                )
                if risk_verdict == "hil" and authority.grant is not None
                else self._now() + timedelta(seconds=self._hil_timeout_seconds)
                if risk_verdict == "hil"
                else None
            ),
        )
        thor_batch.apply_batch_verdict_fields(run, verdict)
        run.preflight_required = wire_safeguard_required and (
            dry_run_evidence == "declared_obligation"
            or thor_preflight.high_risk(run, self._action_semantics)
        )
        claim_status, existing = await resolve_correlation_claim(self._state_store, run)
        if claim_status in {"execution_completed", "correlation_completed"}:
            run.transition(ActionRunState.DENY_DROPPED)
            run.outcome = (
                "duplicate_execution_already_completed"
                if claim_status == "execution_completed"
                else "duplicate_correlation_already_completed"
            )
            self.action_runs[correlation] = run
            self._idempotency_runs[run.idempotency_key] = run
            await self._emit_action_run(run)
            self.record_behavior("dispatch:completed_duplicate")
            return run
        if claim_status == "contended":
            raise _ExecutionResourceUnavailableError
        if claim_status == "active":
            if existing is None:
                raise RuntimeError("Thor active correlation has no ActionRun")
            self.record_behavior("dispatch:idempotent_duplicate")
            existing_run: ActionRun = existing
            return existing_run
        self.action_runs[correlation] = run
        self._idempotency_runs[run.idempotency_key] = run
        if resource_id:
            self._resource_locks.add(str(resource_id))
        initial_publication_failed = False
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
            try:
                await self._emit_action_run(run)
            except Exception:
                initial_publication_failed = True
                raise
            # Record the verdict split so scenario checks can prove shadow and
            # deny paths never mutate.
            self.record_behavior(f"dispatch:{risk_verdict}")
            if shadow_mode:
                self.record_behavior("dispatch:shadow")
                # Distinguish a policy shadow (forced) from a degraded shadow (a
                # hard dependency - Saga/Vidar - is down), so a scenario can see
                # a safety-relevant degradation, not just "shadow".
                if self._unavailable_dependencies():
                    self.record_behavior("dispatch:degraded")

            if risk_verdict == "deny":
                run.transition(ActionRunState.DENY_DROPPED)
                await self._emit_action_run(run)
                self._release_lock(resource_id)
                return run

            if risk_verdict == "hil":
                if not shadow_mode and self._approver_unavailable():
                    run.outcome = "hil_held_approver_unavailable"
                    run.transition(ActionRunState.DENY_DROPPED)
                    await self._emit_action_run(run)
                    await self._release_resource_claim(run)
                    self._release_lock(resource_id)
                    self.record_behavior("dispatch:hil_approver_unavailable")
                    return run
                run.transition(ActionRunState.HIL_PENDING)
                await self._emit_action_run(run)
                # Lock is held intentionally across the HIL wait; released
                # when _execute (on approval) or the reject path terminates.
                return run

            # auto path (releases the lock via _execute's own finally)
            if defer_auto_execution:
                return run
            await self._execute(run)
            return run
        except Exception:
            # Fail-safe: a lifecycle emit (bus hiccup) MUST NOT leave the
            # resource locked forever - that would deadlock every future
            # action on it (permanent dispatch:lock_contention). Release and
            # re-raise. The HIL path returns normally, so its intentional lock
            # hold is unaffected by this guard.
            self.record_behavior("publication:unavailable")
            if initial_publication_failed and run.state is ActionRunState.VERDICTED:
                run.outcome = "action_run_publication_unavailable"
                cleaned = True
                if self._state_store is not None:
                    if run.resource_claimed:
                        claim_abandoned = (
                            await self._state_store.abandon_unpublished_resource_claim(run)
                        )
                        if claim_abandoned:
                            run.resource_claimed = False
                        else:
                            cleaned = False
                            self.record_behavior("publication:unpublished_resource_claim_retained")
                    if cleaned and not await self._state_store.discard_unpublished(run):
                        cleaned = False
                        self.record_behavior("publication:unpublished_run_discard_skipped")
                if cleaned:
                    self.action_runs.pop(correlation, None)
                    if self._idempotency_runs.get(run.idempotency_key) is run:
                        self._idempotency_runs.pop(run.idempotency_key, None)
                    self._release_lock(resource_id)
            raise

    async def _execute_batch_rollup(
        self,
        rollup: ActionRun,
        *,
        targets: tuple[str, ...] | None = None,
        verdict: Mapping[str, Any] | None = None,
    ) -> None:
        if rollup.batch_role != "rollup":
            return
        if targets is None:
            targets = self._batch_rollup_targets.get(rollup.correlation_id)
        if targets is None:
            targets = rollup.target_set
        if not thor_batch.target_set_matches_digest(targets, rollup.target_set_digest):
            rollup.transition(ActionRunState.DENY_DROPPED)
            rollup.outcome = "batch_target_set_digest_mismatch"
            await self._emit_action_run(rollup)
            await self._release_resource_claim(rollup)
            self._release_lock(rollup.resource_id)
            self.record_behavior("batch_target_set:digest_mismatch")
            return
        if targets is None:
            targets = tuple(
                str(run.resource_id)
                for run in self.action_runs.values()
                if run.rollup_correlation_id == rollup.correlation_id and run.resource_id
            )
        if verdict is None:
            verdict = self._batch_rollup_verdicts.get(rollup.correlation_id)
        if verdict is None:
            verdict = {
                **rollup.publication_identity_payload(),
                "idempotency_key": rollup.idempotency_key,
                "risk_verdict": rollup.verdict,
                "resolved_autonomy_ceiling": rollup.resolved_autonomy_ceiling.value,
                "rollback_contract": rollup.rollback_contract,
                "initiator_principal": rollup.initiator_principal,
                "dry_run_receipt": rollup.dry_run_receipt,
            }
        if rollup.state is ActionRunState.APPROVED:
            verdict = {
                **dict(verdict),
                "risk_verdict": "auto",
                "resolved_autonomy_ceiling": Autonomy.ENFORCE_AUTO.value,
            }
        if not targets:
            rollup.transition(ActionRunState.ROLLBACK_FAILED)
            rollup.outcome = "batch_target_set_unknown"
            await self._emit_action_run(rollup)
            return
        attempts: list[ActionRun] = []
        for target in targets:
            attempt_payload = thor_batch.attempt_verdict(verdict, rollup=rollup, target=target)
            attempt = await self._dispatch_verdict_once(attempt_payload, defer_auto_execution=False)
            self._batch_attempt_rollups[attempt.correlation_id] = rollup.correlation_id
            attempts.append(attempt)
        self._batch_rollup_attempts[rollup.correlation_id] = tuple(
            attempt.correlation_id for attempt in attempts
        )
        await self._refresh_batch_rollup(rollup.correlation_id)

    async def _refresh_batch_rollup(self, rollup_correlation_id: str) -> None:
        rollup = self.action_runs.get(rollup_correlation_id)
        if rollup is None or rollup.batch_role != "rollup":
            return
        attempt_ids = self._batch_rollup_attempts.get(rollup_correlation_id)
        if attempt_ids is None:
            attempt_ids = tuple(
                correlation_id
                for correlation_id, run in self.action_runs.items()
                if run.rollup_correlation_id == rollup_correlation_id
            )
            if attempt_ids:
                self._batch_rollup_attempts[rollup_correlation_id] = attempt_ids
        attempts = tuple(
            run for correlation_id in attempt_ids if (run := self.action_runs.get(correlation_id))
        )
        if not attempts:
            return
        state_before = rollup.state
        thor_batch.refresh_rollup(rollup, attempts)
        if rollup.state != state_before and rollup.state in _TERMINAL_STATES:
            rollup.terminal_published = False
        await self._emit_action_run(rollup)
        if state_before not in _TERMINAL_STATES and rollup.state in _TERMINAL_STATES:
            await self._release_resource_claim(rollup)
            self._release_lock(rollup.resource_id)

    def _batch_has_attempts(self, rollup_correlation_id: str) -> bool:
        return bool(self._batch_rollup_attempts.get(rollup_correlation_id)) or any(
            run.rollup_correlation_id == rollup_correlation_id for run in self.action_runs.values()
        )

    async def _invoke_executor(self, run: ActionRun) -> bool:
        return await thor_execution.invoke_executor(self, run)

    async def _claim_execution_resource(self, run: ActionRun) -> bool:
        return await thor_execution.claim_execution_resource(self, run)

    async def _emit_terminal_rejection(
        self,
        verdict: Mapping[str, Any],
        *,
        outcome: str,
        correlation_id: str | None = None,
        params_extra: Mapping[str, Any] | None = None,
    ) -> ActionRun:
        run_correlation = correlation_id or str(verdict.get("correlation_id") or "")
        run_idempotency = str(
            verdict.get("action_idempotency_key")
            or verdict.get("idempotency_key")
            or run_correlation
        )
        params = _bounded_params(verdict.get("params")) or {}
        if params_extra:
            params.update(dict(params_extra))
        run = ActionRun(
            correlation_id=run_correlation,
            action_type=str(verdict.get("action_type") or ""),
            resource_id=verdict.get("resource_id"),
            state=ActionRunState.VERDICTED,
            verdict="deny",
            action_id=action_run_lineage.optional_bounded_text(
                verdict.get("action_id"),
                field_name="action_id",
            ),
            idempotency_key=run_idempotency,
            params=params,
            shadow_mode=True,
            resolved_autonomy_ceiling=Autonomy.SHADOW_ONLY,
            outcome=outcome,
            initiator_principal=verdict.get("initiator_principal"),
            rollback_contract=str(verdict.get("rollback_contract", "state_forward_only")),
            cost_annotation=(
                dict(verdict["cost_annotation"])
                if isinstance(verdict.get("cost_annotation"), dict)
                else None
            ),
        )
        if run.correlation_id not in self.action_runs:
            self.action_runs[run.correlation_id] = run
            self._idempotency_runs[run.idempotency_key] = run
        await self._emit_action_run(run)
        run.transition(ActionRunState.DENY_DROPPED)
        await self._emit_action_run(run)
        self._release_lock(run.resource_id)
        return run


__all__ = ["ThorDispatchMixin", "_positive_quorum"]
