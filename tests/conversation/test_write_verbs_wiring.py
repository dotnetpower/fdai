"""Coordinator intent-match tests for the W1.1 write set verbs.

Complements ``test_coordinator.py`` (which covers ExploreCatalog) by
proving every write-tool verb matches its expected tool name with the
right argument shape. This is the safety-critical wiring between what
an operator types and which tool the coordinator dispatches - a
miswired verb would silently invoke the wrong tool.
"""

from __future__ import annotations

import pytest

from aiopspilot.core.conversation.coordinator import (
    _VERB_PATTERNS,
    _extract_query,
    _extract_tool_arguments,
)

# Re-import at module level so tests can iterate the shipped list.
_VERBS = _VERB_PATTERNS


def _match(text: str) -> tuple[str, str] | None:
    """Return (tool_name, extracted_rest) for the first pattern that hits."""
    import re

    for pattern, tool_name in _VERBS:
        m = re.match(pattern, text, flags=re.IGNORECASE)
        if m:
            rest = m.group("rest") if "rest" in (m.groupdict() or {}) else ""
            return tool_name, _extract_query(rest)
    return None


# ---------------------------------------------------------------------------
# Every write verb resolves to exactly one tool.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "utterance, expected_tool",
    [
        # simulate_change
        ("simulate_change {}", "simulate_change"),
        ("simulate change resource_type=x", "simulate_change"),
        ("what_if resource_type=object-storage", "simulate_change"),
        # list_hil
        ("list_hil", "list_hil"),
        ("list hil", "list_hil"),
        ("pending_approvals", "list_hil"),
        # approve_hil
        ("approve_hil ik-1 approve", "approve_hil"),
        ("approve hil ik-2 reject", "approve_hil"),
        ("resolve_hil ik-3 approve", "approve_hil"),
        # run_runbook
        ("run_runbook name=db_dr_drill", "run_runbook"),
        ("run runbook prod", "run_runbook"),
        # activate_break_glass
        ("activate_break_glass primary db down", "activate_break_glass"),
        ("break glass primary db down", "activate_break_glass"),
    ],
)
def test_verb_pattern_matches_expected_tool(utterance: str, expected_tool: str) -> None:
    result = _match(utterance)
    assert result is not None, f"no match for {utterance!r}"
    tool_name, _ = result
    assert tool_name == expected_tool


# ---------------------------------------------------------------------------
# simulate_change argument extraction.
# ---------------------------------------------------------------------------


class TestSimulateChangeArgs:
    def test_json_scenario_parsed(self) -> None:
        args = _extract_tool_arguments(
            "simulate_change",
            '{"resource_type":"object-storage","resource_id":"x"}',
        )
        assert args["scenario"] == {
            "resource_type": "object-storage",
            "resource_id": "x",
        }

    def test_kv_scenario_composed(self) -> None:
        args = _extract_tool_arguments(
            "simulate_change",
            "resource_type=object-storage resource_id=x",
        )
        assert args["scenario"] == {
            "resource_type": "object-storage",
            "resource_id": "x",
        }

    def test_signal_type_split_out_of_scenario(self) -> None:
        args = _extract_tool_arguments(
            "simulate_change",
            "resource_type=x resource_id=y signal_type=synthetic.test",
        )
        assert args["signal_type"] == "synthetic.test"
        assert args["scenario"] == {"resource_type": "x", "resource_id": "y"}

    def test_malformed_json_falls_through_to_kv(self) -> None:
        # A stray '{' at the start with broken JSON should not crash;
        # the kv path yields an empty scenario the tool will error on.
        args = _extract_tool_arguments("simulate_change", "{broken")
        assert isinstance(args, dict)


# ---------------------------------------------------------------------------
# approve_hil argument extraction.
# ---------------------------------------------------------------------------


class TestApproveHilArgs:
    def test_positional_shorthand(self) -> None:
        args = _extract_tool_arguments("approve_hil", "ik-1 approve")
        assert args == {"idempotency_key": "ik-1", "decision": "approve"}

    def test_positional_with_justification(self) -> None:
        args = _extract_tool_arguments("approve_hil", "ik-1 reject risk too high")
        assert args["idempotency_key"] == "ik-1"
        assert args["decision"] == "reject"
        assert args["justification"] == "risk too high"

    def test_kv_form_wins_over_positional(self) -> None:
        args = _extract_tool_arguments(
            "approve_hil",
            "idempotency_key=explicit decision=approve",
        )
        assert args == {"idempotency_key": "explicit", "decision": "approve"}


# ---------------------------------------------------------------------------
# list_hil argument extraction.
# ---------------------------------------------------------------------------


