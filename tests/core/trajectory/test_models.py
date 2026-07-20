from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.trajectory import (
    DatasetGovernance,
    SourceRecordDigest,
    TrajectoryEnvelope,
    TrajectoryStep,
    TrajectoryStepKind,
    TrajectoryTerminalOutcome,
    TrajectoryVersionPolicy,
    catalog_tool_statistics,
)

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
DIGEST = "a" * 64


@pytest.mark.parametrize("outcome", tuple(TrajectoryTerminalOutcome))
def test_envelope_preserves_every_terminal_outcome(
    outcome: TrajectoryTerminalOutcome,
) -> None:
    source = SourceRecordDigest("audit", "audit-1", DIGEST)
    envelope = TrajectoryEnvelope(
        trajectory_id="trajectory-1",
        trace_id="trace-1",
        correlation_id="correlation-1",
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        environment="test",
        evidence_profile="reviewed",
        principal_scope_digest="b" * 64,
        model_capability_id="t1.judge",
        completion_status=outcome,
        redaction_policy_version="1.0",
        governance=DatasetGovernance(
            purpose="quality-review",
            retention_until=NOW + timedelta(days=30),
            deletion_due_at=NOW + timedelta(days=31),
        ),
        source_records=(source,),
        steps=(
            TrajectoryStep(
                sequence=0,
                occurred_at=NOW,
                kind=TrajectoryStepKind.TERMINAL_OUTCOME,
                source=source,
                payload={"outcome": outcome.value},
            ),
        ),
        tool_statistics=catalog_tool_statistics(
            ("z-unused", "a-used"),
            {"a-used": (1, 1, 0)},
        ),
    )

    assert envelope.completion_status is outcome
    assert [item.tool_id for item in envelope.tool_statistics] == ["a-used", "z-unused"]
    assert envelope.tool_statistics[1].request_count == 0


def test_envelope_rejects_hidden_reasoning_and_broken_order() -> None:
    source = SourceRecordDigest("conversation", "turn-1", DIGEST)

    with pytest.raises(ValueError, match="forbidden fields"):
        TrajectoryStep(
            sequence=0,
            occurred_at=NOW,
            kind=TrajectoryStepKind.ASSISTANT_OUTPUT,
            source=source,
            payload={"chain_of_thought": "must never export"},
        )

    with pytest.raises(ValueError, match="forbidden fields"):
        TrajectoryStep(
            sequence=0,
            occurred_at=NOW,
            kind=TrajectoryStepKind.TOOL_RECEIPT,
            source=source,
            payload={"result": {"raw_output": "must never export"}},
        )

    with pytest.raises(ValueError, match="excerpt limit"):
        TrajectoryStep(
            sequence=0,
            occurred_at=NOW,
            kind=TrajectoryStepKind.NORMALIZED_INPUT_REFERENCE,
            source=source,
            payload={"reference": "x" * 5_000},
        )

    with pytest.raises(ValueError, match="contiguous"):
        TrajectoryEnvelope(
            trajectory_id="trajectory-1",
            trace_id="trace-1",
            correlation_id="correlation-1",
            started_at=NOW,
            completed_at=NOW,
            environment="test",
            evidence_profile="reviewed",
            principal_scope_digest="b" * 64,
            model_capability_id="t1.judge",
            completion_status=TrajectoryTerminalOutcome.FAILED,
            redaction_policy_version="1.0",
            governance=DatasetGovernance(
                purpose="quality-review",
                retention_until=NOW,
                deletion_due_at=NOW,
            ),
            source_records=(source,),
            steps=(
                TrajectoryStep(
                    sequence=1,
                    occurred_at=NOW,
                    kind=TrajectoryStepKind.TERMINAL_OUTCOME,
                    source=source,
                    payload={"outcome": "failed"},
                ),
            ),
            tool_statistics=(),
        )


def test_version_policy_rejects_cross_major_compatibility() -> None:
    with pytest.raises(ValueError, match="share the current major"):
        TrajectoryVersionPolicy(current="2.0", readable=("1.0", "2.0"))

    with pytest.raises(ValueError, match="not readable"):
        TrajectoryVersionPolicy().require_readable("2.0")


def test_nested_payload_is_immutable() -> None:
    source = SourceRecordDigest("tool", "receipt-1", DIGEST)
    step = TrajectoryStep(
        sequence=0,
        occurred_at=NOW,
        kind=TrajectoryStepKind.TOOL_RECEIPT,
        source=source,
        payload={"result": {"status": "succeeded"}, "references": ["evidence-1"]},
    )

    with pytest.raises(TypeError):
        step.payload["result"]["status"] = "failed"  # type: ignore[index]
