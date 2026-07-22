from __future__ import annotations

import itertools
from datetime import UTC, datetime

import pytest

from fdai.core.task_worker import (
    BACKGROUND_READ_ONLY_PROFILE,
    TaskWorkerBudget,
    TaskWorkerRequest,
    attenuate_capabilities,
    isolated_context,
)
from fdai.shared.providers.read_investigation import ReadToolId


def test_attenuation_never_widens_parent_or_profile() -> None:
    universe = ("query_audit", "query_log", "approve_hil", "unknown")
    side_effects = {
        "query_audit": "read",
        "query_log": "read",
        "approve_hil": "approve",
        "unknown": "read",
    }
    subsets = tuple(
        frozenset(item for item, selected in zip(universe, flags, strict=True) if selected)
        for flags in itertools.product((False, True), repeat=len(universe))
    )
    for requested, parent, profile in itertools.product(subsets, repeat=3):
        result = attenuate_capabilities(
            requested=requested,
            parent_visible=parent,
            profile_allowed=profile,
            side_effect_classes=side_effects,
        )
        assert result.allowed_tools <= requested & parent & profile
        assert "approve_hil" not in result.allowed_tools


def test_mutation_and_nested_worker_capabilities_are_denied() -> None:
    requested = frozenset(
        {
            "query_audit",
            "write_memory",
            "create_schedule",
            "spawn_worker",
            "execute_shell",
            "arbitrary_query",
            "approve_action",
        }
    )
    result = attenuate_capabilities(
        requested=requested,
        parent_visible=requested,
        profile_allowed=requested,
        side_effect_classes={tool: "read" for tool in requested},
    )

    assert result.allowed_tools == frozenset({"query_audit"})
    assert result.denied_tools == (
        "approve_action",
        "arbitrary_query",
        "create_schedule",
        "execute_shell",
        "spawn_worker",
        "write_memory",
    )


def test_background_read_only_profile_contains_exactly_five_investigation_tools() -> None:
    assert BACKGROUND_READ_ONLY_PROFILE.profile_id == "background.read-only"
    assert BACKGROUND_READ_ONLY_PROFILE.allowed_tools == frozenset(
        tool.value for tool in ReadToolId
    )
    assert not BACKGROUND_READ_ONLY_PROFILE.allowed_tools.intersection(
        {"submit_action", "approve_action", "execute_shell", "spawn_worker", "arbitrary_query"}
    )


def test_isolated_context_projects_no_parent_history_or_identity() -> None:
    request = TaskWorkerRequest(
        worker_id="worker-1",
        parent_trace_ref="trace-1",
        cancellation_owner="principal-1",
        goal="Compare bounded incident evidence.",
        evidence_refs=("audit:1",),
        constraints=("Cite supplied evidence only.",),
        requested_tools=frozenset({"query_audit"}),
        budget=TaskWorkerBudget(),
        created_at=datetime(2026, 7, 20, tzinfo=UTC),
    )

    context = isolated_context(request)

    assert context.goal == request.goal
    assert not hasattr(context, "cancellation_owner")
    assert not hasattr(context, "history")
    assert not hasattr(context, "principal_id")


def test_worker_depth_is_fixed_to_one() -> None:
    with pytest.raises(ValueError, match="depth 1"):
        TaskWorkerRequest(
            worker_id="worker-1",
            parent_trace_ref="trace-1",
            cancellation_owner="principal-1",
            goal="Investigate.",
            evidence_refs=(),
            constraints=(),
            requested_tools=frozenset(),
            budget=TaskWorkerBudget(),
            created_at=datetime(2026, 7, 20, tzinfo=UTC),
            depth=2,
        )
