"""Post-dispatch evidence handling shared by all execution exits."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime

from fdai.core.executor import ExecutionResult
from fdai.core.executor.direct_api import DirectApiExecutionResult
from fdai.core.executor.tool_call import ToolCallExecutionResult
from fdai.core.mscp_profile import (
    EffectVerificationReason,
    EffectVerificationResult,
    EffectVerificationStatus,
    ExpectedEffect,
    ExpectedEffectProvider,
    IndependentEffectObserver,
    ObservedEffect,
    admissible_effect_evidence,
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
from fdai.core.workflow.workflow_runtime import WorkflowOutcomeRecorder
from fdai.shared.contracts.execution_outcomes import execution_outcome_is_no_effect
from fdai.shared.contracts.models import Action, ResponseOutcome
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger("fdai.core.control_loop.orchestrator")

type ExecutionResultType = ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult


class ControlLoopExecutionEffectsMixin:
    """Record reconciliation, shadow evidence, and workflow outcomes."""

    _audit_store: StateStore
    _clock: Callable[[], datetime]
    _effect_reconciliation_request_sink: EffectReconciliationRequestSink | None
    _mscp_effect_observer: IndependentEffectObserver | None
    _mscp_expected_effect_provider: ExpectedEffectProvider | None
    _response_outcome_sink: Callable[[ResponseOutcome], Awaitable[None]] | None
    _workflow_outcome_recorder: WorkflowOutcomeRecorder | None

    async def _complete_execution_result(
        self,
        *,
        action: Action,
        result: ExecutionResultType,
        expected: ExpectedEffect | None,
        prediction_failure: EffectVerificationReason | None,
        correlation_id: str,
        execution_started_at: datetime,
        execution_ended_at: datetime,
    ) -> ExecutionResultType:
        if execution_outcome_is_no_effect(result.outcome):
            await self._record_workflow_no_effect(action=action, result=result)
            return result
        request_production = await self._produce_effect_reconciliation_request(
            action=action,
            result=result,
        )
        verification = await self._record_mscp_effect_shadow(
            action=action,
            result=result,
            expected=expected,
            prediction_failure=prediction_failure,
            correlation_id=correlation_id,
            execution_started_at=execution_started_at,
            execution_ended_at=execution_ended_at,
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
                    "effect_verified": verification.status is EffectVerificationStatus.VERIFIED,
                    "effect_verification_status": verification.status.value,
                    "effect_verification_reason": verification.reason.value,
                }
            )
        return replace(result, audit_context=audit_context)

    async def _record_workflow_no_effect(
        self,
        *,
        action: Action,
        result: ExecutionResultType,
    ) -> None:
        recorder = self._workflow_outcome_recorder
        if recorder is None or action.workflow_action is None:
            return
        recorded_at = self._clock()
        response_outcome = build_response_outcome(
            action=action,
            execution_outcome=result.outcome.value,
            verification=EffectVerificationResult(
                EffectVerificationStatus.HOLD,
                EffectVerificationReason.PREDICTION_UNAVAILABLE,
            ),
            recorded_at=recorded_at,
            decision="abstain",
            rollback_succeeded=getattr(result, "rollback_succeeded", None),
        )
        try:
            await recorder.record(
                action=action,
                execution_outcome=result.outcome.value,
                execution_receipt_ref=(
                    getattr(result, "receipt_ref", None) or getattr(result, "pr_ref", None)
                ),
                safeguard_bundle_digest=result.safeguard_bundle_digest,
                response_outcome=response_outcome,
            )
        except Exception:  # noqa: BLE001 - missing receipt holds the Process
            _LOGGER.warning(
                "workflow_outcome_record_failed",
                extra={"action_type": action.action_type},
                exc_info=True,
            )

    async def _produce_effect_reconciliation_request(
        self,
        *,
        action: Action,
        result: ExecutionResultType,
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
        result: ExecutionResultType,
        expected: ExpectedEffect | None,
        prediction_failure: EffectVerificationReason | None,
        correlation_id: str,
        execution_started_at: datetime,
        execution_ended_at: datetime,
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

        recorded_at = self._clock()
        verification, observed = admissible_effect_evidence(
            verification=verification,
            expected=expected,
            observed=observed,
            recorded_at=recorded_at,
            not_before=execution_ended_at,
        )
        entry = build_shadow_effect_audit(
            action=action,
            execution_outcome=result.outcome.value,
            verification=verification,
            recorded_at=recorded_at,
            expected=expected,
            observed=observed,
            dispatch_started_at=execution_started_at,
            dispatch_completed_at=execution_ended_at,
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
        execution_receipt_ref = getattr(result, "receipt_ref", None) or getattr(
            result, "pr_ref", None
        )
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
                    execution_receipt_ref=execution_receipt_ref,
                    safeguard_bundle_digest=result.safeguard_bundle_digest,
                    response_outcome=response_outcome,
                )
            except Exception:  # noqa: BLE001 - missing receipt holds the Process
                _LOGGER.warning(
                    "workflow_outcome_record_failed",
                    extra={"action_type": action.action_type},
                    exc_info=True,
                )
        return verification


__all__ = ["ControlLoopExecutionEffectsMixin"]
