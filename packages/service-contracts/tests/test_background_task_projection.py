"""Focused checks for the background-task projection transport contract."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from fdai_service_contracts import ConsumerCodec, ProducerCodec
from fdai_service_contracts.background_task_projection import (
    BackgroundTaskProjectionBudget,
    BackgroundTaskProjectionEnvelope,
    BackgroundTaskProjectionUsage,
    background_task_snapshot_sequence,
    build_background_task_progress,
    build_background_task_snapshot,
)

NOW = datetime(2026, 8, 29, tzinfo=UTC)


def _snapshot(**updates: object) -> BackgroundTaskProjectionEnvelope:
    values: dict[str, object] = {
        "task_id": "background-task-one",
        "owner_principal_id": "principal-one",
        "attempt_id": "background-task-one:1",
        "task_kind": "read_only_investigation",
        "status": "succeeded",
        "revision": 5,
        "created_at": NOW - timedelta(minutes=1),
        "updated_at": NOW,
        "retention_until": NOW + timedelta(days=30),
        "recorded_at": NOW + timedelta(seconds=2),
        "usage": BackgroundTaskProjectionUsage(tokens=12, cost_microusd=34, tool_calls=2),
        "budget": BackgroundTaskProjectionBudget(
            max_wall_seconds=300,
            max_tokens=4096,
            max_cost_microusd=500000,
            max_tool_calls=5,
            max_progress_events=32,
        ),
        "request_summary": "Investigate the queued deployment drift.",
        "request_truncated": False,
        "accountable_agent": "Heimdall",
        "result_summary": "The deployment is healthy again.",
        "result_truncated": False,
        "evidence_refs": ("evidence-one",),
        "evidence_truncated": False,
        "terminal_reason": "completed",
        "started_at": NOW,
        "finished_at": NOW + timedelta(seconds=1),
        "completion_state": "delivered",
        "completion_attempt_count": 1,
        "progress_watermark": 2,
    }
    values.update(updates)
    return build_background_task_snapshot(**values)  # type: ignore[arg-type]


def _progress(**updates: object) -> BackgroundTaskProjectionEnvelope:
    values: dict[str, object] = {
        "task_id": "background-task-one",
        "owner_principal_id": "principal-one",
        "attempt_id": "background-task-one:1",
        "progress_sequence": 2,
        "progress_order": 11,
        "progress_kind": "investigation.progress",
        "progress_message": "Collected the authoritative resource state.",
        "progress_at": NOW,
        "retention_until": NOW + timedelta(days=30),
        "usage": BackgroundTaskProjectionUsage(tokens=5, cost_microusd=8, tool_calls=1),
    }
    values.update(updates)
    return build_background_task_progress(**values)  # type: ignore[arg-type]


def test_snapshot_round_trips_and_codec_validates_schema() -> None:
    snapshot = _snapshot()
    producer = ProducerCodec("background-task-projection", "N", "1.0.0")
    consumer = ConsumerCodec("background-task-projection", "N", ("1.0.0",))

    encoded = producer.encode(snapshot.model_dump(mode="json"))
    decoded = consumer.decode(encoded)
    restored = BackgroundTaskProjectionEnvelope.model_validate(decoded)

    assert restored == snapshot
    assert restored.record_kind == "snapshot"
    assert restored.execution_authority is False
    assert restored.revision is not None
    assert restored.completion_attempt_count is not None
    assert restored.projection_sequence == background_task_snapshot_sequence(
        restored.revision,
        restored.completion_state,
        restored.completion_attempt_count,
    )


def test_progress_round_trips_and_preserves_deterministic_identity() -> None:
    progress = _progress()
    restored = BackgroundTaskProjectionEnvelope.model_validate_json(progress.model_dump_json())

    assert restored == progress
    assert restored.record_kind == "progress"
    assert restored.progress_sequence == 2
    assert restored.progress_order == 11
    assert restored.execution_authority is False


def test_snapshot_rejects_digest_tampering_and_non_terminal_completion_state() -> None:
    snapshot = _snapshot()

    with pytest.raises(ValidationError, match="digest does not match"):
        BackgroundTaskProjectionEnvelope.model_validate(
            {**snapshot.model_dump(mode="json"), "result_summary": "tampered"}
        )
    with pytest.raises(ValidationError, match="terminal status"):
        _snapshot(
            status="running",
            completion_state="pending",
            completion_attempt_count=0,
            progress_watermark=None,
        )


def test_progress_rejects_snapshot_fields_and_control_characters() -> None:
    progress = _progress()

    with pytest.raises(ValidationError, match="snapshot-only fields"):
        BackgroundTaskProjectionEnvelope.model_validate(
            {**progress.model_dump(mode="json"), "status": "running"}
        )
    with pytest.raises(ValidationError, match="control characters"):
        build_background_task_progress(
            task_id="background-task-one",
            owner_principal_id="principal-one",
            attempt_id="background-task-one:1",
            progress_sequence=3,
            progress_order=12,
            progress_kind="investigation.progress",
            progress_message="bad\nmessage",
            progress_at=NOW,
            retention_until=NOW + timedelta(days=30),
            usage=BackgroundTaskProjectionUsage(),
        )


def test_terminal_snapshot_requires_watermark_and_progress_requires_append_order() -> None:
    with pytest.raises(ValidationError, match="terminal background task snapshot is incomplete"):
        BackgroundTaskProjectionEnvelope.model_validate(
            _snapshot(progress_watermark=None).model_dump(mode="json")
        )
    with pytest.raises(ValidationError, match="background task progress record is incomplete"):
        BackgroundTaskProjectionEnvelope.model_validate(
            _progress(progress_order=None).model_dump(mode="json")
        )


def test_codec_rejects_wrong_version_before_model_validation() -> None:
    payload = _snapshot().model_dump(mode="json")
    payload["schema_version"] = "9.9.9"
    encoded = json.dumps(payload, separators=(",", ":")).encode()

    consumer = ConsumerCodec("background-task-projection", "N", ("1.0.0",))
    with pytest.raises(ValueError, match="rejects version"):
        consumer.decode(encoded)
