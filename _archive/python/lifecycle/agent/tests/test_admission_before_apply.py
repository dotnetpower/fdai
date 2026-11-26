"""Plan authentication stays ahead of the opted-in workload effect path."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from .conftest import FakeCluster, Harness


@pytest.mark.parametrize(
    ("fault", "reason"),
    [
        ("sequence", "plan_sequence_stale"),
        ("audience", "plan_audience_mismatch"),
        ("revoked", "hub_key_revoked"),
        ("envelope", "plan_envelope_exceeds_local_maximum"),
    ],
)
def test_rejected_plan_never_reaches_an_enabled_apply_adapter(
    harness: Harness,
    cluster: FakeCluster,
    fault: str,
    reason: str,
) -> None:
    harness.apply_mode(cluster)
    state = harness.state_store.load()
    harness.state_store.save(replace(state, last_accepted_sequence=5))
    changes = {
        "sequence": {"sequence": 3},
        "audience": {"audience": "installation-other"},
        "revoked": {"hub_key_id": "hub-key-revoked", "hub_key_epoch": 2},
        "envelope": {"envelope": harness.maximum_envelope(destructive_allowed=True)},
    }
    plan = harness.serve(
        harness.release_plan("1.0.0", harness.image("admission-release"), **changes[fault])
    )
    before = harness.state_file.read_bytes()
    result = harness.apply_poll(cluster)
    assert (result.outcome, result.reason_code) == ("rejected", reason)
    assert cluster.calls == []
    assert harness.state_file.read_bytes() == before
    retained = harness.state_store.load()
    assert retained.last_accepted_sequence == 5
    assert plan.sequence in retained.rejected_sequences
