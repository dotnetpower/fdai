"""Crash-safe reverse compensation for partially applied workflow runs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.core.runbook.models import RunbookStep
from fdai.core.workflow.automation_hold import StateStoreAutomationHoldLedger
from fdai.core.workflow.workflow_runtime import (
    WorkflowActionDispatcher,
    WorkflowOutcomeResolver,
    WorkflowOutcomeVerifier,
    event_id,
)
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessRuntimeStore,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.state_store import StateStore


@dataclass(frozen=True, slots=True)
class CompensationResult:
    snapshot: ProcessSnapshot
    recovery_incomplete: bool = False


class WorkflowCompensationCoordinator:
    """Dispatch compensation proposals and close only from verified receipts."""

    def __init__(
        self,
        *,
        process_store: ProcessRuntimeStore,
        audit_store: StateStore,
        dispatcher: WorkflowActionDispatcher | None,
        outcome_verifier: WorkflowOutcomeVerifier | None,
    ) -> None:
        self._process_store = process_store
        self._audit_store = audit_store
        self._dispatcher = dispatcher
        self._outcome_verifier = outcome_verifier
        self._automation_holds = StateStoreAutomationHoldLedger(audit_store)

    async def start(
        self,
        *,
        snapshot: ProcessSnapshot,
        compensations: Mapping[str, str],
        target_resource_id: str,
        context: Mapping[str, str],
    ) -> CompensationResult | None:
        events = await self._process_store.events(snapshot.process_id)
        applied = tuple(
            event.step_id
            for event in events
            if event.kind is ProcessEventKind.STEP_COMPLETED
            and event.step_id is not None
            and event.payload.get("reason") == "action_effect_verified"
        )
        if not applied:
            return None
        missing = tuple(step_id for step_id in applied if step_id not in compensations)
        if missing:
            failed = await self._fail(
                snapshot,
                reason="applied_step_missing_compensation",
                payload={"uncompensated_step_ids": list(missing)},
            )
            return CompensationResult(failed, recovery_incomplete=True)

        current = snapshot
        for step_id in reversed(applied):
            current = await self._record_intent(
                current,
                step_id=step_id,
                compensation_action_type=compensations[step_id],
            )
            dispatched = await self._dispatch_intent(
                current,
                step_id=step_id,
                compensation_action_type=compensations[step_id],
                target_resource_id=target_resource_id,
                context=context,
            )
            if dispatched.recovery_incomplete:
                return dispatched
            current = dispatched.snapshot
        return CompensationResult(current)

    async def resume(
        self,
        *,
        snapshot: ProcessSnapshot,
        target_resource_id: str,
        context: Mapping[str, str],
    ) -> CompensationResult:
        events = await self._process_store.events(snapshot.process_id)
        intents = tuple(
            event for event in events if event.kind is ProcessEventKind.COMPENSATION_STARTED
        )
        if not intents:
            failed = await self._fail(snapshot, reason="compensation_intent_missing")
            return CompensationResult(failed, recovery_incomplete=True)
        dispatched_steps = {
            str(event.payload.get("compensates_step_id") or "")
            for event in events
            if event.kind is ProcessEventKind.COMPENSATION_DISPATCHED
        }
        dispatched_by_step = {
            str(event.payload.get("compensates_step_id") or ""): event
            for event in events
            if event.kind is ProcessEventKind.COMPENSATION_DISPATCHED
        }
        current = snapshot
        for intent in intents:
            step_id = str(intent.payload.get("compensates_step_id") or "")
            action_type = str(intent.payload.get("action_type") or "")
            if not step_id or not action_type:
                failed = await self._fail(current, reason="malformed_compensation_intent")
                return CompensationResult(failed, recovery_incomplete=True)
            if step_id not in dispatched_steps:
                dispatched = await self._dispatch_intent(
                    current,
                    step_id=step_id,
                    compensation_action_type=action_type,
                    target_resource_id=target_resource_id,
                    context=context,
                )
                if dispatched.recovery_incomplete:
                    return dispatched
                current = dispatched.snapshot

        receipt_refs: list[str] = []
        for intent in intents:
            step_id = str(intent.payload["compensates_step_id"])
            status = context.get(f"compensation.{step_id}.status")
            receipt_ref = context.get(f"compensation.{step_id}.receipt_ref", "").strip()
            dispatch_event = dispatched_by_step.get(step_id)
            proposal_ref = (
                str(dispatch_event.payload.get("proposal_ref") or "").strip()
                if dispatch_event is not None
                else ""
            )
            if not proposal_ref or self._outcome_verifier is None:
                failed = await self._fail(
                    current,
                    reason="compensation_unscorable",
                    payload={"failed_step_id": step_id},
                )
                return CompensationResult(failed, recovery_incomplete=True)
            outcome = "succeeded" if status == "verified" else "failed"
            try:
                if isinstance(self._outcome_verifier, WorkflowOutcomeResolver):
                    resolved = await self._outcome_verifier.resolve(
                        process_id=current.process_id,
                        step_id=f"compensate_{step_id}",
                        proposal_ref=proposal_ref,
                    )
                    if resolved is None:
                        return CompensationResult(current)
                    outcome = resolved.outcome
                    receipt_ref = resolved.receipt_ref
                else:
                    if status is None:
                        return CompensationResult(current)
                    if status not in {"verified", "failed"}:
                        failed = await self._fail(
                            current,
                            reason="compensation_status_invalid",
                            payload={"failed_step_id": step_id},
                        )
                        return CompensationResult(failed, recovery_incomplete=True)
                    if not receipt_ref:
                        failed = await self._fail(
                            current,
                            reason="compensation_unscorable",
                            payload={"failed_step_id": step_id},
                        )
                        return CompensationResult(failed, recovery_incomplete=True)
                accepted = await self._outcome_verifier.verify(
                    process_id=current.process_id,
                    step_id=f"compensate_{step_id}",
                    proposal_ref=proposal_ref,
                    outcome=outcome,
                    receipt_ref=receipt_ref,
                )
            except Exception:  # noqa: BLE001 - verifier outage is recovery-incomplete
                accepted = False
            if not accepted:
                failed = await self._fail(
                    current,
                    reason="compensation_unscorable",
                    payload={"failed_step_id": step_id},
                )
                return CompensationResult(failed, recovery_incomplete=True)
            if outcome == "failed":
                failed = await self._fail(
                    current,
                    reason="compensation_failed",
                    payload={"failed_step_id": step_id},
                )
                return CompensationResult(failed, recovery_incomplete=True)
            receipt_refs.append(receipt_ref)

        completed = await self._process_store.transition(
            process_id=current.process_id,
            expected_revision=current.revision,
            status=ProcessStatus.COMPENSATED,
            current_step="",
            event=ProcessEvent(
                event_id=event_id(current.process_id, "compensation:completed"),
                process_id=current.process_id,
                kind=ProcessEventKind.COMPENSATION_COMPLETED,
                idempotency_key=f"{current.process_id}:compensation:completed",
                recorded_at=datetime.now(tz=UTC),
                correlation_id=current.correlation_id,
                payload={"receipt_refs": receipt_refs},
            ),
        )
        await self._audit(
            current,
            action_kind="workflow.compensation.verified",
            suffix="terminal",
            payload={"receipt_refs": receipt_refs},
        )
        return CompensationResult(completed)

    async def _record_intent(
        self,
        snapshot: ProcessSnapshot,
        *,
        step_id: str,
        compensation_action_type: str,
    ) -> ProcessSnapshot:
        compensation_step_id = f"compensate_{step_id}"
        await self._audit(
            snapshot,
            action_kind="workflow.compensation.intent",
            suffix=f"{step_id}:intent",
            payload={
                "step_id": compensation_step_id,
                "compensates_step_id": step_id,
                "action_type": compensation_action_type,
            },
        )
        return await self._process_store.transition(
            process_id=snapshot.process_id,
            expected_revision=snapshot.revision,
            status=ProcessStatus.COMPENSATING,
            current_step=compensation_step_id,
            event=ProcessEvent(
                event_id=event_id(snapshot.process_id, f"compensation:{step_id}:started"),
                process_id=snapshot.process_id,
                kind=ProcessEventKind.COMPENSATION_STARTED,
                idempotency_key=f"{snapshot.process_id}:compensation:{step_id}:started",
                recorded_at=datetime.now(tz=UTC),
                correlation_id=snapshot.correlation_id,
                step_id=compensation_step_id,
                payload={
                    "compensates_step_id": step_id,
                    "action_type": compensation_action_type,
                },
            ),
        )

    async def _dispatch_intent(
        self,
        snapshot: ProcessSnapshot,
        *,
        step_id: str,
        compensation_action_type: str,
        target_resource_id: str,
        context: Mapping[str, str],
    ) -> CompensationResult:
        if self._dispatcher is None:
            failed = await self._fail(snapshot, reason="compensation_dispatcher_not_configured")
            return CompensationResult(failed, recovery_incomplete=True)
        compensation_step = RunbookStep(
            id=f"compensate_{step_id}",
            action_type=compensation_action_type,
            params={"compensates_step_id": step_id},
        )
        try:
            proposal_ref = await self._dispatcher.dispatch(
                process_id=snapshot.process_id,
                correlation_id=snapshot.correlation_id,
                step=compensation_step,
                target_resource_id=target_resource_id,
                params=compensation_step.params,
                context=context,
            )
        except Exception as exc:  # noqa: BLE001 - typed dispatch failure fails closed
            failed = await self._fail(
                snapshot,
                reason=f"compensation_dispatch_failed:{type(exc).__name__}",
                payload={"failed_step_id": step_id},
            )
            return CompensationResult(failed, recovery_incomplete=True)
        if not proposal_ref.strip():
            failed = await self._fail(
                snapshot,
                reason="compensation_dispatch_returned_no_reference",
                payload={"failed_step_id": step_id},
            )
            return CompensationResult(failed, recovery_incomplete=True)
        await self._process_store.append_event(
            ProcessEvent(
                event_id=event_id(snapshot.process_id, f"compensation:{step_id}:dispatched"),
                process_id=snapshot.process_id,
                kind=ProcessEventKind.COMPENSATION_DISPATCHED,
                idempotency_key=f"{snapshot.process_id}:compensation:{step_id}:dispatched",
                recorded_at=datetime.now(tz=UTC),
                correlation_id=snapshot.correlation_id,
                step_id=compensation_step.id,
                payload={
                    "compensates_step_id": step_id,
                    "action_type": compensation_action_type,
                    "proposal_ref": proposal_ref,
                },
            )
        )
        return CompensationResult(snapshot)

    async def _fail(
        self,
        snapshot: ProcessSnapshot,
        *,
        reason: str,
        payload: Mapping[str, object] | None = None,
    ) -> ProcessSnapshot:
        failure_payload = {"reason": reason, "recovery_incomplete": True, **dict(payload or {})}
        await self._automation_holds.issue(
            target_ref=snapshot.target_resource_id,
            process_id=snapshot.process_id,
            reason=reason,
        )
        failed = await self._process_store.transition(
            process_id=snapshot.process_id,
            expected_revision=snapshot.revision,
            status=ProcessStatus.FAILED,
            current_step="",
            event=ProcessEvent(
                event_id=event_id(snapshot.process_id, f"compensation:failed:{snapshot.revision}"),
                process_id=snapshot.process_id,
                kind=ProcessEventKind.PROCESS_FAILED,
                idempotency_key=f"{snapshot.process_id}:compensation:failed:{snapshot.revision}",
                recorded_at=datetime.now(tz=UTC),
                correlation_id=snapshot.correlation_id,
                payload=failure_payload,
            ),
        )
        await self._audit(
            snapshot,
            action_kind="workflow.compensation.failed",
            suffix=f"failed:{failed.revision}",
            payload=failure_payload,
        )
        return failed

    async def _audit(
        self,
        snapshot: ProcessSnapshot,
        *,
        action_kind: str,
        suffix: str,
        payload: Mapping[str, object],
    ) -> None:
        await self._audit_store.append_audit_entry(
            {
                "event_id": event_id(snapshot.process_id, f"compensation:{suffix}:audit"),
                "correlation_id": snapshot.correlation_id,
                "actor": "fdai.core.workflow.compensation",
                "action_kind": action_kind,
                "process_id": snapshot.process_id,
                **dict(payload),
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            }
        )


__all__ = ["CompensationResult", "WorkflowCompensationCoordinator"]
