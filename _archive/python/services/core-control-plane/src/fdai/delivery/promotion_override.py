"""Thor-owned direct adapter for attributed operator override promotions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol, TypedDict

from fdai.core.executor.lock import ResourceLockManager
from fdai.core.risk_gate import ActionModeRecord, PromotionMetrics
from fdai.delivery.persistence.state_store_action_promotion import PromotionGateStatus
from fdai.shared.contracts.models import Autonomy, Mode, OntologyActionType
from fdai.shared.providers.direct_api import (
    DirectApiExecutor,
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiReceipt,
    DirectApiRequest,
)

OVERRIDE_PROMOTION_ACTION_TYPE = "governance.override-promote-action-type"


class OverridePromotionRegistry(Protocol):
    def record(self, action_type: str) -> ActionModeRecord | None: ...

    def read_model(self, action_type: str) -> dict[str, object]: ...

    def restore(self, action_type: str, record: ActionModeRecord | None) -> None: ...

    async def refresh_for_update(self, action_type: str) -> None: ...

    async def persist(self, action_type: str) -> None: ...

    async def consider_operator_override(
        self,
        *,
        action_type: OntologyActionType,
        gate_status: PromotionGateStatus | str,
        gate_evidence_digest: str,
        approval_receipt_digest: str,
        operator_principal: str,
        reason: str,
        recorded_at: datetime,
        fdai_revision: str | None = None,
        scenario_set_version: str | None = None,
        metrics: PromotionMetrics | None = None,
    ) -> ActionModeRecord: ...


class OverridePromotionArguments(TypedDict):
    action_type_id: str
    target_mode: str
    fdai_revision: str
    scenario_set_version: str
    gate_status: str
    gate_evidence_digest: str
    approval_receipt_digest: str
    operator_principal: str
    justification: str
    stop_condition_proof_digest: str
    rollback_proof_digest: str
    impact_scope_proof_digest: str
    dry_run_proof_digest: str
    logical_target_lock_proof_digest: str
    idempotency_key: str
    audit_intent_proof_digest: str
    capability_kind: str
    workflow_action_type_ids: list[str]


class OperatorOverridePromotionDirectApiExecutor(DirectApiExecutor):
    """Apply one attributed operator override after Var approval is verified."""

    def __init__(
        self,
        *,
        action_types: Mapping[str, OntologyActionType],
        registry: OverridePromotionRegistry,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._action_types = dict(action_types)
        self._registry = registry
        self._clock = clock or (lambda: datetime.now(UTC))
        self._locks = ResourceLockManager()

    async def already_applied_receipt(self, request: DirectApiRequest) -> DirectApiReceipt | None:
        args = override_promotion_arguments(request.arguments)
        target = self._action_types.get(args["action_type_id"])
        if target is None:
            return None
        await self._registry.refresh_for_update(target.name)
        existing = self._registry.record(target.name)
        projection = self._registry.read_model(target.name)
        if (
            existing is None
            or existing.mode is not Mode.ENFORCE
            or existing.promotion_evidence_digest != args["gate_evidence_digest"]
            or existing.fdai_revision != args["fdai_revision"]
            or existing.scenario_set_version != args["scenario_set_version"]
            or projection.get("promotion_kind") != "operator_override"
            or projection.get("approval_receipt_digest") != args["approval_receipt_digest"]
        ):
            return None
        return DirectApiReceipt(
            outcome=DirectApiOutcome.SUCCEEDED,
            receipt_ref=f"override-promotion:{target.name}:{args['approval_receipt_digest']}",
            detail="verified operator override promotion already applied",
        )

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        if request.action_type_name != OVERRIDE_PROMOTION_ACTION_TYPE:
            raise DirectApiPreconditionError("unsupported override-promotion action type")
        if request.mode is Mode.ENFORCE and "enforce" not in request.labels:
            raise DirectApiPromotionError("override promotion requires the enforce label")
        args = override_promotion_arguments(request.arguments)
        _validate_seven_safeguard_arguments(args)
        if args["capability_kind"] == "workflow":
            _validate_workflow_composition(
                action_types=self._action_types,
                action_type_ids=args["workflow_action_type_ids"],
            )
            raise DirectApiPreconditionError("workflow override promotion writer is not registered")
        target = self._action_types.get(args["action_type_id"])
        if target is None:
            raise DirectApiPreconditionError("override target ActionType is not registered")
        _validate_target_override_eligible(target)
        if request.mode is Mode.SHADOW:
            return DirectApiReceipt(
                outcome=DirectApiOutcome.SUCCEEDED,
                receipt_ref=f"shadow:override-promotion:{target.name}",
                detail="shadow: operator override promotion was not applied",
            )
        async with self._locks.acquire(target.name):
            await self._registry.refresh_for_update(target.name)
            prior_record = self._registry.record(target.name)
            if prior_record is not None and prior_record.mode is Mode.ENFORCE:
                receipt = await self.already_applied_receipt(request)
                if receipt is not None:
                    return receipt
                raise DirectApiPreconditionError(
                    "persisted ActionType promotion attribution differs from this override"
                )
            record = await self._registry.consider_operator_override(
                action_type=target,
                gate_status=args["gate_status"],
                gate_evidence_digest=args["gate_evidence_digest"],
                approval_receipt_digest=args["approval_receipt_digest"],
                operator_principal=args["operator_principal"],
                reason=args["justification"],
                recorded_at=self._clock(),
                fdai_revision=args["fdai_revision"],
                scenario_set_version=args["scenario_set_version"],
            )
            if record.mode is not Mode.ENFORCE:
                raise DirectApiPreconditionError("operator override promotion was rejected")
            try:
                await self._registry.persist(target.name)
            except BaseException:
                self._registry.restore(target.name, prior_record)
                raise
        return DirectApiReceipt(
            outcome=DirectApiOutcome.SUCCEEDED,
            receipt_ref=f"override-promotion:{target.name}:{args['approval_receipt_digest']}",
            detail="verified operator override promotion applied",
        )


def override_promotion_arguments(arguments: Mapping[str, object]) -> OverridePromotionArguments:
    required = (
        "action_type_id",
        "target_mode",
        "fdai_revision",
        "scenario_set_version",
        "gate_status",
        "gate_evidence_digest",
        "approval_receipt_digest",
        "operator_principal",
        "justification",
        "stop_condition_proof_digest",
        "rollback_proof_digest",
        "impact_scope_proof_digest",
        "dry_run_proof_digest",
        "logical_target_lock_proof_digest",
        "idempotency_key",
        "audit_intent_proof_digest",
    )
    values: dict[str, str] = {}
    for name in required:
        value = arguments.get(name)
        if not isinstance(value, str) or not value.strip():
            raise DirectApiPreconditionError(f"override promotion argument {name} is required")
        values[name] = value
    if values["target_mode"] != Mode.ENFORCE.value:
        raise DirectApiPreconditionError("override promotion target_mode MUST be enforce")
    values["capability_kind"] = _optional_text_argument(arguments, "capability_kind", "action_type")
    if values["capability_kind"] not in {"action_type", "workflow"}:
        raise DirectApiPreconditionError(
            "override promotion capability_kind MUST be action_type or workflow"
        )
    raw_workflow_ids = arguments.get("workflow_action_type_ids", ())
    if raw_workflow_ids is None:
        raw_workflow_ids = ()
    if not isinstance(raw_workflow_ids, list) or not all(
        isinstance(item, str) and item.strip() for item in raw_workflow_ids
    ):
        raise DirectApiPreconditionError(
            "override promotion workflow_action_type_ids MUST be a string array"
        )
    return {
        "action_type_id": values["action_type_id"],
        "target_mode": values["target_mode"],
        "fdai_revision": values["fdai_revision"],
        "scenario_set_version": values["scenario_set_version"],
        "gate_status": values["gate_status"],
        "gate_evidence_digest": values["gate_evidence_digest"],
        "approval_receipt_digest": values["approval_receipt_digest"],
        "operator_principal": values["operator_principal"],
        "justification": values["justification"],
        "stop_condition_proof_digest": values["stop_condition_proof_digest"],
        "rollback_proof_digest": values["rollback_proof_digest"],
        "impact_scope_proof_digest": values["impact_scope_proof_digest"],
        "dry_run_proof_digest": values["dry_run_proof_digest"],
        "logical_target_lock_proof_digest": values["logical_target_lock_proof_digest"],
        "idempotency_key": values["idempotency_key"],
        "audit_intent_proof_digest": values["audit_intent_proof_digest"],
        "capability_kind": values["capability_kind"],
        "workflow_action_type_ids": [str(item) for item in raw_workflow_ids],
    }


def _optional_text_argument(
    arguments: Mapping[str, object],
    name: str,
    default: str,
) -> str:
    value = arguments.get(name, default)
    if not isinstance(value, str) or not value.strip():
        raise DirectApiPreconditionError(f"override promotion argument {name} is malformed")
    return value


def _validate_seven_safeguard_arguments(args: Mapping[str, object]) -> None:
    digest_fields = (
        "stop_condition_proof_digest",
        "rollback_proof_digest",
        "impact_scope_proof_digest",
        "dry_run_proof_digest",
        "logical_target_lock_proof_digest",
        "audit_intent_proof_digest",
        "gate_evidence_digest",
        "approval_receipt_digest",
    )
    for field in digest_fields:
        value = args[field]
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)
        ):
            raise DirectApiPreconditionError(
                f"override promotion argument {field} MUST be a SHA-256 digest"
            )


def _validate_target_override_eligible(action_type: OntologyActionType) -> None:
    if not action_type.stop_conditions:
        raise DirectApiPreconditionError(
            "override promotion target ActionType MUST declare stop conditions"
        )
    if action_type.blast_radius is None:
        raise DirectApiPreconditionError(
            "override promotion target ActionType MUST declare blast radius"
        )
    if _release_maximum_is_shadow_only(action_type):
        raise DirectApiPreconditionError(
            "override promotion target ActionType release maximum is shadow_only"
        )


def _release_maximum_is_shadow_only(action_type: OntologyActionType) -> bool:
    ceilings = action_type.ceiling_by_tier
    t0 = (
        Autonomy.ENFORCE_AUTO
        if ceilings is None or ceilings.t0 is None
        else ceilings.t0.max_autonomy
    )
    t1 = (
        Autonomy.ENFORCE_HIL
        if ceilings is None or ceilings.t1 is None
        else ceilings.t1.max_autonomy
    )
    t2 = (
        Autonomy.SHADOW_ONLY
        if ceilings is None or ceilings.t2 is None
        else ceilings.t2.max_autonomy
    )
    return t0 is Autonomy.SHADOW_ONLY and t1 is Autonomy.SHADOW_ONLY and t2 is Autonomy.SHADOW_ONLY


def _validate_workflow_composition(
    *,
    action_types: Mapping[str, OntologyActionType],
    action_type_ids: object,
) -> None:
    if not isinstance(action_type_ids, list) or not action_type_ids:
        raise DirectApiPreconditionError(
            "workflow override promotion requires composed ActionType ids"
        )
    missing = sorted(
        action_type for action_type in action_type_ids if action_type not in action_types
    )
    if missing:
        raise DirectApiPreconditionError(
            f"workflow override promotion composes unregistered ActionTypes: {', '.join(missing)}"
        )


__all__ = [
    "OVERRIDE_PROMOTION_ACTION_TYPE",
    "OperatorOverridePromotionDirectApiExecutor",
    "OverridePromotionArguments",
    "OverridePromotionRegistry",
    "override_promotion_arguments",
]
