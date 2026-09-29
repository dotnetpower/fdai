"""Full-authority development parks and category revalidation for the ControlLoop.

Only the Owner's own operator request inside the selected profile reaches these stages. A
category-only denial parks with an Owner-only block; the HIL coordinator later asks the ControlLoop
to rerun the full current evaluation before an admitted Owner self-approval dispatches.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.development_approval import development_owner_only
from pydantic import ValidationError

from fdai.core.control_loop._notification_helpers import request_hil_approval
from fdai.core.control_loop.development_request import prepare_development_park
from fdai.core.hil_resume import HilResumeCoordinator
from fdai.core.hil_resume.development import CategoryRevalidation, park_block
from fdai.core.risk_gate.category_denial import development_category_denial
from fdai.core.risk_gate.evaluator import UnifiedRiskDecision
from fdai.core.risk_gate.risk_table import RiskTable
from fdai.shared.contracts.models import (
    Action,
    Event,
    FullAuthorityDevelopmentProfile,
    OntologyActionType,
    Rule,
    Tier,
)
from fdai.shared.providers.development_authority import DevelopmentAuthorityBindingSource
from fdai.shared.providers.execution_authorization import (
    ExecutionAuthorizationEvaluator,
    ExecutionAuthorizationRequest,
    ExecutionAuthorizationResult,
    ExecutionAuthorizationStatus,
)
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.target_revision import TargetRevisionReader

_LOGGER = logging.getLogger("fdai.core.control_loop.orchestrator")


class ControlLoopDevelopmentMixin:
    """Park the Owner's development requests and revalidate an admitted category park."""

    _action_types_by_name: Mapping[str, OntologyActionType]
    _audit_store: StateStore
    _clock: Callable[[], datetime]
    _development_binding_source: DevelopmentAuthorityBindingSource | None
    _development_profile: FullAuthorityDevelopmentProfile | None
    _development_revision_reader: TargetRevisionReader | None
    _execution_authorization_evaluator: ExecutionAuthorizationEvaluator | None
    _hil_resume_coordinator: HilResumeCoordinator | None
    _inventory_context_provider: Callable[[str], Awaitable[Mapping[str, Any] | None]] | None
    _risk_table: RiskTable | None

    async def _evaluate_and_audit(
        self, *, event: Event, action: Action, rule: Rule, tier: Tier = Tier.T0
    ) -> UnifiedRiskDecision | None: ...

    async def _development_park_block(
        self,
        *,
        action: Action,
        authorization: ExecutionAuthorizationResult | None,
        unified: UnifiedRiskDecision,
        initiator: object,
    ) -> dict[str, Any] | None:
        """Return the development park block for the Owner's own exact action, if eligible."""
        return await prepare_development_park(
            profile=self._development_profile,
            bindings=self._development_binding_source,
            revisions=self._development_revision_reader,
            initiator=initiator,
            action=action,
            action_type=self._action_types_by_name.get(action.action_type),
            authorization=authorization,
            unified=unified,
        )

    async def _park_development_category_denial(
        self,
        *,
        event: Event,
        action: Action,
        rule: Rule,
        authorization: ExecutionAuthorizationResult | None,
        unified: UnifiedRiskDecision,
        initiator: object,
        correlation_id: str,
    ) -> bool:
        """Park a category-only denial of the Owner's own request as Owner-only.

        Returns ``False``, keeping the ordinary denial, outside a current profile and scope, for
        any other initiator or denial reason, for a workflow step, or when development evidence
        is missing.
        """
        table = self._risk_table
        action_type = self._action_types_by_name.get(action.action_type)
        if (
            self._hil_resume_coordinator is None
            or self._development_profile is None
            or table is None
            or action_type is None
            or action.workflow_action is not None
            or not isinstance(initiator, str)
        ):
            return False
        category = development_category_denial(unified, table=table, action_type=action_type)
        if category is None:
            return False
        parked_action = action.model_copy(update={"mode": unified.gate.effective_mode})
        block = await prepare_development_park(
            profile=self._development_profile,
            bindings=self._development_binding_source,
            revisions=self._development_revision_reader,
            initiator=initiator,
            action=parked_action,
            action_type=action_type,
            authorization=authorization,
            unified=unified,
            category_denial=category,
            evaluation_event=event,
            now=self._clock(),
        )
        if block is None:
            return False
        await self._audit_store.append_audit_entry(
            {
                "event_id": str(event.event_id),
                "correlation_id": correlation_id,
                "idempotency_key": event.idempotency_key,
                "actor": "fdai.core.control_loop",
                "producer_principal": "Forseti",
                "action_kind": "risk_gate.development_category_park",
                "mode": parked_action.mode.value,
                "action_id": str(parked_action.action_id),
                "action_type_id": parked_action.action_type,
                "original_decision": unified.decision,
                "decision": "hil",
                "original_quorum": block["original_quorum"],
                "effective_quorum": 1,
                "owner_self_approval_only": True,
                "category_denial": category.as_audit_dict(),
                "profile_digest": block["profile_digest"],
                "block_digest": block["block_digest"],
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            }
        )
        await request_hil_approval(
            self._hil_resume_coordinator,
            _LOGGER,
            action=parked_action,
            rule=rule,
            correlation_id=correlation_id,
            submitter_oid=initiator,
            development_authority=block,
        )
        return True

    async def revalidate_category_park(
        self,
        parked: Mapping[str, Any],
        *,
        action: Action,
        rule: Rule,
    ) -> CategoryRevalidation:
        """Rerun the full current evaluation that parked one category-only denial.

        The current inventory snapshot, execution authorization, kill switch, degradation,
        promotion state, evidence conflicts, preconditions, live probe, and risk table must still
        yield the same category-only denial in the same mode, and the target revision must be
        unchanged. Anything else refuses the admitted self-approval.
        """
        block = park_block(parked)
        table = self._risk_table
        action_type = self._action_types_by_name.get(action.action_type)
        revisions = self._development_revision_reader
        if block is None or not development_owner_only(parked):
            return CategoryRevalidation(False, "park_block_invalid")
        if table is None or action_type is None or revisions is None:
            return CategoryRevalidation(False, "category_revalidation_unwired")
        try:
            event = Event.model_validate(block["evaluation_event"])
        except (KeyError, TypeError, ValueError, ValidationError):
            return CategoryRevalidation(False, "evaluation_event_invalid")
        if event.event_id != action.event_id:
            return CategoryRevalidation(False, "evaluation_event_invalid")
        current = await self._current_category_event(event)
        if current is None:
            return CategoryRevalidation(False, "current_inventory_unavailable")
        authorization = await self._current_category_authorization(event=current, action=action)
        detail: dict[str, Any] = {
            "execution_authorization": (
                authorization.status.value if authorization is not None else None
            ),
        }
        if (
            authorization is None
            or authorization.status is not ExecutionAuthorizationStatus.AUTHORIZED
            or authorization.executor_identity_ref != action.executor_identity_ref
        ):
            return CategoryRevalidation(False, "execution_authorization_changed", detail)
        unified = await self._evaluate_and_audit(event=current, action=action, rule=rule)
        if unified is None:
            return CategoryRevalidation(False, "risk_evaluation_unavailable", detail)
        category = development_category_denial(unified, table=table, action_type=action_type)
        detail["decision"] = unified.decision
        detail["category_denial"] = category.as_audit_dict() if category is not None else None
        recorded = block.get("category_denial")
        # The residual requirement is the recorded original quorum, so it must be unchanged too.
        if (
            category is None
            or not isinstance(recorded, Mapping)
            or category.as_audit_dict() != dict(recorded)
        ):
            return CategoryRevalidation(False, "category_denial_changed", detail)
        if unified.gate.effective_mode is not action.mode:
            return CategoryRevalidation(False, "promotion_mode_changed", detail)
        try:
            revision = await revisions.read_revision(action.target_resource_ref)
        except Exception:  # noqa: BLE001 - an unreadable target revision never dispatches
            revision = None
        if revision is None or revision != block["target_revision"]:
            return CategoryRevalidation(False, "target_revision_drift", detail)
        return CategoryRevalidation(True, "category_revalidated", detail)

    async def _current_category_event(self, event: Event) -> Event | None:
        """Refresh the evaluated resource snapshot, or ``None`` when inventory cannot be read."""
        provider = self._inventory_context_provider
        if provider is None or not event.resource_ref:
            return event
        try:
            resource = await provider(event.resource_ref)
        except Exception:  # noqa: BLE001 - unreadable current inventory refuses the approval
            _LOGGER.warning(
                "development_category_inventory_unavailable",
                extra={"event_id": str(event.event_id)},
                exc_info=True,
            )
            return None
        if resource is None:
            return event
        return event.model_copy(update={"payload": {**event.payload, "resource": dict(resource)}})

    async def _current_category_authorization(
        self,
        *,
        event: Event,
        action: Action,
    ) -> ExecutionAuthorizationResult | None:
        """Re-read execution authorization without submitting any access-grant request."""
        evaluator = self._execution_authorization_evaluator
        if evaluator is None:
            return None
        try:
            return await evaluator.evaluate(
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
                "development_category_authorization_unavailable",
                extra={"action_type": action.action_type},
                exc_info=True,
            )
            return None


__all__ = ["ControlLoopDevelopmentMixin"]
