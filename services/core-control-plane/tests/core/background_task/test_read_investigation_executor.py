"""Focused tests for typed background read execution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fdai.core.background_task import (
    BackgroundReadInvestigationSpec,
    BackgroundTask,
    BackgroundTaskBudget,
    BackgroundTaskKind,
    BackgroundTaskOrigin,
    ReadInvestigationBackgroundExecutor,
)
from fdai.core.read_investigation import ReadInvestigationOutcome
from fdai.shared.providers.read_investigation import ReadInvestigationIntent, ReadToolId
from fdai.shared.providers.tool import ToolCallOutcome, ToolCallReceipt

NOW = datetime(2026, 8, 23, tzinfo=UTC)


class _Service:
    def __init__(self) -> None:
        self.plans: list[object] = []

    async def execute(self, plan: object, *, progress_observer: object) -> object:
        self.plans.append(plan)
        for step in plan.steps:  # type: ignore[attr-defined]
            await progress_observer(  # type: ignore[operator]
                SimpleNamespace(value=f"step.{step.tool_id.value}")
            )
        return SimpleNamespace(
            outcome=ReadInvestigationOutcome.UNAVAILABLE,
            evidence=(),
            evidence_refs=(),
            receipts=(
                ToolCallReceipt(
                    ToolCallOutcome.SUCCEEDED,
                    "receipt-one",
                    tool_id="resolve_resource",
                ),
            ),
            started_at=NOW,
            finished_at=NOW + timedelta(seconds=1),
        )


def _task(intent: ReadInvestigationIntent | None) -> BackgroundTask:
    return BackgroundTask(
        task_id="background-one",
        owner_principal_id="principal-one",
        origin=BackgroundTaskOrigin("conversation-one", "operator-api", "principal-one"),
        kind=BackgroundTaskKind.READ_ONLY_INVESTIGATION,
        prompt="Inspect",
        context_digest="sha256:" + "a" * 64,
        capability_profile_id="background.read-only",
        budget=BackgroundTaskBudget(),
        correlation_id="correlation-one",
        idempotency_key="idempotency-one",
        created_at=NOW,
        retention_until=NOW + timedelta(days=30),
        investigation=(
            BackgroundReadInvestigationSpec(
                intent=intent,
                resource_name="service-one",
                scope_ref="scope:configured-reader",
                lookback_seconds=3_600,
            )
            if intent is not None
            else None
        ),
    )


@pytest.mark.parametrize(
    ("intent", "expected_tool"),
    [
        (ReadInvestigationIntent.RESOURCE_STATE, ReadToolId.GET_RESOURCE_STATE),
        (ReadInvestigationIntent.CHANGE_ATTRIBUTION, ReadToolId.QUERY_RESOURCE_ACTIVITY),
        (
            ReadInvestigationIntent.RESOURCE_CHANGE_HISTORY,
            ReadToolId.QUERY_RESOURCE_ACTIVITY,
        ),
        (ReadInvestigationIntent.PLATFORM_HEALTH, ReadToolId.QUERY_RESOURCE_HEALTH),
        (
            ReadInvestigationIntent.GUEST_SHUTDOWN,
            ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS,
        ),
        (ReadInvestigationIntent.NETWORK_SECURITY, ReadToolId.QUERY_NETWORK_SECURITY),
        (ReadInvestigationIntent.NETWORK_PEERING, ReadToolId.QUERY_NETWORK_PEERINGS),
    ],
)
async def test_executor_plans_every_registered_intent_without_prompt_classification(
    intent: ReadInvestigationIntent,
    expected_tool: ReadToolId,
) -> None:
    service = _Service()
    progress: list[str] = []
    executor = ReadInvestigationBackgroundExecutor(service, clock=lambda: NOW)  # type: ignore[arg-type]

    result = await executor.execute(
        task=_task(intent),
        progress=lambda kind, message, usage: _record_progress(
            progress, kind, message, usage.tool_calls
        ),
    )

    plan = service.plans[0]
    assert plan.steps[0].tool_id is ReadToolId.RESOLVE_RESOURCE  # type: ignore[attr-defined]
    assert expected_tool in {step.tool_id for step in plan.steps}  # type: ignore[attr-defined]
    assert plan.request.selector.scope_ref == "scope:configured-reader"  # type: ignore[attr-defined]
    assert result.terminal_reason == "unavailable"
    assert result.usage.cost_microusd == 500_000
    assert progress


async def test_executor_keeps_legacy_task_unavailable_without_provider_call() -> None:
    service = _Service()
    executor = ReadInvestigationBackgroundExecutor(service, clock=lambda: NOW)  # type: ignore[arg-type]

    result = await executor.execute(
        task=_task(None),
        progress=lambda kind, message, usage: _record_progress([], kind, message, usage.tool_calls),
    )

    assert result.terminal_reason == "read_investigation_spec_unavailable"
    assert service.plans == []


async def _record_progress(
    records: list[str],
    kind: str,
    message: str,
    tool_calls: int,
) -> None:
    assert kind == message
    assert tool_calls == 0
    records.append(kind)
