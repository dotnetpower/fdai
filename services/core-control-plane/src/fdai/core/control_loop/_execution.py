"""Governance, risk-authority, and executor dispatch stages."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime

from fdai.core.control_loop._helpers import (
    _unified_audit_dict,
    build_shadow_authority_audit,
    evaluate_unified,
)
from fdai.core.executor import ExecutionResult, ExecutorOutcome, ShadowExecutor
from fdai.core.executor.direct_api import DirectApiExecutionResult
from fdai.core.executor.port import DirectApiExecutionPort
from fdai.core.executor.tool_call import (
    ToolCallExecutionResult,
    ToolCallShadowExecutor,
)
from fdai.core.mscp_profile import (
    EffectVerificationReason,
    EffectVerificationResult,
    EffectVerificationStatus,
    ExpectedEffect,
    ExpectedEffectProvider,
    IndependentEffectObserver,
    ObservedEffect,
    build_response_outcome,
    build_shadow_effect_audit,
    response_outcome_audit_entry,
    verify_effect,
)
from fdai.core.ontology_platform.reconciliation_producer import (
    EffectReconciliationRequestSink,
    ReconciliationRequestProduction,
    ReconciliationRequestProductionStatus,
)
from fdai.core.operational_planning import PreDispatchKineticSafetyWriter
from fdai.core.risk_gate.evaluator import UnifiedRiskDecision
from fdai.core.risk_gate.gate import RiskGate
from fdai.core.risk_gate.preconditions import (
    AutomationHoldReader,
    AutomationHoldRecoveryReader,
    PreconditionEvaluation,
    PreconditionEvaluator,
)
from fdai.core.risk_gate.risk_table import RiskTable
from fdai.core.workflow.workflow_runtime import WorkflowOutcomeRecorder
from fdai.rule_catalog.schema.assignment import (
    Assignment,
    AssignmentResolution,
    resolve_assignments,
)
from fdai.rule_catalog.schema.scope import ResourceContext
from fdai.shared.contracts.models import (
    Action,
    Event,
    ExecutionPath,
    OntologyActionType,
    ResponseOutcome,
    Rule,
)
from fdai.shared.providers.cost_estimator import (
    CostEstimator,
    resolve_cost_impact_monthly,
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


class ControlLoopExecutionMixin:
    """Resolve governance, execution authority, and executor selection."""

    _action_types_by_name: Mapping[str, OntologyActionType]
    _audit_store: StateStore
    _cost_estimator: CostEstimator | None
    _degradation: DegradationController | None
    _direct_api_executor: DirectApiExecutionPort | None
    _executor: ShadowExecutor
    _execution_authorization_evaluator: ExecutionAuthorizationEvaluator | None
    _execution_access_grant_sink: ExecutionAccessGrantSink | None
    _governance_assignments: Sequence[Assignment]
    _inventory_age_provider: Callable[[str], Awaitable[int | None]] | None
    _kill_switch: KillSwitch | None
    _kill_switch_refresher: Callable[[], Awaitable[None]] | None
    _mscp_effect_observer: IndependentEffectObserver | None
    _mscp_expected_effect_provider: ExpectedEffectProvider | None
    _response_outcome_sink: Callable[[ResponseOutcome], Awaitable[None]] | None
    _workflow_outcome_recorder: WorkflowOutcomeRecorder | None
    _effect_reconciliation_request_sink: EffectReconciliationRequestSink | None
    _pre_dispatch_kinetic_safety_writer: PreDispatchKineticSafetyWriter | None
    _promotion_state_refresher: Callable[[str], Awaitable[None]] | None
    _precondition_evaluator: PreconditionEvaluator
    _automation_hold_reader: AutomationHoldReader | None
    _risk_gate: RiskGate | None
    _risk_table: RiskTable | None
    _tool_executor: ToolCallShadowExecutor | None

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

    def _resolve_governance_assignment(
        self,
        *,
        event: Event,
        resource_id: str,
        resource_type: str,
        rule_id: str,
    ) -> AssignmentResolution | None:
        if not self._governance_assignments:
            return None
        payload = event.payload
        resource = payload.get("resource")
        resource_data = resource if isinstance(resource, dict) else {}
        props = resource_data.get("props")
        props_data = props if isinstance(props, dict) else {}
        tags = props_data.get("tags")
        tag_data = tags if isinstance(tags, dict) else {}

        def _text(*keys: str) -> str:
            for key in keys:
                value = resource_data.get(key, payload.get(key))
                if isinstance(value, str) and value:
                    return value
            return ""

        context = ResourceContext(
            organization=_text("organization", "tenant_id"),
            account=_text("account", "subscription_id"),
            resource_group=_text("resource_group"),
            resource_id=resource_id,
            resource_type=resource_type,
            tags={str(key): str(value) for key, value in tag_data.items()},
        )
        return resolve_assignments(
            assignments=self._governance_assignments,
            ctx=context,
            rule_id=rule_id,
        )

    async def _resolve_cost_override(
        self,
        *,
        rule: Rule,
        action_type: OntologyActionType,
    ) -> float | None:
        """Return the cost override for the authority pipeline."""
        if rule.remediation.cost_impact_monthly_usd is not None:
            return None
        if self._cost_estimator is None:
            return None
        return await resolve_cost_impact_monthly(self._cost_estimator, action_type, arguments=None)

    async def _dispatch_action(
        self,
        *,
        action: Action,
        rule: Rule,
        correlation_id: str = "",
    ) -> ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult:
        """Route an action to the executor its ActionType declares."""
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
                return ExecutionResult(
                    action_id=str(action.action_id),
                    outcome=ExecutorOutcome.REJECTED_INVARIANT,
                    mode=action.mode,
                    reason="pre-dispatch kinetic safety evidence is invalid",
                )
        expected, prediction_failure = await self._prepare_mscp_effect(action)
        action_type = self._action_types_by_name.get(action.action_type)
        path = action_type.execution_path if action_type is not None else None
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
            result = await self._executor.execute(action=action, rule=rule)
        request_production = await self._produce_effect_reconciliation_request(
            action=action,
            result=result,
        )
        verification = await self._record_mscp_effect_shadow(
            action=action,
            result=result,
            expected=expected,
            prediction_failure=prediction_failure,
        )
        if verification is None and request_production is None:
            return result
        audit_context = dict(result.audit_context)
        if request_production is not None:
            audit_context.update(
                {
                    "effect_reconciliation_request_status": request_production.status.value,
                    "effect_reconciliation_request_reason": request_production.reason_code,
                    **(
                        {"effect_reconciliation_id": request_production.reconciliation_id}
                        if request_production.reconciliation_id is not None
                        else {}
                    ),
                }
            )
        if verification is not None:
            audit_context.update(
                {
                    "effect_verified": (verification.status is EffectVerificationStatus.VERIFIED),
                    "effect_verification_status": verification.status.value,
                    "effect_verification_reason": verification.reason.value,
                }
            )
        return replace(
            result,
            audit_context=audit_context,
        )

    async def _produce_effect_reconciliation_request(
        self,
        *,
        action: Action,
        result: ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult,
    ) -> ReconciliationRequestProduction | None:
        sink = self._effect_reconciliation_request_sink
        if sink is None:
            return None
        try:
            return await sink(
                action,
                result.outcome.value,
                getattr(result, "receipt_ref", None) or getattr(result, "pr_ref", None),
            )
        except Exception:  # noqa: BLE001 - dispatch cannot become observed success
            _LOGGER.warning(
                "effect_reconciliation_request_failed",
                extra={"action_type": action.action_type},
                exc_info=True,
            )
            return ReconciliationRequestProduction(
                status=ReconciliationRequestProductionStatus.HELD,
                reason_code="request_publication_failed",
            )

    async def _prepare_mscp_effect(
        self,
        action: Action,
    ) -> tuple[ExpectedEffect | None, EffectVerificationReason | None]:
        provider = self._mscp_expected_effect_provider
        if provider is None:
            return None, None
        try:
            expected = await provider(action)
        except Exception:  # noqa: BLE001 - shadow observer never breaks dispatch
            _LOGGER.warning(
                "mscp_effect_prediction_failed",
                extra={"action_type": action.action_type},
                exc_info=True,
            )
            return None, EffectVerificationReason.PREDICTION_PROVIDER_FAILED
        if expected is None:
            return None, EffectVerificationReason.PREDICTION_UNAVAILABLE
        if expected.target_ref != action.target_resource_ref:
            return expected, EffectVerificationReason.PREDICTION_TARGET_MISMATCH
        return expected, None

    async def _record_mscp_effect_shadow(
        self,
        *,
        action: Action,
        result: ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult,
        expected: ExpectedEffect | None,
        prediction_failure: EffectVerificationReason | None,
    ) -> EffectVerificationResult | None:
        """Audit independent effect evidence and return only durable verification."""
        observer = self._mscp_effect_observer
        if observer is None:
            return None

        observed: ObservedEffect | None = None
        if prediction_failure is not None:
            verification = EffectVerificationResult(
                EffectVerificationStatus.HOLD,
                prediction_failure,
            )
        elif expected is None:  # pragma: no cover - constructor/provider contract narrows this
            verification = EffectVerificationResult(
                EffectVerificationStatus.HOLD,
                EffectVerificationReason.PREDICTION_UNAVAILABLE,
            )
        else:
            try:
                observed = await observer(action, expected)
            except Exception:  # noqa: BLE001 - shadow observer never breaks dispatch
                _LOGGER.warning(
                    "mscp_effect_observation_failed",
                    extra={"action_type": action.action_type},
                    exc_info=True,
                )
                verification = EffectVerificationResult(
                    EffectVerificationStatus.HOLD,
                    EffectVerificationReason.OBSERVATION_PROVIDER_FAILED,
                )
            else:
                verification = (
                    verify_effect(expected, observed)
                    if observed is not None
                    else EffectVerificationResult(
                        EffectVerificationStatus.HOLD,
                        EffectVerificationReason.OBSERVATION_UNAVAILABLE,
                    )
                )

        recorded_at = datetime.now(tz=UTC)
        entry = build_shadow_effect_audit(
            action=action,
            execution_outcome=result.outcome.value,
            verification=verification,
            recorded_at=recorded_at,
            expected=expected,
            observed=observed,
        )
        response_outcome = build_response_outcome(
            action=action,
            execution_outcome=result.outcome.value,
            verification=verification,
            recorded_at=recorded_at,
            expected=expected,
            observed=observed,
            decision=(
                "auto" if verification.status is EffectVerificationStatus.VERIFIED else "abstain"
            ),
            rollback_succeeded=getattr(result, "rollback_succeeded", None),
        )
        try:
            await self._audit_store.append_audit_entry(entry)
            await self._audit_store.append_audit_entry(
                response_outcome_audit_entry(response_outcome)
            )
        except Exception:  # noqa: BLE001 - side-consumer never changes executor result
            _LOGGER.warning(
                "mscp_effect_shadow_audit_failed",
                extra={"action_type": action.action_type},
                exc_info=True,
            )
            return None
        if self._response_outcome_sink is not None:
            try:
                await self._response_outcome_sink(response_outcome)
            except Exception:  # noqa: BLE001 - learning relay never changes executor result
                _LOGGER.warning(
                    "response_outcome_relay_failed",
                    extra={"action_type": action.action_type},
                    exc_info=True,
                )
        if self._workflow_outcome_recorder is not None:
            try:
                await self._workflow_outcome_recorder.record(
                    action=action,
                    execution_outcome=result.outcome.value,
                    execution_receipt_ref=(
                        getattr(result, "receipt_ref", None) or getattr(result, "pr_ref", None)
                    ),
                    response_outcome=response_outcome,
                )
            except Exception:  # noqa: BLE001 - missing receipt holds the Process
                _LOGGER.warning(
                    "workflow_outcome_record_failed",
                    extra={"action_type": action.action_type},
                    exc_info=True,
                )
        return verification

    async def _evaluate_and_audit(
        self, *, event: Event, action: Action, rule: Rule
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
        if self._risk_gate is not None:
            unified = evaluate_unified(
                event=event,
                action=action,
                rule=rule,
                action_type=action_type,
                table=self._risk_table,
                risk_gate=self._risk_gate,
                cost_override=cost_override,
                system_degraded=system_degraded,
                kill_switch_engaged=kill_switch_engaged,
                inventory_age_seconds=inventory_age_seconds,
                precondition_evaluations=precondition_evaluations,
                automation_hold_engaged=automation_hold_engaged,
                automation_hold_recovery=automation_hold_recovery,
            )
            entry = _unified_audit_dict(event=event, action=action, unified=unified)
            entry["recorded_at"] = datetime.now(tz=UTC).isoformat()
            await self._audit_store.append_audit_entry(entry)
            return unified
        entry = build_shadow_authority_audit(
            event=event,
            action=action,
            rule=rule,
            action_type=action_type,
            table=self._risk_table,
            cost_override=cost_override,
            system_degraded=system_degraded,
            kill_switch_engaged=kill_switch_engaged,
        )
        entry["recorded_at"] = datetime.now(tz=UTC).isoformat()
        await self._audit_store.append_audit_entry(entry)
        return None


__all__ = ["ControlLoopExecutionMixin"]
