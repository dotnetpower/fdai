"""A signed Plan cannot bypass observed-schema refusal before workload effects."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from fdai_lifecycle_agent.dry_run import load_current_state, snapshot_document
from fdai_lifecycle_agent.state import write_json_atomically

from .test_operator_workload import poll_operator, serve_operator

if TYPE_CHECKING:
    from .conftest import FakeCluster, Harness


@pytest.mark.parametrize("revision", [11, 17])
def test_outside_tolerance_is_rejected_before_cluster_calls(
    harness: Harness,
    cluster: FakeCluster,
    revision: int,
) -> None:
    harness.apply_mode(cluster)
    current = load_current_state(harness.state_file)
    write_json_atomically(
        harness.state_file,
        snapshot_document(
            current.entities,
            schema_revision=revision,
            observed_at=current.observed_at,
            available_artifact_digests=current.available_artifact_digests,
        ),
    )
    serve_operator(harness, cluster)
    before = harness.state_file.read_bytes()
    result = poll_operator(harness, cluster)
    assert result.reason_code == "schema_transition_unsupported"
    assert cluster.calls == []
    assert harness.state_file.read_bytes() == before
