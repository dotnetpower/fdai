"""Fixed-owner recovery callbacks using a fresh exact inverse and independent observation.

The callbacks propose and verify; only the existing Thor dispatch callback can
send an inverse. A pending proposal is never a successful Vidar rollback.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from fdai_service_contracts.human_access_execution import human_access_record_digest
from fdai_service_contracts.human_access_workflow import HumanAccessHandoff, HumanAccessWorkNotice

from fdai.core.executor.action_builder import ActionBuilder
from fdai.shared.contracts.models import Action, Event, Mode, RollbackKind, RollbackRef

if TYPE_CHECKING:
    from fdai.runtime.human_access_workflow import HumanAccessWorkflowRuntime

RECOVERY_SCRIPT_REFERENCE = "human-access-reviewed-inverse:v1"


async def judge_inverse(
    runtime: HumanAccessWorkflowRuntime, handoff: HumanAccessHandoff
) -> HumanAccessHandoff:
    """Forseti judges retained failure evidence for a separately reviewed inverse."""
    original, observed = await runtime._observation(handoff)
    recovery = runtime.recovery
    if recovery is None or original.inverse is not None:
        raise ValueError("human access non-recursive recovery source is unavailable")
    case = await runtime.builder.cases.get_case(original.action().params["case_id"])
    if case.state.value != "degraded" or case.iam_recovery_preparation is not None:
        raise ValueError("human access recovery requires an independently held original case")
    await runtime._close(handoff, original, observed)
    binding = await recovery.binding(original)
    action_type = (
        "ops.apply-human-access"
        if binding.original_before_membership
        else "ops.revoke-human-access"
    )
    await runtime.current.source.promotions.refresh(action_type)
    promotion = await runtime.store.read_state("action_promotion:" + action_type)
    if promotion is None:
        raise ValueError("human access inverse promotion source is missing")
    identity = human_access_record_digest(
        {
            "original": original.digest,
            "binding": binding.model_dump(mode="json"),
            "case": case.to_dict(),
            "promotion": dict(promotion),
        }
    )
    request_id = uuid5(NAMESPACE_URL, "fdai:human-access-inverse:" + identity)
    now = runtime.clock()
    key = "human_assignment:execution-request:" + str(request_id)
    candidate_notice = HumanAccessWorkNotice(
        request_id=request_id,
        operation="request",
        case_id=case.case_id,
        expected_revision=case.revision,
        observed_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    await runtime.store.write_state_with_audit_if_absent(
        key,
        candidate_notice.model_dump(mode="json"),
        {
            "actor": "Forseti",
            "action_kind": "human_access.inverse.judged",
            "original_material": original.digest,
            "request_id": str(request_id),
            "mode": "shadow",
        },
    )
    notice = HumanAccessWorkNotice.model_validate(await runtime.store.read_state(key))
    runtime._fresh(notice)
    event = Event(
        schema_version="1.0.0",
        event_id=request_id,
        idempotency_key="human-access-inverse:" + str(request_id),
        correlation_id=str(request_id),
        source="human-assignment",
        event_type="operator.requested",
        resource_ref=original.action().target_resource_ref,
        detected_at=notice.observed_at,
        ingested_at=now,
        mode=Mode.SHADOW,
        payload={
            "operator_request": {
                "action_type": action_type,
                "initiator_principal": original.requester_ref,
                "params": {
                    "case_id": case.case_id,
                    "expected_revision": case.revision,
                    "recovery_of": str(original.action().action_id),
                },
            }
        },
    )
    builder = ActionBuilder(
        runtime.action_builder.action_types_by_name,
        runtime.action_builder.ontology_release,
        lambda: notice.observed_at,
    )
    candidate, rule = builder.build_from_operator_request(event=event)
    value = candidate.model_dump(mode="json")
    value.update(
        mode=runtime.current.source.promotions.mode_of(action_type).value,
        executor_identity_ref="identity/human-access",
        rollback_ref=RollbackRef(
            kind=RollbackKind.SCRIPTED, reference=RECOVERY_SCRIPT_REFERENCE
        ).model_dump(mode="json"),
    )
    action = Action.model_validate(value)
    await runtime._risk(action, rule)
    material = await recovery.build(
        action=action, original=original, promotion=promotion, at=notice.observed_at
    )
    await runtime.store.write_state_with_audit_if_absent(
        "human_assignment:execution-rule:" + str(action.action_id),
        rule.model_dump(mode="json"),
        {"actor": "Forseti", "action_kind": "human_access.inverse.rule.retained", "mode": "shadow"},
    )
    return HumanAccessHandoff(
        notice=notice,
        stage="recovery_judged",
        action_id=action.action_id,
        material_digest=material.digest,
    )


async def propose_inverse(
    runtime: HumanAccessWorkflowRuntime, handoff: HumanAccessHandoff
) -> HumanAccessHandoff:
    """Vidar proposes the judged inverse without dispatching or declaring success."""
    material = await runtime._material(handoff)
    if material.inverse is None or runtime.recovery is None:
        raise ValueError("human access recovery proposal is not an original inverse")
    await runtime.current.source.check(material)
    return HumanAccessHandoff(
        notice=handoff.notice,
        stage="recovery_proposed",
        action_id=handoff.action_id,
        material_digest=handoff.material_digest,
    )


async def finish_inverse(
    runtime: HumanAccessWorkflowRuntime, handoff: HumanAccessHandoff
) -> HumanAccessHandoff:
    """Vidar reports rollback only after exact independent inverse effect and Core readback."""
    material, observed = await runtime._effect(handoff)
    case = await runtime.builder.cases.get_case(material.action().params["case_id"])
    if (
        material.inverse is None
        or case.iam_recovery_effect is None
        or case.iam_recovery_effect.receipt_ref != handoff.evidence_ref
    ):
        raise ValueError("human access recovery has no independently recorded inverse effect")
    await runtime._close(handoff, material, observed)
    return HumanAccessHandoff(
        notice=handoff.notice,
        stage="recovery_recorded",
        action_id=handoff.action_id,
        material_digest=handoff.material_digest,
        evidence_ref=handoff.evidence_ref,
    )


__all__ = ["RECOVERY_SCRIPT_REFERENCE", "judge_inverse", "propose_inverse", "finish_inverse"]
