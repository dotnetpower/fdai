from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.trajectory import DatasetGovernance, TrajectoryJoinService
from fdai.core.trajectory.projection import TrajectoryProjectionRequest
from fdai.shared.providers.trajectory import (
    AuthorizedTrajectoryScope,
    ImmutableTrajectorySnapshot,
    TrajectoryBatchFilters,
    TrajectorySourceKind,
)

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)


class DenyingAuthorizer:
    async def authorize(self, **_: object) -> AuthorizedTrajectoryScope:
        raise PermissionError("scope denied")


class CountingProvider:
    def __init__(self, records: tuple[ImmutableTrajectorySnapshot, ...] = ()) -> None:
        self.calls = 0
        self.records = records

    async def snapshot(self, **_: object) -> tuple[ImmutableTrajectorySnapshot, ...]:
        self.calls += 1
        return self.records


class AllowingAuthorizer:
    async def authorize(self, **_: object) -> AuthorizedTrajectoryScope:
        return AuthorizedTrajectoryScope("principal-1", "scope-1", "b" * 64)


def _request() -> TrajectoryProjectionRequest:
    return TrajectoryProjectionRequest(
        principal_id="principal-1",
        access_scope="scope-1",
        purpose="quality-review",
        environment="test",
        evidence_profile="reviewed",
        model_capability_id="t1.judge",
        redaction_policy_version="1.0",
        governance=DatasetGovernance(
            purpose="quality-review",
            retention_until=NOW + timedelta(days=30),
            deletion_due_at=NOW + timedelta(days=31),
        ),
        catalog_tool_ids=("tool-a", "tool-b"),
        filters=TrajectoryBatchFilters(outcomes=("failed",)),
    )


async def test_authorization_happens_before_any_source_materialization() -> None:
    provider = CountingProvider()
    service = TrajectoryJoinService(
        authorizer=DenyingAuthorizer(),
        audit=provider,
        conversation=provider,
        tool=provider,
        approval=provider,
        outcome=provider,
    )

    with pytest.raises(PermissionError, match="scope denied"):
        await service.materialize(_request())

    assert provider.calls == 0


def test_immutable_snapshot_deep_freezes_payload() -> None:
    snapshot = ImmutableTrajectorySnapshot(
        TrajectorySourceKind.TOOL,
        "receipt-1",
        "a" * 64,
        "trace-1",
        "correlation-1",
        NOW,
        "tool_receipt",
        {"result": {"status": "succeeded"}},
    )

    with pytest.raises(TypeError):
        snapshot.payload["result"]["status"] = "failed"  # type: ignore[index]


async def test_join_is_deterministic_and_preserves_mixed_tool_failure() -> None:
    records = (
        ImmutableTrajectorySnapshot(
            TrajectorySourceKind.OUTCOME,
            "outcome-1",
            "e" * 64,
            "trace-1",
            "correlation-1",
            NOW + timedelta(seconds=3),
            "terminal_outcome",
            {"outcome": "failed"},
        ),
        ImmutableTrajectorySnapshot(
            TrajectorySourceKind.TOOL,
            "receipt-1",
            "d" * 64,
            "trace-1",
            "correlation-1",
            NOW + timedelta(seconds=2),
            "tool_receipt",
            {"tool_id": "tool-a", "status": "failed", "receipt_ref": "receipt-1"},
        ),
        ImmutableTrajectorySnapshot(
            TrajectorySourceKind.TOOL,
            "request-1",
            "c" * 64,
            "trace-1",
            "correlation-1",
            NOW + timedelta(seconds=1),
            "tool_request",
            {"tool_id": "tool-a", "action_type": "tool.inspect"},
        ),
    )
    provider = CountingProvider(records)
    empty = CountingProvider()
    service = TrajectoryJoinService(
        authorizer=AllowingAuthorizer(),
        audit=empty,
        conversation=empty,
        tool=provider,
        approval=empty,
        outcome=empty,
    )

    first = await service.materialize(_request())
    second = await service.materialize(_request())

    assert first == second
    assert [step.kind.value for step in first[0].steps] == [
        "tool_request",
        "tool_receipt",
        "terminal_outcome",
    ]
    assert first[0].tool_statistics[0].failure_count == 1
    assert first[0].tool_statistics[1].request_count == 0


async def test_join_preserves_complete_observable_tool_and_action_sequence() -> None:
    ordered_kinds = (
        "normalized_input_reference",
        "routing_decision",
        "assistant_output",
        "tool_request",
        "tool_receipt",
        "action_request",
        "verifier_result",
        "risk_result",
        "approval",
        "action_receipt",
        "rollback_state",
        "terminal_outcome",
    )
    records = tuple(
        ImmutableTrajectorySnapshot(
            source_kind=(
                TrajectorySourceKind.OUTCOME
                if kind == "terminal_outcome"
                else TrajectorySourceKind.AUDIT
            ),
            record_id=f"record-{index:02d}",
            record_digest=f"{index + 1:064x}",
            trace_id="trace-full",
            correlation_id="correlation-full",
            occurred_at=NOW + timedelta(seconds=index),
            step_kind=kind,
            payload=(
                {"outcome": "failed"}
                if kind == "terminal_outcome"
                else {"status": "observable", "action_type": "ops.inspect"}
            ),
        )
        for index, kind in enumerate(ordered_kinds)
    )
    provider = CountingProvider(records)
    empty = CountingProvider()
    service = TrajectoryJoinService(
        authorizer=AllowingAuthorizer(),
        audit=provider,
        conversation=empty,
        tool=empty,
        approval=empty,
        outcome=empty,
    )

    result = await service.materialize(_request())

    assert tuple(step.kind.value for step in result[0].steps) == ordered_kinds


async def test_equal_timestamps_use_step_rank_and_keep_terminal_last() -> None:
    records = (
        ImmutableTrajectorySnapshot(
            TrajectorySourceKind.OUTCOME,
            "outcome-1",
            "e" * 64,
            "trace-tie",
            "correlation-tie",
            NOW,
            "terminal_outcome",
            {"outcome": "completed"},
        ),
        ImmutableTrajectorySnapshot(
            TrajectorySourceKind.TOOL,
            "request-1",
            "d" * 64,
            "trace-tie",
            "correlation-tie",
            NOW,
            "tool_request",
            {"tool_id": "tool-a"},
        ),
    )
    provider = CountingProvider(records)
    empty = CountingProvider()
    service = TrajectoryJoinService(
        authorizer=AllowingAuthorizer(),
        audit=empty,
        conversation=empty,
        tool=provider,
        approval=empty,
        outcome=empty,
    )

    result = await service.materialize(_request())

    assert tuple(step.kind.value for step in result[0].steps) == (
        "tool_request",
        "terminal_outcome",
    )
