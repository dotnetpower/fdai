"""Deterministic validation of claims added by grounded answer narration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.conversation import (
    ConversationCoordinator,
    ConversationSession,
    Principal,
    Role,
    ToolResult,
    default_tool_schemas,
)
from fdai.core.conversation.grounded_answer_validation import validate_grounded_answer
from fdai.core.conversation.tools import SideEffectClass


class _ResultTool:
    name = "explore_catalog"
    description = "Return one synthetic grounded result."
    rbac_floor = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, result: ToolResult) -> None:
        self.result = result

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        return self.result


class _AnswerNarrator:
    def __init__(self, answer: str) -> None:
        self.answer = answer

    def translate(self, **kwargs: Any) -> None:
        return None

    def render_answer(self, **kwargs: Any) -> str:
        return self.answer


def _run(answer: str, result: ToolResult) -> ToolResult:
    coordinator = ConversationCoordinator(
        tools=(_ResultTool(result),),
        narrator=_AnswerNarrator(answer),
        narrator_tool_schemas=default_tool_schemas(),
    )
    session = ConversationSession(
        session_id="session-claims",
        principal=Principal(id="principal-example", role=Role.READER),
        channel_id="cli",
    )
    rendered = coordinator.handle_turn(session=session, message="explore_catalog storage")
    assert isinstance(rendered, ToolResult)
    return rendered


def test_unsupported_numeric_claim_falls_back_to_tool_preview() -> None:
    result = ToolResult(
        status="ok",
        data={"matched": 2},
        preview="found 2 rules",
        evidence_refs=("rule-example",),
    )

    rendered = _run("Found 9 rules. [rule-example]", result)

    assert rendered.preview == "found 2 rules"


def test_freshness_claim_without_authoritative_timestamp_falls_back() -> None:
    result = ToolResult(
        status="ok",
        data={"state": "healthy"},
        preview="state healthy",
        evidence_refs=("status-example",),
    )

    rendered = _run("The current state is healthy. [status-example]", result)

    assert rendered.preview == "state healthy"


def test_freshness_claim_with_exact_authoritative_timestamp_is_accepted() -> None:
    timestamp = "2026-07-23T08:00:00Z"
    result = ToolResult(
        status="ok",
        data={"state": "healthy", "observed_at": timestamp},
        preview=f"state healthy at {timestamp}",
        evidence_refs=("status-example",),
    )

    rendered = _run(
        f"The current state is healthy as of {timestamp}. [status-example]",
        result,
    )

    assert rendered.preview.startswith("The current state is healthy as of")


def test_markdown_numbered_list_ordinals_are_not_numeric_claims() -> None:
    result = ToolResult(status="ok", preview="steps available")

    validation = validate_grounded_answer("1. Inspect\n2. Verify", result)

    assert validation.valid is True


def test_unsupported_percentage_claim_is_rejected() -> None:
    result = ToolResult(status="ok", data={"success_rate": "95%"}, preview="success 95%")

    validation = validate_grounded_answer("Success is 99%.", result)

    assert validation.valid is False
    assert validation.reason_code == "unsupported_numeric_value"


def test_mismatched_timestamp_claim_is_rejected() -> None:
    result = ToolResult(
        status="ok",
        data={"observed_at": "2026-07-23T08:00:00Z"},
        preview="observation available",
    )

    validation = validate_grounded_answer(
        "Current as of 2026-07-23T09:00:00Z.",
        result,
    )

    assert validation.valid is False
    assert validation.reason_code == "unsupported_timestamp"


def test_invented_rule_identifier_is_rejected() -> None:
    result = ToolResult(
        status="ok",
        data={"rule_id": "rule-example"},
        preview="rule-example matched",
        evidence_refs=("rule-example",),
    )

    validation = validate_grounded_answer(
        "rule-example matched, and rule-invented also applies. [rule-example]",
        result,
    )

    assert validation.valid is False
    assert validation.reason_code == "unsupported_identifier"


def test_invented_action_type_identifier_is_rejected() -> None:
    result = ToolResult(
        status="ok",
        data={"action_type": "ops.restart-service"},
        preview="ops.restart-service is available",
    )

    validation = validate_grounded_answer(
        "Use ops.restart-service or ops.delete-storage.",
        result,
    )

    assert validation.valid is False
    assert validation.reason_code == "unsupported_identifier"


def test_supported_identifier_subset_is_accepted() -> None:
    result = ToolResult(
        status="ok",
        data={"rule_ids": ["rule-one", "rule-two"]},
        preview="two rules matched",
    )

    validation = validate_grounded_answer("rule-one matched.", result)

    assert validation.valid is True


def test_ordinary_resource_alias_is_outside_canonical_identifier_check() -> None:
    result = ToolResult(status="ok", data={"resource": "vm-example"}, preview="VM found")

    validation = validate_grounded_answer("vm-example was found.", result)

    assert validation.valid is True
