"""Private requester/promotion resolution and pre-risk alert Action binding.

All stores are supplied by the Core runtime. This module creates no connection,
executor identity, approval decision or promotion record. The caller MUST hold alert
actions when this binder is absent or raises, before entering the ordinary risk gate.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.detection.alert_noise.execution import (
    ALERT_ACTIONS,
    RESTORE_ACTION,
    AlertExecutionHeld,
    alert_execution_key,
)
from fdai.core.detection.alert_noise.workflow import (
    ALERT_WORKFLOWS,
    AlertWorkflowCoordinator,
    AlertWorkflowResolution,
)
from fdai.core.rbac.roles import Role
from fdai.core.workflow.workflow_runtime import event_id as process_event_id
from fdai.delivery.alert_noise_workflow_readers import (
    MappedAlertRequesterReader as MappedAlertRequesterReader,
)
from fdai.delivery.alert_noise_workflow_readers import (
    StateStoreAlertWorkflowPromotionReader as StateStoreAlertWorkflowPromotionReader,
)
from fdai.shared.contracts.models import (
    Action,
    BlastRadiusScope,
    Event,
    Mode,
    OntologyTypeRef,
    Operation,
    RollbackKind,
)
from fdai.shared.providers.process_runtime import ProcessEvent, ProcessEventKind, ProcessStatus
from fdai.shared.providers.state_store import StateStore


class StateStoreAlertActionBinder:
    """Bind the canonical operator-built Action to its retained plan before risk.

    Only action id, stable idempotency key and rollback reference change. Mode remains
    SHADOW; identity, catalog reference, scope, stop conditions and all other security
    fields remain unchanged. Real risk, Var, recovery and sink checks still apply.
    Reordered ingress without a journaled canonical dispatch is held, never inferred
    from a forged workflow reference; replay may retry only after journal recovery.
    """

    def __init__(
        self,
        *,
        workflows: AlertWorkflowCoordinator,
        registered_actions: Mapping[str, OntologyTypeRef],
        store: StateStore,
        clock: Callable[[], datetime],
    ) -> None:
        self._workflows, self._registered = workflows, registered_actions
        self._store, self._clock = store, clock

    async def bind(self, action: Action, event: Event) -> Action:
        """Return a bound shadow proposal or raise a content-free, audited hold."""
        if action.action_type not in ALERT_ACTIONS:
            return action
        try:
            async with asyncio.timeout(15):
                validated_action = Action.model_validate(action.model_dump(mode="python"))
                validated_event = Event.model_validate(event.model_dump(mode="python"))
                if content_digest(validated_action.model_dump(mode="json")) != content_digest(
                    action.model_dump(mode="json")
                ) or content_digest(validated_event.model_dump(mode="json")) != content_digest(
                    event.model_dump(mode="json")
                ):
                    raise AlertExecutionHeld("alert_binding_input_not_canonical")
                action, event = validated_action, validated_event
                self._require_action(action, event)
                lineage = action.workflow_action
                if lineage is None:
                    raise AlertExecutionHeld("alert_workflow_lineage_missing")
                resolution = await self._workflows.resolve(process_id=lineage.process_id)
                self._require_lineage(action, event, resolution)
                proof = await self._workflows.promotion_admission(resolution)
                self._workflows.require_promotion_current(resolution, proof)
                key = alert_execution_key(action.action_type, resolution.binding.plan_digest)
                bound = Action.model_validate(
                    action.model_copy(
                        update={
                            "action_id": uuid5(NAMESPACE_URL, f"fdai.action://{key}"),
                            "idempotency_key": key,
                            "rollback_ref": action.rollback_ref.model_copy(
                                update={
                                    "reference": resolution.plan.rollback_ref,
                                }
                            ),
                        }
                    ).model_dump(mode="python")
                )
                await self._audit(bound, event, "bound", resolution.binding.plan_digest)
                # Refresh private identity and Process evidence after promotion/audit I/O.
                current = await self._workflows.resolve(process_id=lineage.process_id)
                if current.binding != resolution.binding:
                    raise AlertExecutionHeld("alert_workflow_binding_changed")
                self._require_action(bound, event)
                self._require_lineage(bound, event, current)
                self._workflows.require_promotion_current(current, proof)
                return bound
        except asyncio.CancelledError:
            await self._audit(action, event, "binding_cancelled", None)
            raise
        except Exception as exc:  # noqa: BLE001 - all malformed/unavailable inputs hold before risk
            reason = (
                str(exc) if isinstance(exc, AlertExecutionHeld) else "alert_binding_unavailable"
            )
            await self._audit(action, event, reason, None)
            raise AlertExecutionHeld(reason) from exc

    def _require_action(self, action: Action, event: Event) -> None:
        digest = action.params.get("plan_digest")
        request = event.payload.get("operator_request")
        lineage = action.workflow_action
        if (
            set(action.params) != {"plan_digest"}
            or type(digest) is not str
            or re.fullmatch(r"[a-f0-9]{64}", digest) is None
            or action.mode is not Mode.SHADOW
            or action.operation is not Operation.UPDATE
            or action.rollback_ref.kind is not RollbackKind.PR_REVERT
            or action.blast_radius.count != 1
            or action.blast_radius.scope
            not in {BlastRadiusScope.RESOURCE, BlastRadiusScope.RESOURCE_GROUP}
            or action.action_type_ref is None
            or action.action_type_ref != self._registered.get(action.action_type)
            or lineage is None
            or event.event_type != "operator_request"
            or event.mode is not Mode.SHADOW
            or event.event_id != action.event_id
            or event.resource_ref != action.target_resource_ref
            or event.idempotency_key != lineage.proposal_ref
            or event.event_id
            != uuid5(NAMESPACE_URL, f"fdai.operator-request://{lineage.proposal_ref}")
            or event.payload.get("workflow_action") != lineage.model_dump(mode="json")
            or not isinstance(request, Mapping)
            or request.get("action_type") != action.action_type
            or request.get("params") != action.params
        ):
            raise AlertExecutionHeld("alert_action_binding_mismatch")

    def _require_lineage(
        self,
        action: Action,
        event: Event,
        resolution: AlertWorkflowResolution,
    ) -> None:
        binding, plan, snapshot = resolution.binding, resolution.plan, resolution.snapshot
        lineage = action.workflow_action
        request = event.payload.get("operator_request")
        if (
            lineage is None
            or not isinstance(request, Mapping)
            or binding.mode is not Mode.ENFORCE
            or action.action_type not in {plan.action_type, RESTORE_ACTION}
            or action.params != {"plan_digest": binding.plan_digest[7:]}
            or action.target_resource_ref != binding.target_resource_id
            or action.rollback_ref.reference not in {None, plan.rollback_ref}
            or event.correlation_id != binding.correlation_id
            or request.get("initiator_principal") != binding.requester_principal
            or lineage.proposal_ref
            != f"{binding.process_id}:step:{lineage.step_id}:attempt:{lineage.attempt}"
        ):
            raise AlertExecutionHeld("alert_workflow_lineage_mismatch")
        forward_step = ALERT_WORKFLOWS[plan.action_type][1]
        restore = action.action_type == RESTORE_ACTION
        expected_step = f"compensate_{forward_step}" if restore else forward_step
        if (
            lineage.step_id != expected_step
            or snapshot.current_step != expected_step
            or snapshot.status
            not in (
                {ProcessStatus.COMPENSATING}
                if restore
                else {ProcessStatus.RUNNING, ProcessStatus.WAITING}
            )
        ):
            raise AlertExecutionHeld("alert_workflow_step_mismatch")
        if not restore:
            self._workflows.require_current(resolution)
            if any(
                item.kind is ProcessEventKind.PROCESS_CANCELLATION_REQUESTED
                for item in resolution.events
            ):
                raise AlertExecutionHeld("alert_workflow_cancelled")
        kind = (
            ProcessEventKind.COMPENSATION_DISPATCHED
            if restore
            else ProcessEventKind.ACTION_DISPATCHED
        )
        dispatched = tuple(
            (index, item)
            for index, item in enumerate(resolution.events)
            if item.kind is kind
            and item.step_id == expected_step
            and item.attempt == lineage.attempt
        )
        if len(dispatched) != 1:
            raise AlertExecutionHeld("alert_workflow_dispatch_not_recorded")
        index, dispatch = dispatched[0]
        expected: dict[str, object] = {
            "proposal_ref": lineage.proposal_ref,
            "action_type": action.action_type,
        }
        expected.update(
            {"compensates_step_id": forward_step} if restore else {"params": dict(action.params)}
        )
        suffix = (
            f"compensation:{forward_step}:dispatched"
            if restore
            else f"step:{expected_step}:attempt:{lineage.attempt}:action-dispatched"
        )
        if (
            dispatch.process_id != binding.process_id
            or dispatch.event_id != process_event_id(binding.process_id, suffix)
            or dispatch.idempotency_key != f"{binding.process_id}:{suffix}"
            or dispatch.correlation_id != binding.correlation_id
            or dispatch.payload != expected
        ):
            raise AlertExecutionHeld("alert_workflow_dispatch_mismatch")
        earlier = resolution.events[:index]
        if restore:
            self._require_compensation(earlier, action, forward_step)
        elif not any(
            item.kind is ProcessEventKind.APPROVAL_RECORDED
            and item.step_id == "approve_plan"
            and item.attempt == lineage.attempt
            and item.payload.get("decision") == "approved"
            and item.payload.get("quorum") == 2
            and item.payload.get("no_self_approval") is True
            and item.payload.get("required_role") == Role.OWNER.value
            and item.correlation_id == binding.correlation_id
            for item in earlier
        ):
            raise AlertExecutionHeld("alert_workflow_approval_not_recorded")

    @staticmethod
    def _require_compensation(events: tuple[ProcessEvent, ...], action: Action, step: str) -> None:
        """Verify canonical applied-step and restore intent, without authorizing recovery."""
        lineage = action.workflow_action
        if lineage is None:
            raise AlertExecutionHeld("alert_workflow_lineage_missing")
        intents = tuple(
            item
            for item in events
            if item.kind is ProcessEventKind.COMPENSATION_STARTED
            and item.step_id == lineage.step_id
            and item.attempt == lineage.attempt
        )
        applied = tuple(
            item
            for item in events
            if item.kind is ProcessEventKind.STEP_COMPLETED
            and item.step_id == step
            and item.payload.get("reason") == "action_effect_verified"
        )
        if len(intents) != 1 or len(applied) != 1:
            raise AlertExecutionHeld("alert_compensation_lineage_missing")
        intent, completed = intents[0], applied[0]
        prior_dispatches = tuple(
            item
            for item in events[: events.index(completed)]
            if item.kind is ProcessEventKind.ACTION_DISPATCHED
            and item.step_id == step
            and item.attempt == completed.attempt
            and item.payload.get("params") == action.params
        )
        if (
            len(prior_dispatches) != 1
            or intent.correlation_id != completed.correlation_id
            or completed.correlation_id != prior_dispatches[0].correlation_id
        ):
            raise AlertExecutionHeld("alert_compensation_forward_lineage_missing")
        bundle = completed.payload.get("safeguard_bundle_digest")
        if (
            type(bundle) is not str
            or re.fullmatch(r"sha256:[a-f0-9]{64}", bundle) is None
            or intent.payload.get("compensates_step_id") != step
            or intent.payload.get("action_type") != RESTORE_ACTION
            or intent.payload.get("params") != action.params
            or intent.payload.get("original_safeguard_bundle_digest") != bundle
            or events.index(completed) >= events.index(intent)
        ):
            raise AlertExecutionHeld("alert_compensation_intent_mismatch")

    async def _audit(
        self, action: Action, event: Event, reason: str, plan_digest: str | None
    ) -> None:
        async with asyncio.timeout(5):
            await self._store.append_audit_entry(
                {
                    "actor": "Forseti",
                    "action_kind": "alert_noise.action_binding",
                    "event_id": str(event.event_id),
                    "correlation_id": event.correlation_id,
                    "action_id": str(action.action_id),
                    "action_type": action.action_type,
                    "plan_digest": plan_digest,
                    "reason": reason,
                    "mode": Mode.SHADOW.value,
                    "recorded_at": self._clock().isoformat(),
                    "execution_authority": False,
                }
            )
