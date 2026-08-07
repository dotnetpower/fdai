from __future__ import annotations

import json

from fdai.delivery.operator_api.projections.conversation.trajectory import (
    TrajectoryDetailCollector,
    trajectory_detail_budget,
)


def test_collector_keeps_latest_allowlisted_records() -> None:
    collector = TrajectoryDetailCollector()
    collector.observe(
        {
            "event": "branch",
            "branch_id": "branch-1",
            "branch_kind": "operational",
            "parent_branch_id": None,
            "status": "running",
            "summary": "Reading evidence",
            "started_at": "2026-01-01T00:00:00Z",
            "evidence_refs": [],
            "ignored": "not retained",
        }
    )
    collector.observe(
        {
            "event": "branch",
            "branch_id": "branch-1",
            "branch_kind": "operational",
            "parent_branch_id": None,
            "status": "completed",
            "summary": "Evidence ready",
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": "2026-01-01T00:00:01Z",
            "duration_ms": 1000,
            "evidence_refs": ["evidence:1"],
        }
    )

    payload = collector.snapshot()

    assert payload is not None
    assert payload["branches"] == [
        {
            "branch_id": "branch-1",
            "branch_kind": "operational",
            "parent_branch_id": None,
            "status": "completed",
            "summary": "Evidence ready",
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": "2026-01-01T00:00:01Z",
            "duration_ms": 1000,
            "evidence_refs": ["evidence:1"],
        }
    ]
    assert "ignored" not in json.dumps(payload)


def test_collector_drops_execution_without_redaction_attestation() -> None:
    collector = TrajectoryDetailCollector()
    collector.observe(
        {
            "event": "activity",
            "activity_id": "unsafe-execution",
            "kind": "query",
            "status": "completed",
            "label": "Query",
            "completed": 1,
            "total": 1,
            "execution": {
                "tool": "inventory",
                "command": "sensitive input",
                "input_kind": "query",
                "redacted": False,
                "output": "sensitive output",
            },
        }
    )

    payload = collector.snapshot()

    assert payload is not None
    assert "execution" not in payload["activities"][0]
    assert "sensitive" not in json.dumps(payload)


def test_collector_truncates_outputs_and_caps_terminal_payload() -> None:
    collector = TrajectoryDetailCollector()
    for index in range(8):
        collector.observe(
            {
                "event": "activity",
                "activity_id": f"activity-{index}",
                "kind": "query",
                "status": "completed",
                "label": f"Query {index}",
                "completed": 1,
                "total": 1,
                "execution": {
                    "tool": "inventory",
                    "command": '{"query":"status"}',
                    "input_kind": "query",
                    "redacted": True,
                    "output": "x" * (64 * 1024),
                },
            }
        )

    payload = collector.snapshot()

    assert payload is not None
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    assert len(serialized.encode("ascii")) <= 64 * 1024
    assert payload["omitted"]["activities"] > 0
    assert payload["truncated_outputs"] == len(payload["activities"])
    assert all(item["execution"]["output_truncated"] is True for item in payload["activities"])


def test_collector_counts_repeated_omitted_identity_once() -> None:
    collector = TrajectoryDetailCollector()
    for index in range(9):
        event = {
            "event": "activity",
            "activity_id": f"activity-{index}",
            "kind": "query",
            "status": "completed",
            "label": "Query",
            "completed": 1,
            "total": 1,
        }
        collector.observe(event)
        if index == 8:
            collector.observe({**event, "label": "Repeated query update"})

    payload = collector.snapshot()

    assert payload is not None
    assert payload["omitted"]["activities"] == 1


def test_collector_truncates_unicode_output_by_serialized_bytes() -> None:
    collector = TrajectoryDetailCollector()
    collector.observe(
        {
            "event": "activity",
            "activity_id": "unicode-output",
            "kind": "query",
            "status": "completed",
            "label": "Query",
            "completed": 1,
            "total": 1,
            "execution": {
                "tool": "inventory",
                "command": '{"query":"status"}',
                "input_kind": "query",
                "redacted": True,
                "output": "상태" * (32 * 1024),
            },
        }
    )

    payload = collector.snapshot()

    assert payload is not None
    output = payload["activities"][0]["execution"]["output"]
    assert output
    assert len(json.dumps(output, ensure_ascii=True).encode("ascii")) <= 32 * 1024
    assert payload["truncated_outputs"] == 1


def test_collector_fits_remaining_terminal_frame_budget() -> None:
    collector = TrajectoryDetailCollector()
    collector.observe(
        {
            "event": "milestone",
            "message_id": "milestone-1",
            "text": "x" * 1024,
            "recorded_at": "2026-01-01T00:00:00Z",
        }
    )
    base_payload = {"answer": "x" * (250 * 1024)}
    budget = trajectory_detail_budget(base_payload)

    detail = collector.snapshot(max_bytes=budget)

    assert budget < 64 * 1024
    if detail is not None:
        terminal = {**base_payload, "trajectory_detail": detail}
        assert (
            len(
                json.dumps(
                    terminal,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("ascii")
            )
            <= 252 * 1024
        )
