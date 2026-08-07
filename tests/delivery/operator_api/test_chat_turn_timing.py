from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from fdai.delivery.operator_api.projections.conversation.terminal import TurnTimingRecorder


def test_turn_timing_uses_one_wall_anchor_and_monotonic_offsets() -> None:
    recorder = TurnTimingRecorder(
        started_monotonic=100.0,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    with patch(
        "fdai.delivery.operator_api.projections.conversation.terminal.payload.time.monotonic",
        side_effect=[101.0, 103.5, 104.0],
    ):
        token = recorder.begin("evidence")
        recorder.complete(token, status="degraded")
        payload = recorder.snapshot()

    assert payload == {
        "schema_version": 1,
        "started_at": "2026-01-01T00:00:00+00:00",
        "completed_at": "2026-01-01T00:00:04+00:00",
        "duration_ms": 4000,
        "phases": [
            {
                "phase": "evidence",
                "status": "degraded",
                "started_at": "2026-01-01T00:00:01+00:00",
                "completed_at": "2026-01-01T00:00:03.500000+00:00",
                "duration_ms": 2500,
            }
        ],
    }


def test_turn_timing_rejects_duplicate_or_inactive_completion() -> None:
    recorder = TurnTimingRecorder()
    token = recorder.begin("verification")

    with pytest.raises(ValueError, match="duplicated"):
        recorder.begin("verification")

    with pytest.raises(ValueError, match="active phases"):
        recorder.snapshot()

    recorder.complete(token, status="completed")
    with pytest.raises(ValueError, match="not active"):
        recorder.complete(token, status="completed")
