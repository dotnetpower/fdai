from __future__ import annotations

import pytest

from fdai.delivery.read_api.routes.chat_turn_plan import TurnKind, parse_turn_plan


def _plan(**overrides: object) -> dict[str, object]:
    return {
        "kind": "answer",
        "answer_intent": "open_question",
        "tool_name": None,
        "action_type": None,
        "arguments": {},
        "clarification": None,
        "confidence": 0.91,
        **overrides,
    }


def test_question_plan_has_no_write_authority() -> None:
    plan = parse_turn_plan(_plan())

    assert plan.kind is TurnKind.ANSWER
    assert plan.requires_confirmation is False


def test_action_plan_is_always_a_confirmation_required_draft() -> None:
    plan = parse_turn_plan(
        _plan(
            kind="action_draft",
            action_type="ops.restart-service",
            arguments={"resource_id": "vm-1"},
        )
    )

    assert plan.kind is TurnKind.ACTION_DRAFT
    assert plan.requires_confirmation is True


@pytest.mark.parametrize(
    "raw",
    [
        _plan(kind="answer", action_type="ops.restart-service"),
        _plan(kind="read_tool", tool_name=None),
        _plan(kind="incident_draft", action_type="ops.restart-service"),
        _plan(kind="clarification", clarification=None),
        _plan(kind="answer", arguments={"resource_id": "vm-1"}),
        {**_plan(), "unexpected": True},
    ],
)
def test_invalid_or_overprivileged_model_plans_are_rejected(raw: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="turn plan"):
        parse_turn_plan(raw)
