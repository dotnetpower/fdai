from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.read_investigation import (
    READ_TOOL_SPECS,
    ReadInvestigationBudget,
    ReadInvestigationRequest,
    plan_read_investigation,
)
from fdai.shared.providers.read_investigation import (
    ReadInvestigationIntent,
    ReadToolId,
    ResourceSelector,
)


def _request(
    intent: ReadInvestigationIntent,
    *,
    max_tool_calls: int = 5,
    requested_evidence: tuple[ReadToolId, ...] = (),
    explicit_deep: bool = False,
) -> ReadInvestigationRequest:
    return ReadInvestigationRequest(
        requester_ref="principal:one",
        conversation_ref="conversation:one",
        correlation_ref="correlation:one",
        intent=intent,
        selector=ResourceSelector(name="vm-01", scope_ref="scope:allowed"),
        lookback_seconds=3_600,
        requested_evidence=requested_evidence,
        budget=ReadInvestigationBudget(max_tool_calls=max_tool_calls),
        idempotency_key="request:one",
        created_at=datetime(2026, 7, 22, tzinfo=UTC),
        explicit_deep=explicit_deep,
    )


def test_catalog_registers_all_bounded_reader_tools() -> None:
    assert {spec.tool_id for spec in READ_TOOL_SPECS} == set(ReadToolId)
    assert all(spec.required_role == "Reader" for spec in READ_TOOL_SPECS)
    assert all(spec.side_effect_class == "read" for spec in READ_TOOL_SPECS)
    assert all(spec.query_template_owner == "server" for spec in READ_TOOL_SPECS)


def test_planner_resolves_before_any_history_query() -> None:
    plan = plan_read_investigation(_request(ReadInvestigationIntent.CHANGE_ATTRIBUTION))
    assert plan.steps[0].tool_id is ReadToolId.RESOLVE_RESOURCE
    assert [step.tool_id for step in plan.evidence_steps] == [
        ReadToolId.QUERY_RESOURCE_ACTIVITY,
        ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS,
        ReadToolId.QUERY_RESOURCE_HEALTH,
    ]


def test_planner_never_widens_budget_or_accepts_client_resolution() -> None:
    plan = plan_read_investigation(
        _request(
            ReadInvestigationIntent.RESOURCE_STATE,
            requested_evidence=(ReadToolId.GET_RESOURCE_STATE,),
        )
    )
    assert all(step.timeout_seconds <= plan.request.budget.max_wall_seconds for step in plan.steps)
    assert all(step.max_results <= plan.request.budget.max_results for step in plan.steps)

    with pytest.raises(ValueError, match="server-owned"):
        _request(
            ReadInvestigationIntent.RESOURCE_STATE,
            requested_evidence=(ReadToolId.RESOLVE_RESOURCE,),
        )
    with pytest.raises(ValueError, match="max_tool_calls"):
        plan_read_investigation(
            _request(ReadInvestigationIntent.CHANGE_ATTRIBUTION, max_tool_calls=2)
        )


def test_explicit_deep_plan_is_still_bounded_to_the_vm_tools() -> None:
    plan = plan_read_investigation(
        _request(ReadInvestigationIntent.RESOURCE_STATE, explicit_deep=True)
    )
    assert tuple(step.tool_id for step in plan.steps) == (
        ReadToolId.RESOLVE_RESOURCE,
        ReadToolId.GET_RESOURCE_STATE,
        ReadToolId.QUERY_RESOURCE_ACTIVITY,
        ReadToolId.QUERY_RESOURCE_HEALTH,
        ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS,
    )


@pytest.mark.parametrize(
    ("intent", "tool_id"),
    [
        (ReadInvestigationIntent.NETWORK_SECURITY, ReadToolId.QUERY_NETWORK_SECURITY),
        (ReadInvestigationIntent.NETWORK_PEERING, ReadToolId.QUERY_NETWORK_PEERINGS),
    ],
)
def test_network_intents_plan_one_bounded_tool(
    intent: ReadInvestigationIntent,
    tool_id: ReadToolId,
) -> None:
    plan = plan_read_investigation(_request(intent, explicit_deep=True))
    assert tuple(step.tool_id for step in plan.steps) == (
        ReadToolId.RESOLVE_RESOURCE,
        tool_id,
    )


def test_request_budget_can_represent_resource_ambiguity() -> None:
    with pytest.raises(ValueError, match="max_results"):
        ReadInvestigationBudget(max_results=1)
