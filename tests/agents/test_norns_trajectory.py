from datetime import UTC, datetime

import pytest

from fdai.agents import Norns
from fdai.core.trajectory import ReviewedTrajectoryDataset, TrajectoryLearningAggregate


def _reviewed() -> ReviewedTrajectoryDataset:
    return ReviewedTrajectoryDataset(
        dataset_id="dataset-1",
        manifest_checksum="a" * 64,
        reviewed_by="reviewer-1",
        reviewed_at=datetime(2026, 7, 21, tzinfo=UTC),
        review_ref="approval-1",
        aggregate=TrajectoryLearningAggregate(
            record_count=2,
            outcome_counts=(("completed", 1), ("failed", 1)),
            tool_request_counts=(("tool-a", 1), ("tool-b", 0)),
        ),
    )


def test_norns_consumes_reviewed_aggregate_once_without_candidate_or_promotion() -> None:
    norns = Norns()

    assert norns.observe_reviewed_trajectory_dataset(_reviewed()) is True
    assert norns.observe_reviewed_trajectory_dataset(_reviewed()) is False
    assert norns.pending_candidates == []
    assert norns.behavior_snapshot()["reviewed_trajectory_dataset_consumed"] == 1


def test_norns_rejects_unreviewed_or_raw_trajectory_input() -> None:
    norns = Norns()

    with pytest.raises(TypeError, match="ReviewedTrajectoryDataset"):
        norns.observe_reviewed_trajectory_dataset({"dataset_id": "raw"})  # type: ignore[arg-type]

    assert norns.pending_candidates == []
