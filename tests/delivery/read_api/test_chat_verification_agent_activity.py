from __future__ import annotations

from collections.abc import Sequence

import pytest

from fdai.delivery.read_api.routes.chat_verification import (
    _agent_activity_lines,
    verify_answer,
)


def _evidence(
    *,
    audit: Sequence[object] | None = None,
    involved: Sequence[object] | None = None,
    grounded: bool = False,
) -> dict[str, object]:
    return {
        "status": "matched",
        "selected_incident": {
            "correlation_id": "corr-1",
            "title": "Memory pressure",
            "status": "triaging",
            "last_updated_at": "2026-07-22T00:00:00Z",
            "involved_agents": involved or [],
        },
        "audit_evidence": audit or [],
        "grounded_hypotheses": (
            [{"cause": "Memory leak", "citations": [{"kind": "metric", "ref": "memory"}]}]
            if grounded
            else []
        ),
    }


@pytest.mark.parametrize(
    ("korean", "expected"),
    [
        (False, "- Forseti: rca.hypothesis at 2026-07-22T00:00:00Z"),
        (True, "- Forseti: 2026-07-22T00:00:00Z에 rca.hypothesis 기록"),
    ],
)
def test_renders_recorded_audit_activity(korean: bool, expected: str) -> None:
    lines = _agent_activity_lines(
        _evidence(
            audit=[
                {
                    "agent": "Forseti",
                    "action_kind": "rca.hypothesis",
                    "recorded_at": "2026-07-22T00:00:00Z",
                }
            ]
        ),
        korean=korean,
    )

    assert lines == [expected]


def test_keeps_one_recorded_line_per_agent() -> None:
    lines = _agent_activity_lines(
        _evidence(
            audit=[
                {"agent": "Forseti", "action_kind": "first", "recorded_at": "t1"},
                {"agent": "Forseti", "action_kind": "second", "recorded_at": "t2"},
            ]
        ),
        korean=False,
    )

    assert lines == ["- Forseti: first at t1"]


def test_caps_recorded_activity_at_eight_agents() -> None:
    audit = [
        {"agent": f"Agent-{index}", "action_kind": "observed", "recorded_at": "now"}
        for index in range(10)
    ]

    assert len(_agent_activity_lines(_evidence(audit=audit), korean=False)) == 8


def test_ignores_malformed_recorded_agents() -> None:
    lines = _agent_activity_lines(
        _evidence(
            audit=[
                {"agent": None, "action_kind": "ignored"},
                {"agent": "", "action_kind": "ignored"},
                {"agent": "Var", "action_kind": "hil.pending", "recorded_at": "now"},
            ]
        ),
        korean=False,
    )

    assert lines == ["- Var: hil.pending at now"]


def test_normalizes_and_deduplicates_involved_agent_fallback() -> None:
    lines = _agent_activity_lines(
        _evidence(involved=[" Var ", "", None, "Var", "Forseti"]),
        korean=False,
    )

    assert [line.split(":", 1)[0] for line in lines] == ["- Var", "- Forseti"]


def test_fallback_does_not_infer_current_task_absence() -> None:
    lines = _agent_activity_lines(_evidence(involved=["Var"]), korean=False)

    assert "no current task" not in lines[0].lower()
    assert "no agent-specific audit activity is recorded" in lines[0].lower()


def test_empty_activity_uses_explicit_absence_message() -> None:
    result = verify_answer("draft", {"_operational_evidence": _evidence()}, locale="en")

    assert "No agent-specific activity is recorded" in result.answer


@pytest.mark.parametrize("grounded", [False, True])
def test_korean_terminal_answer_includes_incident_status(grounded: bool) -> None:
    result = verify_answer(
        "초안",
        {"_operational_evidence": _evidence(grounded=grounded)},
        locale="ko",
    )

    assert "triaging" in result.answer


def test_terminal_heading_describes_recorded_not_current_activity() -> None:
    result = verify_answer(
        "draft",
        {
            "_operational_evidence": _evidence(
                audit=[{"agent": "Var", "action_kind": "hil.pending", "recorded_at": "then"}]
            )
        },
        locale="en",
    )

    assert "Recorded agent activity" in result.answer
    assert "Current recorded agent activity" not in result.answer
