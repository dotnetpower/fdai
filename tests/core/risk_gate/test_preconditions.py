"""Deterministic ActionType precondition evidence tests."""

from __future__ import annotations

from typing import Any

from fdai.core.risk_gate import EventPreconditionEvaluator
from fdai.shared.contracts.models import (
    Action,
    ActionPrecondition,
    Event,
    OntologyActionType,
    Operation,
    PreconditionKind,
    PromotionGate,
    RollbackKind,
)


def _action_type(*preconditions: ActionPrecondition) -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name="remediate.example",
        version="1.0.0",
        operation=Operation.UPDATE,
        rollback_contract=RollbackKind.PR_REVERT,
        promotion_gate=PromotionGate(
            min_shadow_days=1,
            min_samples=1,
            min_accuracy=0.9,
            max_policy_escapes=0,
        ),
        preconditions=list(preconditions),
    )


async def test_event_evaluator_checks_property_and_tag(
    valid_event: dict[str, Any], valid_action: dict[str, Any]
) -> None:
    event = Event.model_validate(valid_event).model_copy(
        update={
            "payload": {
                "resource": {
                    "props": {"public_access": "enabled"},
                    "tags": {"approved": "true"},
                }
            }
        }
    )
    action_type = _action_type(
        ActionPrecondition(
            kind=PreconditionKind.RESOURCE_PROPERTY_EQUALS,
            property="public_access",
            value="enabled",
        ),
        ActionPrecondition(
            kind=PreconditionKind.RESOURCE_TAG_PRESENT,
            tag="approved",
        ),
    )

    evaluations = await EventPreconditionEvaluator().evaluate(
        event=event,
        action=Action.model_validate(valid_action),
        action_type=action_type,
    )

    assert [(item.condition_index, item.kind, item.satisfied) for item in evaluations] == [
        (0, PreconditionKind.RESOURCE_PROPERTY_EQUALS, True),
        (1, PreconditionKind.RESOURCE_TAG_PRESENT, True),
    ]


async def test_event_evaluator_emits_false_for_known_mismatch(
    valid_event: dict[str, Any], valid_action: dict[str, Any]
) -> None:
    event = Event.model_validate(valid_event).model_copy(
        update={"payload": {"resource": {"props": {"enabled": 1}}}}
    )
    action_type = _action_type(
        ActionPrecondition(
            kind=PreconditionKind.RESOURCE_PROPERTY_EQUALS,
            property="enabled",
            value=True,
        )
    )

    evaluations = await EventPreconditionEvaluator().evaluate(
        event=event,
        action=Action.model_validate(valid_action),
        action_type=action_type,
    )

    assert len(evaluations) == 1
    assert evaluations[0].satisfied is False


async def test_event_evaluator_leaves_stateful_conditions_unresolved(
    valid_event: dict[str, Any], valid_action: dict[str, Any]
) -> None:
    event = Event.model_validate(valid_event).model_copy(
        update={"payload": {"resource": {"props": {}}}}
    )
    action_type = _action_type(ActionPrecondition(kind=PreconditionKind.MAINTENANCE_WINDOW_ACTIVE))

    evaluations = await EventPreconditionEvaluator().evaluate(
        event=event,
        action=Action.model_validate(valid_action),
        action_type=action_type,
    )

    assert evaluations == ()
