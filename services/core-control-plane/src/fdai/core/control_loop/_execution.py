"""Governance, risk-authority, and executor dispatch stages."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime

from fdai.core.control_loop._execution_effects import ControlLoopExecutionEffectsMixin
from fdai.core.control_loop._governance import ControlLoopGovernanceMixin
from fdai.core.control_loop._helpers import (
    _unified_audit_dict,
    build_shadow_authority_audit,
    evaluate_unified,
)
from fdai.core.control_loop._safeguard_commitment import ControlLoopSafeguardCommitmentMixin
from fdai.core.executor import ExecutionResult, ExecutorOutcome, ShadowExecutor
from fdai.core.executor.direct_api import DirectApiExecutionResult
from fdai.core.executor.port import DirectApiExecutionPort
from fdai.core.executor.tool_call import (
    ToolCallExecutionResult,
    ToolCallShadowExecutor,
)
from fdai.core.mscp_profile import MscpAuthorityCeiling
from fdai.core.ontology_platform.evidence_conflict import (
    EvidenceConflictCurrentReader,
    EvidenceConflictDisposition,
    current_evidence_conflict_ceiling,
)
from fdai.core.operational_planning import PreDispatchKineticSafetyWriter
from fdai.core.risk_gate.ceiling import AxisLevel
from fdai.core.risk_gate.evaluator import UnifiedRiskDecision
from fdai.core.risk_gate.gate import RiskGate
from fdai.core.risk_gate.live_probe import LiveProbeObservation
from fdai.core.risk_gate.preconditions import (
    AutomationHoldReader,
    AutomationHoldRecoveryReader,
    PreconditionEvaluation,
    PreconditionEvaluator,
)
from fdai.core.risk_gate.risk_table import RiskTable
from fdai.shared.contracts.models import (
    Action,
    Event,
    ExecutionPath,
    OntologyActionType,
    Rule,
    Tier,
)
from fdai.shared.providers.blast_probe import (
    BlastProbeError,
    LiveBlastProbe,
    ProbeQuery,
    ProbeVerdict,
)
from fdai.shared.providers.execution_authorization import (
    ExecutionAccessGrantSink,
    ExecutionAuthorizationEvaluator,
    ExecutionAuthorizationRequest,
    ExecutionAuthorizationResult,
    ExecutionAuthorizationStatus,
)
from fdai.shared.providers.state_store import StateStore
from fdai.shared.resilience import DegradationController, KillSwitch

_LOGGER = logging.getLogger("fdai.core.control_loop.orchestrator")
_LIVE_PROBE_MAX_DEADLINE_SECONDS = 60.0
_LIVE_PROBE_TIMEOUT_SLACK_SECONDS = 1.0


class ControlLoopExecutionMixin(
    ControlLoopExecutionEffectsMixin,
    ControlLoopGovernanceMixin,
    ControlLoopSafeguardCommitmentMixin,
):
    """Resolve governance, execution authority, and executor selection."""

    _action_types_by_name: Mapping[str, OntologyActionType]
    _audit_store: StateStore
    _clock: Callable[[], datetime]
    _degradation: DegradationController | None
    _direct_api_executor: DirectApiExecutionPort | None
    _executor: ShadowExecutor
    _execution_authorization_evaluator: ExecutionAuthorizationEvaluator | None
    _execution_access_grant_sink: ExecutionAccessGrantSink | None
    _evidence_conflict_reader: EvidenceConflictCurrentReader | None
    _inventory_age_provider: Callable[[str], Awaitable[int | None]] | None
    _kill_switch: KillSwitch | None
    _kill_switch_refresher: Callable[[], Awaitable[None]] | None
    _live_blast_probe: LiveBlastProbe | None
    _pre_dispatch_kinetic_safety_writer: PreDispatchKineticSafetyWriter | None
    _promotion_state_refresher: Callable[[str], Awaitable[None]] | None
    _precondition_evaluator: PreconditionEvaluator
    _automation_hold_reader: AutomationHoldReader | None
    _risk_gate: RiskGate | None
    _risk_table: RiskTable | None
    _tool_executor: ToolCallShadowExecutor | None

    async def _measure_live_probe(
        self,
        *,
        action: Action,
        action_type: OntologyActionType,
    ) -> LiveProbeObservation | None:
        probe_id = action_type.live_probe_ref
        if probe_id is None or self._live_blast_probe is None:
            return None
        try:
            async with asyncio.timeout(
                _LIVE_PROBE_MAX_DEADLINE_SECONDS + _LIVE_PROBE_TIMEOUT_SLACK_SECONDS
            ):
                result = await self._live_blast_probe.measure(
                    ProbeQuery(
                        probe_id=probe_id,
                        target_ref=action.target_resource_ref,
                        deadline_seconds=_LIVE_PROBE_MAX_DEADLINE_SECONDS,
                    )
                )
        except TimeoutError:
            _LOGGER.warning(
                "live_blast_probe_failed",
                extra={"action_type": action.action_type, "error_kind": "timeout"},
            )
            return LiveProbeObservation(
                probe_id=probe_id,
                verdict=ProbeVerdict.ACTIVE,
                degraded=True,
                age_seconds=0.0,
                max_age_seconds=_LIVE_PROBE_MAX_DEADLINE_SECONDS,
                reason="probe failure: timeout",
            )
        except BlastProbeError as exc:
            _LOGGER.warning(
                "live_blast_probe_failed",
                extra={"action_type": action.action_type, "error_kind": exc.kind},
            )
            return LiveProbeObservation(
                probe_id=probe_id,
                verdict=ProbeVerdict.ACTIVE,
                degraded=True,
                age_seconds=0.0,
                max_age_seconds=_LIVE_PROBE_MAX_DEADLINE_SECONDS,
                reason=f"probe failure: {exc.kind}",
            )
        except Exception:  # noqa: BLE001 - unexpected adapter failure lowers authority
            _LOGGER.warning(
                "live_blast_probe_failed",
                extra={"action_type": action.action_type, "error_kind": "unexpected"},
                exc_info=True,
            )
            return LiveProbeObservation(
                probe_id=probe_id,
                verdict=ProbeVerdict.ACTIVE,
                degraded=True,
                age_seconds=0.0,
                max_age_seconds=_LIVE_PROBE_MAX_DEADLINE_SECONDS,
                reason="probe failure: unexpected",
            )
        return LiveProbeObservation(
            probe_id=probe_id,
            verdict=result.verdict,
            degraded=result.degraded,
            age_seconds=0.0,
            max_age_seconds=_LIVE_PROBE_MAX_DEADLINE_SECONDS,
            reason=result.reason,
            metrics=result.metrics,
        )

    @staticmethod
    def _bind_authorized_identity(
        action: Action,
        authorization: ExecutionAuthorizationResult | None,
    ) -> Action:
        if authorization is None:
            return action
        if authorization.status is not ExecutionAuthorizationStatus.AUTHORIZED:
            return action
        identity_ref = authorization.executor_identity_ref
        if identity_ref is None:  # pragma: no cover - result contract rejects this
            raise ValueError("authorized execution identity is unavailable")
        return action.model_copy(update={"executor_identity_ref": identity_ref})

    async def _evaluate_execution_authorization(
        self,
        *,
        event: Event,
        action: Action,
    ) -> ExecutionAuthorizationResult | None:
        evaluator = self._execution_authorization_evaluator
        if evaluator is None:
            return None
        try:
            result = await evaluator.evaluate(
                ExecutionAuthorizationRequest(
                    action_id=str(action.action_id),
                    action_type_id=action.action_type,
                    target_resource_ref=action.target_resource_ref,
                    correlation_id=event.correlation_id or str(event.event_id),
                    idempotency_key=action.idempotency_key,
                )
            )
        except Exception:  # noqa: BLE001 - authorization lookup fails closed
            _LOGGER.warning(
                "execution_authorization_evaluation_failed",
                extra={"action_type": action.action_type},
                exc_info=True,
            )
            result = ExecutionAuthorizationResult(
                status=ExecutionAuthorizationStatus.UNKNOWN,
                decision_digest="evaluator-unavailable",
                evaluator_ref="unavailable",
                reason_codes=("evaluator_unavailable",),
            )
        grant_requests: list[dict[str, str | None]] = []
        if result.status is ExecutionAuthorizationStatus.GRANT_REQUIRED:
            sink = self._execution_access_grant_sink
            if sink is None:
                grant_requests = [
                    {
                        "requirement_id": proposal.requirement_id,
                        "scope_ref": proposal.scope_ref,
                        "request_id": None,
                        "state": "sink_unavailable",
                    }
                    for proposal in result.grant_proposals
                ]
            else:
                for proposal in result.grant_proposals:
                    if proposal.idempotency_key != action.idempotency_key:
                        raise ValueError("grant proposal idempotency key does not match action")
                    if proposal.original_action_id != str(action.action_id):
                        raise ValueError("grant proposal action id does not match action")
                    if proposal.authorization_decision_digest != result.decision_digest:
                        raise ValueError("grant proposal decision digest does not match result")
                for proposal in result.grant_proposals:
                    request_id: str | None = None
                    state = "submitted"
                    try:
                        request_id = await sink.submit_grant(proposal)
                    except Exception:  # noqa: BLE001 - original action remains held
                        state = "submission_failed"
                        _LOGGER.warning(
                            "execution_access_grant_submission_failed",
                            extra={
                                "action_type": action.action_type,
                                "requirement_id": proposal.requirement_id,
                            },
                            exc_info=True,
                        )
                    grant_requests.append(
                        {
                            "requirement_id": proposal.requirement_id,
                            "scope_ref": proposal.scope_ref,
                            "request_id": request_id,
                            "state": state,
                        }
                    )
        await self._audit_store.append_audit_entry(
            {
                "event_id": str(event.event_id),
                "correlation_id": event.correlation_id or str(event.event_id),
                "idempotency_key": event.idempotency_key,
                "actor": result.evaluator_ref,
                "producer_principal": "Forseti",
                "action_kind": "execution_authorization.decided",
                "mode": action.mode.value,
                "action_id": str(action.action_id),
                "action_type_id": action.action_type,
                "decision": result.status.value,
                "decision_digest": result.decision_digest,
                "executor_identity_ref": result.executor_identity_ref,
                "reason_codes": list(result.reason_codes),
                "authorization": dict(result.audit_context),
                "grant_requests": grant_requests,
                "grant_execution_profiles": sorted(
                    {proposal.execution_profile for proposal in result.grant_proposals}
                ),
                "grant_executor_identity_refs": sorted(
                    {proposal.executor_identity_ref for proposal in result.grant_proposals}
                ),
                "grant_modes": sorted({proposal.grant_mode for proposal in result.grant_proposals}),
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            }
        )
        return result

    async def _dispatch_action(
        self,
        *,
        action: Action,
        rule: Rule,
        correlation_id: str = "",
    ) -> ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult:
        """Route an action to the executor its ActionType declares."""
        action_type = self._action_types_by_name.get(action.action_type)
        conflict_hold = await self._current_evidence_conflict_hold(
            action=action,
            action_type=action_type,
        )
        if conflict_hold is not None:
            blocked_at = self._clock()
            return await self._complete_execution_result(
                action=action,
                result=conflict_hold,
                expected=None,
                prediction_failure=None,
                correlation_id=correlation_id,
                execution_started_at=blocked_at,
                execution_ended_at=blocked_at,
            )
        writer = self._pre_dispatch_kinetic_safety_writer
        if writer is not None:
            try:
                await writer.persist(action=action, correlation_id=correlation_id)
            except Exception:  # noqa: BLE001 - kinetic ambiguity blocks every executor
                _LOGGER.warning(
                    "pre_dispatch_kinetic_safety_failed",
                    extra={
                        "action_type": action.action_type,
                        "idempotency_key": action.idempotency_key,
                    },
                    exc_info=True,
                )
                blocked_result = ExecutionResult(
                    action_id=str(action.action_id),
                    outcome=ExecutorOutcome.REJECTED_INVARIANT,
                    mode=action.mode,
                    reason="pre-dispatch kinetic safety evidence is invalid",
                )
                blocked_at = self._clock()
                return await self._complete_execution_result(
                    action=action,
                    result=blocked_result,
                    expected=None,
                    prediction_failure=None,
                    correlation_id=correlation_id,
                    execution_started_at=blocked_at,
                    execution_ended_at=blocked_at,
                )
        path = action_type.execution_path if action_type is not None else None
        commitment_error = await self._prepare_workflow_safeguard_commitment(
            action=action,
            correlation_id=correlation_id,
        )
        if commitment_error is not None:
            blocked_result = ExecutionResult(
                action_id=str(action.action_id),
                outcome=ExecutorOutcome.REJECTED_INVARIANT,
                mode=action.mode,
                reason=commitment_error,
            )
            blocked_at = self._clock()
            return await self._complete_execution_result(
                action=action,
                result=blocked_result,
                expected=None,
                prediction_failure=None,
                correlation_id=correlation_id,
                execution_started_at=blocked_at,
                execution_ended_at=blocked_at,
            )
        expected, prediction_failure = await self._prepare_mscp_effect(action)
        execution_started_at = self._clock()
        result: ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult

        if path is ExecutionPath.DIRECT_API and self._direct_api_executor is not None:
            result = await self._direct_api_executor.execute(action=action)
        elif path is ExecutionPath.TOOL_CALL and self._tool_executor is not None:
            result = await self._tool_executor.execute(action=action)
        elif path in (ExecutionPath.DIRECT_API, ExecutionPath.TOOL_CALL):
            reason = f"execution_path {path.value!r} has no wired executor"
            _LOGGER.warning(
                "action_dispatch_executor_unavailable",
                extra={
                    "action_type": action.action_type,
                    "execution_path": path.value,
                    "idempotency_key": action.idempotency_key,
                },
            )
            result = ExecutionResult(
                action_id=str(action.action_id),
                outcome=ExecutorOutcome.REJECTED_INVARIANT,
                mode=action.mode,
                reason=reason,
            )
        else:
            result = await self._executor.execute(
                action=action,
                rule=rule,
                execution_path=(
                    path if path is ExecutionPath.PR_MANUAL else ExecutionPath.PR_NATIVE
                ),
            )
        execution_ended_at = self._clock()
        return await self._complete_execution_result(
            action=action,
            result=result,
            expected=expected,
            prediction_failure=prediction_failure,
            correlation_id=correlation_id,
            execution_started_at=execution_started_at,
            execution_ended_at=execution_ended_at,
        )

    async def _current_evidence_conflict_hold(
        self,
        *,
        action: Action,
        action_type: OntologyActionType | None,
    ) -> ExecutionResult | None:
        reader = self._evidence_conflict_reader
        if reader is None or action_type is None:
            return None
        try:
            ceiling, disposition, conflicts = await current_evidence_conflict_ceiling(
                reader,
                action_type=action_type,
                target_ref=action.target_resource_ref,
                evaluated_at=datetime.now(tz=UTC),
            )
        except Exception:  # noqa: BLE001 - unreadable conflict state blocks executor I/O
            _LOGGER.warning(
                "evidence_conflict_lookup_failed",
                extra={"action_type": action.action_type},
                exc_info=True,
            )
            return ExecutionResult(
                action_id=str(action.action_id),
                outcome=ExecutorOutcome.REJECTED_INVARIANT,
                mode=action.mode,
                reason="evidence-conflict current state is unavailable",
            )
        if not conflicts:
            return None
        _LOGGER.info(
            "evidence_conflict_execution_held",
            extra={
                "action_type": action.action_type,
                "conflict_disposition": disposition.value,
                "conflict_revision_refs": [item.revision_ref for item in conflicts],
                "authority_ceiling": ceiling.value,
            },
        )
        return ExecutionResult(
            action_id=str(action.action_id),
            outcome=ExecutorOutcome.REJECTED_INVARIANT,
            mode=action.mode,
            reason=f"evidence conflict requires shadow-only: {disposition.value}",
        )

    async def _evaluate_and_audit(
        self,
        *,
        event: Event,
        action: Action,
        rule: Rule,
        tier: Tier = Tier.T0,
    ) -> UnifiedRiskDecision | None:
        """Evaluate unified risk authority and append its audit row."""
        if self._risk_table is None:
            return None
        action_type = self._action_types_by_name.get(action.action_type)
        if action_type is None:
            return None
        promotion_refresh_failed = False
        if self._promotion_state_refresher is not None:
            try:
                await self._promotion_state_refresher(action_type.name)
            except Exception:  # noqa: BLE001 - stale promotion authority fails closed
                promotion_refresh_failed = True
                _LOGGER.warning(
                    "promotion_state_refresh_failed",
                    extra={"action_type": action.action_type},
                    exc_info=True,
                )
        cost_override = await self._resolve_cost_override(rule=rule, action_type=action_type)
        system_degraded = promotion_refresh_failed or (
            self._degradation is not None and not self._degradation.autonomy_permitted()
        )
        kill_switch_refresh_failed = False
        if self._kill_switch_refresher is not None:
            try:
                await self._kill_switch_refresher()
            except Exception:  # noqa: BLE001 - emergency-state lookup fails closed
                kill_switch_refresh_failed = True
                _LOGGER.warning(
                    "kill_switch_refresh_failed",
                    extra={"action_type": action.action_type},
                    exc_info=True,
                )
        kill_switch_engaged = kill_switch_refresh_failed or (
            self._kill_switch is not None and self._kill_switch.is_engaged()
        )
        inventory_age_seconds = None
        if self._inventory_age_provider is not None:
            try:
                inventory_age_seconds = await self._inventory_age_provider(
                    action.target_resource_ref
                )
            except Exception:  # noqa: BLE001 - freshness lookup fails closed
                _LOGGER.warning(
                    "inventory_age_lookup_failed",
                    extra={"action_type": action.action_type},
                    exc_info=True,
                )
        precondition_evaluations: tuple[PreconditionEvaluation, ...] = ()
        automation_hold_engaged = False
        automation_hold_recovery = False
        if self._automation_hold_reader is not None:
            try:
                automation_hold_engaged = await self._automation_hold_reader.is_held(
                    target_ref=action.target_resource_ref
                )
                lineage = action.workflow_action
                if (
                    automation_hold_engaged
                    and lineage is not None
                    and isinstance(self._automation_hold_reader, AutomationHoldRecoveryReader)
                ):
                    automation_hold_recovery = await self._automation_hold_reader.recovery_eligible(
                        target_ref=action.target_resource_ref,
                        process_id=lineage.process_id,
                        step_id=lineage.step_id,
                    )
            except Exception:  # noqa: BLE001 - unreadable hold state denies execution
                automation_hold_engaged = True
                automation_hold_recovery = False
                _LOGGER.warning(
                    "automation_hold_lookup_failed",
                    extra={"action_type": action.action_type},
                    exc_info=True,
                )
        try:
            precondition_evaluations = await self._precondition_evaluator.evaluate(
                event=event,
                action=action,
                action_type=action_type,
            )
        except Exception:  # noqa: BLE001 - missing evidence fails closed in RiskGate
            _LOGGER.warning(
                "action_precondition_evaluation_failed",
                extra={"action_type": action.action_type},
                exc_info=True,
            )
        live_probe_observation = await self._measure_live_probe(
            action=action,
            action_type=action_type,
        )
        if self._risk_gate is not None:
            unified = evaluate_unified(
                event=event,
                action=action,
                rule=rule,
                action_type=action_type,
                table=self._risk_table,
                risk_gate=self._risk_gate,
                tier=tier,
                cost_override=cost_override,
                system_degraded=system_degraded,
                kill_switch_engaged=kill_switch_engaged,
                inventory_age_seconds=inventory_age_seconds,
                precondition_evaluations=precondition_evaluations,
                automation_hold_engaged=automation_hold_engaged,
                automation_hold_recovery=automation_hold_recovery,
                live_probe_observation=live_probe_observation,
            )
            conflict_disposition = EvidenceConflictDisposition.NOT_APPLICABLE
            conflict_revision_refs: list[str] = []
            if self._evidence_conflict_reader is not None:
                try:
                    (
                        ceiling,
                        conflict_disposition,
                        conflicts,
                    ) = await current_evidence_conflict_ceiling(
                        self._evidence_conflict_reader,
                        action_type=action_type,
                        target_ref=action.target_resource_ref,
                        evaluated_at=datetime.now(tz=UTC),
                    )
                    if (
                        ceiling is MscpAuthorityCeiling.HOLD
                        and unified.level > AxisLevel.SHADOW_ONLY
                    ):
                        unified = replace(
                            unified,
                            level=AxisLevel.SHADOW_ONLY,
                            winning_side="evidence_conflict",
                        )
                    conflict_revision_refs = [item.revision_ref for item in conflicts]
                except Exception:  # noqa: BLE001 - unreadable current conflict fails closed
                    unified = replace(
                        unified,
                        level=min(unified.level, AxisLevel.SHADOW_ONLY),
                        winning_side="evidence_conflict_unavailable",
                    )
                    conflict_disposition = EvidenceConflictDisposition.EXPIRED_UNRESOLVED
            entry = _unified_audit_dict(event=event, action=action, unified=unified)
            entry["evidence_conflict"] = {
                "disposition": conflict_disposition.value,
                "revision_refs": conflict_revision_refs,
            }
            entry["recorded_at"] = datetime.now(tz=UTC).isoformat()
            await self._audit_store.append_audit_entry(entry)
            return unified
        entry = build_shadow_authority_audit(
            event=event,
            action=action,
            rule=rule,
            action_type=action_type,
            table=self._risk_table,
            tier=tier,
            cost_override=cost_override,
            system_degraded=system_degraded,
            kill_switch_engaged=kill_switch_engaged,
            live_probe_observation=live_probe_observation,
        )
        entry["recorded_at"] = datetime.now(tz=UTC).isoformat()
        await self._audit_store.append_audit_entry(entry)
        return None


__all__ = ["ControlLoopExecutionMixin"]
