"""Crash-safe reverse compensation for partially applied workflow runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.core.runbook.models import RunbookStep
from fdai.core.workflow.automation_hold import StateStoreAutomationHoldLedger
from fdai.core.workflow.recovery_coordinator import (
    RecoveryDisposition,
    WorkflowRecoveryCoordinator,
)
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
        recovery_coordinator: WorkflowRecoveryCoordinator | None = None,
        automation_holds: StateStoreAutomationHoldLedger | None = None,
    ) -> None:
        self._process_store = process_store
        self._audit_store = audit_store
        self._dispatcher = dispatcher
        self._outcome_verifier = outcome_verifier
        self._automation_holds = automation_holds or StateStoreAutomationHoldLedger(audit_store)
        self._recovery_coordinator = recovery_coordinator

    async def start(
        self,
        *,
        snapshot: ProcessSnapshot,
        compensations: Mapping[str, str],
        target_resource_id: str,
        context: Mapping[str, str],
    ) -> CompensationResult | None:
        events = await self._process_store.events(snapshot.process_id)
        applied_events = tuple(
            event
            for event in events
            if event.kind is ProcessEventKind.STEP_COMPLETED
            and event.step_id is not None
            and event.payload.get("reason") == "action_effect_verified"
        )
        applied = tuple(event.step_id for event in applied_events if event.step_id is not None)
        if not applied:
            return None
        dispatched_actions = {
            event.step_id: event
            for event in events
            if event.kind is ProcessEventKind.ACTION_DISPATCHED and event.step_id is not None
        }
        missing = tuple(step_id for step_id in applied if step_id not in compensations)
        if missing:
            failed = await self._fail(
                snapshot,
                reason="applied_step_missing_compensation",
                payload={"uncompensated_step_ids": list(missing)},
            )
            return CompensationResult(failed, recovery_incomplete=True)
        missing_bundles = tuple(
            event.step_id
            for event in applied_events
            if not isinstance(event.payload.get("safeguard_bundle_digest"), str)
        )
        if missing_bundles:
            failed = await self._fail(
                snapshot,
                reason="applied_step_missing_safeguard_bundle",
                payload={"unbound_step_ids": list(missing_bundles)},
            )
            return CompensationResult(failed, recovery_incomplete=True)
        original_bundle_by_step = {
            event.step_id: str(event.payload["safeguard_bundle_digest"])
            for event in applied_events
            if event.step_id is not None
        }

        current = snapshot
        for step_id in reversed(applied):
            dispatch_event = dispatched_actions.get(step_id)
            raw_params = dispatch_event.payload.get("params") if dispatch_event else None
            if not isinstance(raw_params, Mapping):
                failed = await self._fail(
                    current,
                    reason="compensation_params_missing",
                    payload={"failed_step_id": step_id},
                )
                return CompensationResult(failed, recovery_incomplete=True)
            compensation_params = dict(raw_params)
            current = await self._record_intent(
                current,
                step_id=step_id,
                compensation_action_type=compensations[step_id],
                compensation_params=compensation_params,
                original_safeguard_bundle_digest=original_bundle_by_step[step_id],
            )
            dispatched = await self._dispatch_intent(
                current,
                step_id=step_id,
                compensation_action_type=compensations[step_id],
                compensation_params=compensation_params,
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
        repaired = await self._heal_released_recovery(snapshot)
        if repaired is not None:
            return repaired
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
            raw_params = intent.payload.get("params")
            if not step_id or not action_type or not isinstance(raw_params, Mapping):
                failed = await self._fail(current, reason="malformed_compensation_intent")
                return CompensationResult(failed, recovery_incomplete=True)
            if step_id not in dispatched_steps:
                dispatched = await self._dispatch_intent(
                    current,
                    step_id=step_id,
                    compensation_action_type=action_type,
                    compensation_params=dict(raw_params),
                    target_resource_id=target_resource_id,
                    context=context,
                )
                if dispatched.recovery_incomplete:
                    return dispatched
                current = dispatched.snapshot

        receipt_refs: list[str] = []
        safeguard_bundle_digests: list[str] = []
        for intent in intents:
            step_id = str(intent.payload["compensates_step_id"])
            status = context.get(f"compensation.{step_id}.status")
            receipt_ref = context.get(f"compensation.{step_id}.receipt_ref", "").strip()
            safeguard_bundle_digest: str | None = (
                context.get(
                    f"compensation.{step_id}.safeguard_bundle_digest",
                    "",
                ).strip()
                or None
            )
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
                    safeguard_bundle_digest = resolved.safeguard_bundle_digest
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
                    if not receipt_ref or (
                        status == "verified" and safeguard_bundle_digest is None
                    ):
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
            if safeguard_bundle_digest is None:
                failed = await self._fail(
                    current,
                    reason="compensation_unscorable",
                    payload={"failed_step_id": step_id},
                )
                return CompensationResult(failed, recovery_incomplete=True)
            receipt_refs.append(receipt_ref)
            safeguard_bundle_digests.append(safeguard_bundle_digest)

        if await self._automation_holds.is_held(target_ref=current.target_resource_id):
            recovery = await self._recover_under_hold(
                current,
                receipt_refs=receipt_refs,
                safeguard_bundle_digests=safeguard_bundle_digests,
                intents=intents,
            )
            if recovery is not None:
                return recovery
            refreshed = await self._process_store.get(current.process_id)
            if refreshed is not None:
                if refreshed.status.terminal:
                    return CompensationResult(refreshed)
                current = refreshed

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
                payload={
                    "receipt_refs": receipt_refs,
                    "safeguard_bundle_digests": safeguard_bundle_digests,
                },
            ),
        )
        await self._audit(
            current,
            action_kind="workflow.compensation.verified",
            suffix="terminal",
            payload={
                "receipt_refs": receipt_refs,
                "safeguard_bundle_digests": safeguard_bundle_digests,
            },
        )
        return CompensationResult(completed)

    async def _heal_released_recovery(
        self,
        snapshot: ProcessSnapshot,
    ) -> CompensationResult | None:
        """Repair a recovery that released its hold but never terminalized.

        A crash between the guarded hold release and the Process transition
        leaves the hold released while the Process and its Saga delivery are
        still open. The hold is gone, so the ordinary held-recovery branch can
        no longer see the work; without this the resume would close the Process
        outside the recovery completion it was released under. Healing runs
        first, repairs from the durable release binding after an arbitrary
        delay, and returns ``None`` when nothing durable is left to repair.
        """

        coordinator = self._recovery_coordinator
        if coordinator is None:
            return None
        try:
            healed = await coordinator.heal(snapshot=snapshot)
        except Exception:  # noqa: BLE001 - an unreadable recovery state fails closed
            failed = await self._fail(snapshot, reason="workflow_recovery_heal_failed")
            return CompensationResult(failed, recovery_incomplete=True)
        if healed is None:
            return None
        await self._audit(
            snapshot,
            action_kind="workflow.compensation.recovery_healed",
            suffix=f"heal:{healed.disposition.value}",
            payload={
                "disposition": healed.disposition.value,
                "reason": healed.reason,
                "attempt_identity_digest": healed.attempt_identity_digest,
                "effect_claim_digest": healed.effect_claim_digest,
                "release_receipt_digest": healed.release_receipt_digest,
                "completion_digest": healed.completion_digest,
            },
        )
        if healed.recovery_incomplete:
            failed = await self._fail(
                snapshot,
                reason="workflow_recovery_heal_incomplete",
                payload={
                    "recovery_disposition": healed.disposition.value,
                    "recovery_reason": healed.reason,
                },
            )
            return CompensationResult(failed, recovery_incomplete=True)
        terminal = await self._process_store.get(snapshot.process_id)
        if terminal is None or not terminal.status.terminal:
            return None
        return CompensationResult(terminal)

    async def _recover_under_hold(
        self,
        snapshot: ProcessSnapshot,
        *,
        receipt_refs: list[str],
        safeguard_bundle_digests: list[str],
        intents: tuple[ProcessEvent, ...],
    ) -> CompensationResult | None:
        """Close a held recovery only through the durable recovery path.

        Returns a terminal result when the hold MUST stay in force, and
        ``None`` when the recovery path released it and the Process may
        continue to its own terminal transition.
        """

        coordinator = self._recovery_coordinator
        recovery_receipt_ref = _recovery_receipt_ref(
            process_id=snapshot.process_id,
            receipt_refs=receipt_refs,
        )
        if coordinator is None:
            failed = await self._fail(
                snapshot,
                reason="recovery_coordinator_not_configured",
                payload={"recovery_receipt_ref": recovery_receipt_ref},
            )
            return CompensationResult(failed, recovery_incomplete=True)
        last_intent = intents[-1] if intents else None
        recovery_action_type = (
            str(last_intent.payload.get("action_type") or "") if last_intent is not None else ""
        )
        recovery_params = (
            dict(last_intent.payload.get("params") or {})
            if last_intent is not None and isinstance(last_intent.payload.get("params"), Mapping)
            else {}
        )
        try:
            outcome = await coordinator.recover(
                snapshot=snapshot,
                failed_compensation_proposal_digest=_compensation_proposal_digest(
                    process_id=snapshot.process_id,
                    receipt_refs=receipt_refs,
                ),
                recovery_action_type=recovery_action_type or "workflow.recovery.reconcile",
                recovery_params=recovery_params,
                compensation_receipt_digests=tuple(
                    sorted({_evidence_digest(digest) for digest in safeguard_bundle_digests})
                ),
            )
        except Exception:  # noqa: BLE001 - recovery outage keeps the hold in force
            failed = await self._fail(
                snapshot,
                reason="automation_hold_recovery_failed",
                payload={"recovery_receipt_ref": recovery_receipt_ref},
            )
            return CompensationResult(failed, recovery_incomplete=True)
        await self._audit(
            snapshot,
            action_kind="workflow.compensation.recovery",
            suffix=f"recovery:{outcome.disposition.value}",
            payload={
                "disposition": outcome.disposition.value,
                "reason": outcome.reason,
                "attempt_identity_digest": outcome.attempt_identity_digest,
                "effect_claim_digest": outcome.effect_claim_digest,
                "release_receipt_digest": outcome.release_receipt_digest,
                "completion_digest": outcome.completion_digest,
                "recovery_receipt_ref": recovery_receipt_ref,
            },
        )
        if outcome.recovery_incomplete or await self._automation_holds.is_held(
            target_ref=snapshot.target_resource_id
        ):
            failed = await self._fail(
                snapshot,
                reason="automation_hold_release_failed",
                payload={
                    "recovery_receipt_ref": recovery_receipt_ref,
                    "recovery_disposition": outcome.disposition.value,
                    "recovery_reason": outcome.reason,
                },
            )
            return CompensationResult(failed, recovery_incomplete=True)
        if outcome.disposition in {
            RecoveryDisposition.COMPLETED,
            RecoveryDisposition.REPLAYED,
        }:
            terminal = await self._process_store.get(snapshot.process_id)
            if terminal is not None and terminal.status.terminal:
                return CompensationResult(terminal)
        return None

    async def _record_intent(
        self,
        snapshot: ProcessSnapshot,
        *,
        step_id: str,
        compensation_action_type: str,
        compensation_params: Mapping[str, object],
        original_safeguard_bundle_digest: str,
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
                "params": dict(compensation_params),
                "original_safeguard_bundle_digest": original_safeguard_bundle_digest,
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
                    "params": dict(compensation_params),
                    "original_safeguard_bundle_digest": (original_safeguard_bundle_digest),
                },
            ),
        )

    async def _dispatch_intent(
        self,
        snapshot: ProcessSnapshot,
        *,
        step_id: str,
        compensation_action_type: str,
        compensation_params: Mapping[str, object],
        target_resource_id: str,
        context: Mapping[str, str],
    ) -> CompensationResult:
        if self._dispatcher is None:
            failed = await self._fail(snapshot, reason="compensation_dispatcher_not_configured")
            return CompensationResult(failed, recovery_incomplete=True)
        compensation_step = RunbookStep(
            id=f"compensate_{step_id}",
            action_type=compensation_action_type,
            params=dict(compensation_params),
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


def _recovery_receipt_ref(*, process_id: str, receipt_refs: list[str]) -> str:
    canonical = json.dumps(
        {"process_id": process_id, "receipt_refs": receipt_refs},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"workflow-recovery:{hashlib.sha256(canonical.encode()).hexdigest()}"


def _compensation_proposal_digest(*, process_id: str, receipt_refs: list[str]) -> str:
    """Bind the failed compensation proposal so recovery never reuses it."""

    canonical = json.dumps(
        {
            "domain": "workflow-failed-compensation-proposal",
            "process_id": process_id,
            "receipt_refs": sorted(receipt_refs),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def _evidence_digest(value: str) -> str:
    """Normalize a compensation receipt reference to a canonical digest."""

    if value.startswith("sha256:") and len(value) == len("sha256:") + 64:
        return value
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


__all__ = ["CompensationResult", "WorkflowCompensationCoordinator"]
