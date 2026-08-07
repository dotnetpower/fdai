"""Focused contracts for application-owned conversation response completion."""

from __future__ import annotations

from fdai.delivery.operator_api.application.conversation.response_completion import (
    metering_correlation_id,
    turn_metadata,
    uses_evidence_fast_path,
)


def test_metering_correlation_is_stable_and_opaque() -> None:
    first = metering_correlation_id("principal-a", "conversation-a")

    assert first == metering_correlation_id("principal-a", "conversation-a")
    assert first.startswith("chat-")
    assert "principal-a" not in first
    assert "conversation-a" not in first


def test_turn_metadata_keeps_web_and_planning_evidence_server_side() -> None:
    metadata = turn_metadata(
        model="narrator-mini",
        view_context={"_web_evidence": {"status": "completed"}, "ignored": "value"},
        answer_planning={"status": "completed"},
    )

    assert metadata == {
        "model": "narrator-mini",
        "web_evidence": {"status": "completed"},
        "answer_planning": {"status": "completed"},
    }


def test_fast_path_accepts_verified_server_evidence_only() -> None:
    assert uses_evidence_fast_path({"_tool_evidence": {"tool": "query_inventory"}})
    assert not uses_evidence_fast_path({"_tool_evidence": {"tool": "unknown_tool"}})
