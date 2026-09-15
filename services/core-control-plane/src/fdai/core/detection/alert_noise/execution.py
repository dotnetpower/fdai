"""Additive alert PR execution through Thor's existing safeguard lifecycle.

No dispatch journal, observer, promotion writer, or actor-name authorization lives here.
Production composition must supply trusted authority readers and an exclusive-writer fence;
an absent binding holds. Publication and lifecycle closure never verify an Azure effect.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime

from fdai_service_contracts.alert_noise import digest_record

from fdai.core.detection.alert_noise.execution_admission import _AlertExecutionAdmission
from fdai.core.detection.alert_noise.execution_models import (
    ALERT_ACTIONS as ALERT_ACTIONS,
)
from fdai.core.detection.alert_noise.execution_models import (
    RESTORE_ACTION as RESTORE_ACTION,
)
from fdai.core.detection.alert_noise.execution_models import (
    AlertAuthorityFence as AlertAuthorityFence,
)
from fdai.core.detection.alert_noise.execution_models import (
    AlertAuthorityLease as AlertAuthorityLease,
)
from fdai.core.detection.alert_noise.execution_models import (
    AlertExecutionHeld as AlertExecutionHeld,
)
from fdai.core.detection.alert_noise.execution_models import (
    AlertPlanReader as AlertPlanReader,
)
from fdai.core.detection.alert_noise.execution_models import (
    AlertPrDelivery as AlertPrDelivery,
)
from fdai.core.detection.alert_noise.execution_models import (
    AlertPrDispatch as AlertPrDispatch,
)
from fdai.core.detection.alert_noise.execution_models import (
    AlertPublicationCheck as AlertPublicationCheck,
)
from fdai.core.detection.alert_noise.execution_models import (
    AlertPublicationRecorder as AlertPublicationRecorder,
)
from fdai.core.detection.alert_noise.execution_models import (
    AlertRecoveryAdmission as AlertRecoveryAdmission,
)
from fdai.core.detection.alert_noise.execution_models import (
    AlertRecoveryAuthorityReader as AlertRecoveryAuthorityReader,
)
from fdai.core.detection.alert_noise.execution_models import (
    alert_execution_key as alert_execution_key,
)
from fdai.core.detection.alert_noise.execution_models import (
    alert_publication_digest as alert_publication_digest,
)
from fdai.core.executor.executor import ExecutionResult, ExecutorOutcome
from fdai.core.executor.port import _PrNativeExecutionPort
from fdai.core.executor.safeguard_lifecycle_coordinator import (
    SafeguardCoordinationDisposition,
    SafeguardLifecycleCoordinator,
)
from fdai.core.executor.safeguards import (
    SafeguardRefusal,
    evaluate_pre_dispatch,
    full_action_digest,
)
from fdai.shared.contracts.models import Action, ExecutionPath, Mode, OntologyTypeRef, Rule
from fdai.shared.providers.alert_noise import AlertAuthorityReader
from fdai.shared.providers.state_store import StateStore


class AlertActionExecution(_AlertExecutionAdmission):
    """Implement the PR execution port without changing the existing P1 fallback.

    Shadow produces audit only. Enforce requires current proof resolution twice, inside
    the dependency fence, and uses the existing reservation/audit/fence/closure coordinator.
    ``registered_actions`` must come from the reviewed catalog, not an Action payload.
    """

    def __init__(
        self,
        *,
        plans: AlertPlanReader,
        delivery: AlertPrDelivery,
        authority: AlertAuthorityReader | None,
        fence: AlertAuthorityFence | None,
        coordinator: SafeguardLifecycleCoordinator | None,
        audit_store: StateStore,
        fallback: _PrNativeExecutionPort,
        registered_actions: Mapping[str, OntologyTypeRef],
        clock: Callable[[], datetime],
        recovery: AlertRecoveryAuthorityReader | None = None,
        publication_recorder: AlertPublicationRecorder | None = None,
    ) -> None:
        self._plans, self._delivery, self._authority = plans, delivery, authority
        self._fence, self._coordinator, self._audit_store = fence, coordinator, audit_store
        self._fallback, self._registered = fallback, dict(registered_actions)
        self._clock, self._recovery = clock, recovery
        self._publication_recorder = publication_recorder

    async def execute(
        self,
        *,
        action: Action,
        rule: Rule,
        execution_path: ExecutionPath = ExecutionPath.PR_NATIVE,
    ) -> ExecutionResult:
        """Publish only a manual-review artifact; refusals and unknown outcomes are audited."""
        if action.action_type not in ALERT_ACTIONS:
            return await self._fallback.execute(
                action=action, rule=rule, execution_path=execution_path
            )
        port: AlertPrDispatch | None = None
        bundle: str | None = None
        outcome = ExecutorOutcome.REJECTED_INVARIANT
        reason: str | None = None
        try:
            action = Action.model_validate(action.model_dump(mode="python"))
            if action.mode is Mode.SHADOW:
                outcome = ExecutorOutcome.REJECTED_MODE
                raise AlertExecutionHeld("shadow_only")
            if execution_path is not ExecutionPath.PR_MANUAL:
                raise AlertExecutionHeld("manual_pr_required")
            if self._coordinator is None or self._fence is None:
                raise AlertExecutionHeld("safeguard_binding_missing")
            async with asyncio.timeout(15):
                plan = await self._load(action, rule)
            budget = (
                plan.max_recovery_seconds
                if action.action_type == RESTORE_ACTION
                else plan.max_execution_seconds
            )
            async with asyncio.timeout(budget):
                async with asyncio.timeout(15):
                    pr = await self._delivery.prepare(action=action, rule=rule, plan=plan)
                patch_digest = alert_publication_digest(plan, pr)
                safeguards = evaluate_pre_dispatch(
                    action,
                    execution_path=execution_path,
                    plan_digest=patch_digest,
                    plan_kind="alert_noise_manual_pr",
                )
                if isinstance(safeguards, SafeguardRefusal):
                    raise AlertExecutionHeld("declared_safeguard_missing")
                dry_run_receipt = safeguards.dry_run_receipt
                async with self._fence.hold(action=action, plan=plan, pr=pr) as lease:
                    await self._authorize(action, plan, pr, lease)

                    async def revalidate() -> AlertPublicationCheck:
                        async with asyncio.timeout(15):
                            current_plan = await self._load(action, rule)
                            current_pr = await self._delivery.prepare(
                                action=action, rule=rule, plan=current_plan
                            )
                            if current_plan != plan or current_pr != pr:
                                raise AlertExecutionHeld("prepared_publication_changed")
                            return await self._authorize(action, plan, pr, lease)

                    async def intent(digest: str) -> None:
                        await self._audit(
                            action,
                            rule,
                            "intent",
                            {
                                "plan_digest": digest_record(plan),
                                "patch_digest": patch_digest,
                                "dry_run_receipt": dry_run_receipt,
                                "safeguard_bundle_digest": digest,
                            },
                        )

                    port = self._delivery.dispatch_port(
                        pr=pr,
                        revalidate=revalidate,
                        audit_intent=intent,
                        dry_run_receipt=dry_run_receipt,
                    )
                    coordinated = await self._coordinator.dispatch(
                        action=action,
                        safeguard_receipt=safeguards,
                        dispatch_port=port,
                        correlation_id=str(action.event_id),
                        attempt=action.workflow_action.attempt if action.workflow_action else 1,
                    )
                    bundle = coordinated.bundle_digest
                if isinstance(port.error, asyncio.CancelledError):
                    raise port.error
                if (
                    port.error is not None
                    or coordinated.disposition is SafeguardCoordinationDisposition.QUARANTINED
                ):
                    outcome, reason = ExecutorOutcome.PUBLISH_OUTCOME_UNKNOWN, "publication_unknown"
                elif (
                    coordinated.disposition is SafeguardCoordinationDisposition.DUPLICATE
                    and bundle is not None
                ):
                    outcome = ExecutorOutcome.ALREADY_EXISTED
                elif (
                    coordinated.disposition is SafeguardCoordinationDisposition.COMPLETED
                    and coordinated.dispatch_performed
                    and bundle is not None
                    and port.receipt is not None
                ):
                    if self._publication_recorder is not None:
                        await self._publication_recorder.record(
                            action=action,
                            plan=plan,
                            receipt=port.receipt,
                            result=coordinated,
                        )
                    outcome = (
                        ExecutorOutcome.ALREADY_EXISTED
                        if port.receipt.already_existed
                        else ExecutorOutcome.PUBLISHED
                    )
                elif port.invoked:
                    outcome, reason = ExecutorOutcome.PUBLISH_OUTCOME_UNKNOWN, "publication_unknown"
                else:
                    reason = "safeguard_dispatch_held"
        except asyncio.CancelledError as cancelled:
            try:
                await self._finish(
                    action,
                    rule,
                    (
                        ExecutorOutcome.PUBLISH_OUTCOME_UNKNOWN
                        if port is not None and port.invoked
                        else ExecutorOutcome.REJECTED_INVARIANT
                    ),
                    "execution_cancelled",
                    port,
                    bundle,
                )
            except Exception as audit_error:
                raise cancelled from audit_error
            raise
        except Exception as exc:
            if port is not None and port.invoked:
                outcome, reason = ExecutorOutcome.PUBLISH_OUTCOME_UNKNOWN, "publication_unknown"
            else:
                reason = (
                    str(exc) if isinstance(exc, AlertExecutionHeld) else "admission_unavailable"
                )
        return await self._finish(action, rule, outcome, reason, port, bundle)

    async def _finish(
        self,
        action: Action,
        rule: Rule,
        outcome: ExecutorOutcome,
        reason: str | None,
        port: AlertPrDispatch | None,
        bundle: str | None,
    ) -> ExecutionResult:
        receipt = port.receipt if port is not None else None
        result = ExecutionResult(
            action_id=str(action.action_id),
            outcome=outcome,
            mode=action.mode,
            reason=reason,
            pr_ref=receipt.pr_ref if receipt else None,
            pr_url=receipt.url if receipt else None,
            safeguard_bundle_digest=bundle or (port.bundle_digest if port else None),
            audit_context={
                "execution_path": "pr_manual",
                "publication_only": True,
                "effect_verified": False,
            },
        )
        await self._audit(
            action,
            rule,
            "terminal",
            {
                **result.audit_context,
                "outcome": outcome.value,
                "reason": reason,
                "safeguard_bundle_digest": result.safeguard_bundle_digest,
                "pr_ref": result.pr_ref,
            },
        )
        return result

    async def _audit(
        self,
        action: Action,
        rule: Rule,
        phase: str,
        detail: Mapping[str, object],
    ) -> None:
        async with asyncio.timeout(15):
            await self._audit_store.append_audit_entry(
                {
                    "kind": "alert_noise.execution",
                    "audit_phase": phase,
                    "event_id": str(action.event_id),
                    "action_id": str(action.action_id),
                    "idempotency_key": action.idempotency_key,
                    "actor": action.executor_identity_ref,
                    "action_digest": full_action_digest(action),
                    "action_type": action.action_type,
                    "mode": action.mode.value,
                    "rule_id": rule.id,
                    "rule_version": rule.version,
                    "rollback_ref": action.rollback_ref.reference,
                    "workflow_action": (
                        action.workflow_action.model_dump(mode="json")
                        if action.workflow_action
                        else None
                    ),
                    "recorded_at": self._clock().isoformat(),
                    "effect_verified": False,
                    **detail,
                }
            )