class TestListHilArgs:
    def test_limit_coerced_to_int(self) -> None:
        args = _extract_tool_arguments("list_hil", "limit=5")
        assert args == {"limit": 5}

    def test_bad_limit_left_as_string(self) -> None:
        args = _extract_tool_arguments("list_hil", "limit=abc")
        # The tool's own validator returns error - the extractor stays
        # forgiving so a typo does not silently mask into a default.
        assert args["limit"] == "abc"

    def test_empty_query_returns_empty(self) -> None:
        assert _extract_tool_arguments("list_hil", "") == {}


# ---------------------------------------------------------------------------
# run_runbook argument extraction.
# ---------------------------------------------------------------------------


class TestRunRunbookArgs:
    def test_positional_name(self) -> None:
        args = _extract_tool_arguments("run_runbook", "db_dr_drill")
        assert args == {"name": "db_dr_drill"}

    def test_dry_run_coerced_to_bool(self) -> None:
        for token, expected in (
            ("true", True),
            ("false", False),
            ("1", True),
            ("0", False),
            ("yes", True),
            ("no", False),
        ):
            args = _extract_tool_arguments("run_runbook", f"name=x dry_run={token}")
            assert args["dry_run"] is expected, f"token={token!r}"

    def test_params_json_parsed(self) -> None:
        args = _extract_tool_arguments(
            "run_runbook",
            'name=x params_json={"env":"dev"}',
        )
        assert args["params"] == {"env": "dev"}
        assert "params_json" not in args

    def test_bad_params_json_ignored(self) -> None:
        args = _extract_tool_arguments("run_runbook", "name=x params_json=not-json")
        assert "params" not in args


# ---------------------------------------------------------------------------
# activate_break_glass argument extraction.
# ---------------------------------------------------------------------------


class TestActivateBreakGlassArgs:
    def test_reason_from_natural_language_query(self) -> None:
        args = _extract_tool_arguments(
            "activate_break_glass",
            "primary db down, paging owners now for restore",
        )
        assert "primary" in args["reason"]

    def test_kv_reason_wins(self) -> None:
        # kv-token parser splits on whitespace, so a kv-form reason must
        # be a single word; multi-word reasons should use natural-language
        # positional form (test_reason_from_natural_language_query above).
        args = _extract_tool_arguments(
            "activate_break_glass",
            "reason=explicit-reason expiry_seconds=3600",
        )
        assert args["reason"] == "explicit-reason"
        assert args["expiry_seconds"] == 3600

    def test_expiry_coerced_to_int(self) -> None:
        args = _extract_tool_arguments("activate_break_glass", "reason=x expiry_seconds=7200")
        assert args["expiry_seconds"] == 7200

    def test_bad_expiry_left_as_string(self) -> None:
        args = _extract_tool_arguments("activate_break_glass", "reason=x expiry_seconds=abc")
        assert args["expiry_seconds"] == "abc"


# ---------------------------------------------------------------------------
# End-to-end: coordinator dispatches through a real tool stack.
# ---------------------------------------------------------------------------


def test_end_to_end_list_hil_through_coordinator() -> None:
    from aiopspilot.core.conversation import (
        ConversationCoordinator,
        ConversationSession,
        ListHilTool,
        Principal,
        Role,
        ToolResult,
    )
    from aiopspilot.shared.providers.testing import InMemoryHilApprovalRegistry

    reg = InMemoryHilApprovalRegistry()
    tool = ListHilTool(registry=reg)
    coord = ConversationCoordinator(tools=[tool])
    session = ConversationSession(
        session_id="sess-1",
        principal=Principal(id="cli-approver", role=Role.APPROVER),
        channel_id="cli",
    )
    result = coord.handle_turn(session=session, message="list_hil limit=5")
    assert isinstance(result, ToolResult)
    assert result.status == "abstain"  # empty queue
    assert result.data["limit"] == 5


def test_end_to_end_break_glass_through_coordinator() -> None:
    from aiopspilot.core.conversation import (
        ActivateBreakGlassTool,
        AuditWriter,
        ConversationCoordinator,
        ConversationSession,
        Principal,
        Role,
        ToolResult,
    )
    from aiopspilot.shared.providers.testing import (
        InMemoryBreakGlassPager,
        InMemoryStateStore,
    )

    store = InMemoryStateStore()
    tool = ActivateBreakGlassTool(
        pager=InMemoryBreakGlassPager(),
        audit_writer=AuditWriter(audit_store=store),
    )
    coord = ConversationCoordinator(tools=[tool])
    session = ConversationSession(
        session_id="sess-2",
        principal=Principal(id="cli-user", role=Role.READER),
        channel_id="cli",
    )
    result = coord.handle_turn(
        session=session,
        message=("activate_break_glass primary database unreachable please page owners"),
    )
    assert isinstance(result, ToolResult)
    assert result.status == "ok"
    assert "pager_receipt" in result.data
