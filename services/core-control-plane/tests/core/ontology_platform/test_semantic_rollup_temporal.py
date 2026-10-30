"""Temporal rollups preserve observed order without claiming unseen continuity."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import timedelta
from decimal import Decimal

import pytest
from fdai.core.ontology_platform.semantic_rollup import (
    RelationshipChange,
    RollupFactKind,
    build_semantic_rollup,
)
from fdai.core.ontology_platform.semantic_rollup_merge import merge_semantic_rollups
from fdai.delivery.inventory_rollup import semantic_rollup_to_archive_partition

from .test_semantic_rollup import _DIGEST_B, _START, _observation, _policy


def _build(policy, observations, start=0, end=3):
    return build_semantic_rollup(
        policy,
        tuple(observations),
        window_start=_START + timedelta(minutes=start),
        window_end=_START + timedelta(minutes=end),
    )


def _temporal(result):
    return json.loads(result.statistics_json)["temporal"]


def test_short_bad_event_retains_order_uncertainty_and_archive_coverage():
    policy = _policy(RollupFactKind.CATEGORICAL_STATE, ("state_timeline",))
    result = _build(
        policy,
        [_observation(policy, i, state) for i, state in enumerate(("healthy", "bad", "healthy"))],
    )
    temporal = _temporal(result)
    assert [run["value"] for run in temporal["timeline"]] == ["healthy", "bad", "healthy"]
    assert [run["observed_interval_seconds"] for run in temporal["timeline"]] == ["60"] * 3
    assert [(edge["from_state"], edge["to_state"]) for edge in temporal["transitions"]] == [
        ("healthy", "bad"),
        ("bad", "healthy"),
    ]
    assert all(not edge["exact_transition_time_available"] for edge in temporal["transitions"])
    assert temporal["continuity"] == "not_asserted"
    archive = semantic_rollup_to_archive_partition(
        result, partition_id="partition", schema_version="1"
    )
    assert archive.complete and archive.content_digest == result.digest
    assert archive.ontology_release_digest == _DIGEST_B


def test_missed_interval_never_bridges_state_or_counter():
    for kind, field, values in [
        (RollupFactKind.CATEGORICAL_STATE, "state_timeline", ("healthy", "healthy")),
        (RollupFactKind.COUNTER, "counter_delta", (Decimal(10), Decimal(30))),
    ]:
        policy = _policy(kind, (field,))
        result = _build(
            policy, [_observation(policy, i, v) for i, v in zip((0, 2), values, strict=True)]
        )
        temporal = _temporal(result)
        assert not result.complete and len(temporal["gaps"]) == 1
        assert temporal["observed_interval_seconds"] == "120"
        if field == "state_timeline":
            assert len(temporal["timeline"]) == 2
        else:
            assert temporal["counter_delta"]["known_delta"] == "0"
            assert temporal["counter_delta"]["unresolved"][0]["reason"] == "missing_interval"
        archive = semantic_rollup_to_archive_partition(
            result, partition_id="partition", schema_version="1"
        )
        assert not archive.complete


def test_counter_reset_is_not_an_invented_delta():
    policy = _policy(RollupFactKind.COUNTER, ("counter_delta",))
    result = _build(
        policy, [_observation(policy, i, Decimal(v)) for i, v in enumerate((10, 15, 2, 5))], end=4
    )
    counter = _temporal(result)["counter_delta"]
    assert counter["known_delta"] == "8"
    assert counter["reset_count"] == 1
    assert counter["delta_semantics"] == "sum_of_observed_non_decreasing_steps"
    assert len(counter["resets"]) == 1
    assert counter["resets"][0]["before"]["value"] == "15"
    assert counter["resets"][0]["after"]["value"] == "2"
    assert counter["unresolved"] == []


@pytest.mark.parametrize(
    "change", ["source", "partition", "overlap", "contradiction", "missing_time"]
)
def test_ambiguous_series_fail_closed(change):
    policy = _policy(RollupFactKind.CATEGORICAL_STATE, ("state_timeline",))
    first, second = (_observation(policy, i, "healthy") for i in range(2))
    if change == "source":
        second = replace(second, source_id="another-provider", conflict_count=1)
    elif change == "partition":
        second = replace(second, source_partition_digest=_DIGEST_B)
    elif change == "overlap":
        second = replace(second, interval_start=first.interval_start)
    elif change == "contradiction":
        second = replace(second, event_at=first.event_at)
    else:
        second = replace(second, event_at=None)
    with pytest.raises(ValueError):
        _build(policy, [first, second])


def test_irregular_sampling_uses_exact_coverage_not_slot_quantization():
    policy = _policy(RollupFactKind.COUNTER, ("counter_delta", "time_coverage"))
    first = replace(
        _observation(policy, 0, Decimal(5)),
        interval_end=_START + timedelta(seconds=20),
        effective_at=_START + timedelta(seconds=20),
        event_at=None,
    )
    second = replace(
        _observation(policy, 1, Decimal(9)),
        interval_start=_START + timedelta(seconds=20),
        event_at=None,
    )
    result = _build(policy, [second, first], end=2)
    temporal = _temporal(result)
    assert result.complete and not result.missing_intervals
    assert temporal["time_basis"] == "effective_at"
    assert temporal["observed_interval_seconds"] == "120"
    # A long interval does not establish a missing intermediate counter value.
    assert temporal["counter_delta"]["known_delta"] == "0"
    assert temporal["counter_delta"]["unresolved"][0]["reason"] == "missing_interval"


def test_late_duplicate_keeps_delivery_lineage_without_recounting():
    policy = _policy(RollupFactKind.CATEGORICAL_STATE, ("state_timeline",))
    first = _observation(policy, 0, "healthy")
    late = replace(
        first,
        generation_ref="generation-2",
        source_revision="revision-late",
        recorded_at=_START + timedelta(days=1),
    )
    result = _build(policy, [late, first], end=1)
    assert result.observation_count == 1
    assert result.generation_refs == ("generation-1", "generation-2")
    assert "provider@revision-late" in result.source_revisions
    assert result.recorded_time_range[1] == late.recorded_at
    assert _temporal(result)["timeline"][0]["count"] == 1
    assert _temporal(result)["first"]["recorded_at"] == late.recorded_at.isoformat()


@pytest.mark.parametrize(
    "kind,statistics,values",
    [
        (RollupFactKind.CATEGORICAL_STATE, ("state_timeline",), ("healthy", "bad", "healthy")),
        (RollupFactKind.CATEGORICAL_STATE, ("state_timeline",), ("healthy",) * 3),
        (RollupFactKind.COUNTER, ("counter_delta",), (Decimal(10), Decimal(2), Decimal(7))),
        (
            RollupFactKind.GAUGE,
            ("count", "sum", "extrema_timestamps"),
            (Decimal(2), Decimal(9), Decimal(2)),
        ),
        (
            RollupFactKind.RELATIONSHIP_CHANGE,
            ("change_timeline",),
            (RelationshipChange.ADDED, RelationshipChange.REMOVED, RelationshipChange.ADDED),
        ),
    ],
)
def test_merge_is_equivalent_and_associative(kind, statistics, values):
    policy = _policy(kind, statistics)
    observations = [_observation(policy, i, value) for i, value in enumerate(values)]
    direct = _build(policy, observations)
    pieces = [_build(policy, [item], start=i, end=i + 1) for i, item in enumerate(observations)]
    merged = merge_semantic_rollups(policy, tuple(reversed(pieces)))
    nested = merge_semantic_rollups(
        policy,
        (
            merge_semantic_rollups(policy, tuple(pieces[:2])),
            pieces[2],
        ),
    )
    assert merged == direct == nested


def test_merge_rejects_policy_source_and_time_mismatch():
    policy = _policy(RollupFactKind.COUNTER, ("counter_delta",))
    first = _build(policy, [_observation(policy, 0, Decimal(1))], end=1)
    second_observation = _observation(policy, 1, Decimal(2))
    for changed in (
        replace(second_observation, source_id="other"),
        replace(second_observation, event_at=None),
        replace(second_observation, source_partition_digest=_DIGEST_B),
    ):
        second = _build(policy, [changed], start=1, end=2)
        with pytest.raises(ValueError):
            merge_semantic_rollups(policy, (first, second))
    with pytest.raises(ValueError, match="exact statistics policy"):
        merge_semantic_rollups(replace(policy, expected_interval_seconds=30), (first,))


def test_empty_window_and_gap_merge_equivalence():
    policy = _policy(RollupFactKind.CATEGORICAL_STATE, ("state_timeline",))
    first, last = _observation(policy, 0, "healthy"), _observation(policy, 2, "bad")
    pieces = (
        _build(policy, [first], end=1),
        _build(policy, [], start=1, end=2),
        _build(policy, [last], start=2, end=3),
    )
    assert merge_semantic_rollups(policy, pieces) == _build(policy, [first, last])


def test_constant_state_and_revision_statistics_are_run_bounded():
    policy = _policy(RollupFactKind.CATEGORICAL_STATE, ("state_timeline",))
    sizes = []
    for count in (10, 1000):
        result = _build(
            policy,
            [
                replace(_observation(policy, i, "healthy"), source_revision="unchanged")
                for i in range(count)
            ],
            end=count,
        )
        temporal = _temporal(result)
        assert len(temporal["timeline"]) == 1 and temporal["timeline"][0]["count"] == count
        sizes.append(len(result.statistics_json.encode()))
    assert sizes[1] < sizes[0] + 100
    # Changing revisions grow ordered metadata; this bound needs an unchanged revision.


def test_compressed_runs_preserve_revision_order_and_declare_known_at_loss():
    policy = _policy(RollupFactKind.CATEGORICAL_STATE, ("state_timeline",))
    indices = (0, 1, 2, 4, 5, 6, 7, 8, 9)
    rows = [
        _observation(policy, i, state)
        for i, state in zip(indices, ("A",) * 3 + ("B",) * 3 + ("A",) * 3, strict=True)
    ]
    delayed = _START + timedelta(days=2)
    rows = [
        replace(row, recorded_at=delayed) if position >= 3 else row
        for position, row in enumerate(rows)
    ]
    early = list(rows)
    late = list(rows)
    early[4] = replace(rows[4], recorded_at=_START + timedelta(days=1, hours=1))
    late[4] = replace(rows[4], recorded_at=_START + timedelta(days=1, hours=3))
    first, second = _build(policy, early, end=10), _build(policy, late, end=10)
    assert first == second
    temporal = _temporal(first)
    assert [run["value"] for run in temporal["timeline"]] == ["A", "B", "A"]
    assert temporal["gaps"] == [
        [
            (_START + timedelta(minutes=3)).isoformat(),
            (_START + timedelta(minutes=4)).isoformat(),
        ]
    ]
    assert [
        revision for run in temporal["timeline"] for revision in run["source_revision_order"]
    ] == [row.source_revision for row in rows]
    assert set(first.source_revisions) == {f"provider@{row.source_revision}" for row in rows}
    cutoff = _START + timedelta(days=1, hours=2)

    def raw_as_of(observations, known_at):
        return max(
            (row for row in observations if row.recorded_at <= known_at),
            key=lambda row: row.effective_at,
        ).value

    assert raw_as_of(early, cutoff) == "B" and raw_as_of(late, cutoff) == "A"
    after_last_recorded = delayed + timedelta(seconds=1)
    assert raw_as_of(early, after_last_recorded) == raw_as_of(late, after_last_recorded) == "A"
    assert temporal["known_at_reconstruction"] == "cannot_reconstruct_intermediate_known_at"
    assert temporal["last"]["value"] == "A"
    assert temporal["last"]["recorded_at"] == delayed.isoformat()


def test_temporal_merge_explicitly_rejects_different_source_partitions():
    policy = _policy(RollupFactKind.CATEGORICAL_STATE, ("state_timeline",))
    first = _build(policy, [_observation(policy, 0, "A")], end=1)
    second = _build(
        policy,
        [replace(_observation(policy, 1, "A"), source_partition_digest=_DIGEST_B)],
        start=1,
        end=2,
    )
    with pytest.raises(ValueError, match="requires one source and source partition"):
        merge_semantic_rollups(policy, (first, second))


def test_full_rollup_serialized_bytes_include_linear_revision_metadata():
    policy = _policy(RollupFactKind.CATEGORICAL_STATE, ("state_timeline",))
    measurements = []
    for count in (10, 1000):
        result = _build(
            policy, [_observation(policy, i, "healthy") for i in range(count)], end=count
        )
        record = asdict(result)
        assert len(record["source_revisions"]) == count
        full_bytes = len(
            json.dumps(
                record,
                default=str,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        )
        statistics_bytes = len(result.statistics_json.encode("utf-8"))
        measurements.append((full_bytes, statistics_bytes))
    full_growth = measurements[1][0] - measurements[0][0]
    statistics_growth = measurements[1][1] - measurements[0][1]
    assert full_growth > statistics_growth + 10000
    assert measurements[1][0] > measurements[0][0] * 5
    print(
        {
            "observations": [10, 1000],
            "full_record_json_bytes_not_db_bytes": [item[0] for item in measurements],
            "statistics_utf8_bytes": [item[1] for item in measurements],
        }
    )


@pytest.mark.parametrize(
    "kind,statistics,values,digest",
    [
        (
            RollupFactKind.GAUGE,
            ("count", "sum", "minimum", "maximum", "average"),
            (Decimal(0), Decimal(2)),
            "85be4aa4f4b9597bb9ecda675103cdc8002da811e9824ccab1b996663a546651",
        ),
        (
            RollupFactKind.COUNTER,
            ("count", "sum", "average"),
            (Decimal(3), Decimal(5)),
            "14e09adff0361445b1c73e27ab80680ede9b87c595d2cd3dd221a8d23a7bb97f",
        ),
        (
            RollupFactKind.CATEGORICAL_STATE,
            ("state_counts", "latest"),
            ("ready", "degraded"),
            "fbf3b4d4dd600a97bc5b26e7f6f5eaf66a196486901e2d5b22c289cb599ac202",
        ),
    ],
)
def test_legacy_digest_golden(kind, statistics, values, digest):
    policy = _policy(kind, statistics)
    result = _build(
        policy, [_observation(policy, i, value) for i, value in enumerate(values)], end=2
    )
    assert result.digest == "sha256:" + digest


@pytest.mark.parametrize("quality", ["generation", "incomplete", "conflict"])
def test_counter_quality_boundaries_are_unresolved_not_delta(quality):
    policy = _policy(RollupFactKind.COUNTER, ("counter_delta",))
    first = _observation(policy, 0, Decimal(10))
    second = _observation(policy, 1, Decimal(20))
    if quality == "generation":
        second = replace(second, generation_ref="generation-2")
    elif quality == "incomplete":
        second = replace(second, complete=False)
    else:
        second = replace(second, conflict_count=1)
    direct = _build(policy, [first, second], end=2)
    counter = _temporal(direct)["counter_delta"]
    assert counter["known_delta"] == "0" and len(counter["unresolved"]) == 1
    assert direct == merge_semantic_rollups(
        policy,
        (
            _build(policy, [first], end=1),
            _build(policy, [second], start=1, end=2),
        ),
    )


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-1")])
def test_invalid_counter_samples_fail_closed(value):
    policy = _policy(RollupFactKind.COUNTER, ("counter_delta",))
    with pytest.raises(ValueError):
        _build(policy, [_observation(policy, 0, value)], end=1)


def test_counter_arithmetic_does_not_round_large_boundaries():
    policy = _policy(RollupFactKind.COUNTER, ("counter_delta",))
    values = (Decimal("100000000000000000000000000001"), Decimal("100000000000000000000000000003"))
    result = _build(policy, [_observation(policy, i, v) for i, v in enumerate(values)], end=2)
    temporal = _temporal(result)
    assert temporal["first"]["value"] == str(values[0])
    assert temporal["counter_delta"]["known_delta"] == "2"


def test_temporal_merge_cannot_silently_downgrade_to_legacy_statistics():
    policy = _policy(RollupFactKind.COUNTER, ("counter_delta",))
    result = _build(policy, [_observation(policy, 0, Decimal(1))], end=1)
    with pytest.raises(ValueError, match="exact statistics policy"):
        merge_semantic_rollups(replace(policy, statistics=("count",)), (result,))


def test_inventory_archive_seam_keeps_observation_time_distinct_from_event_time():
    from fdai.delivery.inventory_convergence import (
        InventoryMutationKind,
        InventoryObservationMode,
        InventoryObservedRevision,
    )
    from fdai.delivery.inventory_rollup import inventory_revision_to_rollup_observation

    policy = _policy(RollupFactKind.RELATIONSHIP_CHANGE, ("change_timeline",))
    observations = []
    for i, mutation in enumerate((InventoryMutationKind.UPSERT, InventoryMutationKind.TOMBSTONE)):
        revision = InventoryObservedRevision(
            logical_key="relationship.example",
            mode=InventoryObservationMode.DELTA,
            mutation=mutation,
            observed_at=_START + timedelta(minutes=i + 1),
            recorded_at=_START + timedelta(minutes=i + 1, seconds=2),
            source_id="provider",
            source_revision=f"revision-{i}",
            payload_digest="sha256:" + str(i + 1) * 64,
        )
        observation = inventory_revision_to_rollup_observation(
            revision,
            policy,
            generation_ref="generation-1",
            interval_start=_START + timedelta(minutes=i),
            interval_end=_START + timedelta(minutes=i + 1),
            complete=True,
            conflict_count=0,
            source_partition_digest=_DIGEST_B,
        )
        assert observation.event_at is None
        assert observation.source_partition_digest == _DIGEST_B
        legacy = inventory_revision_to_rollup_observation(
            revision,
            replace(policy, statistics=("change_counts",)),
            generation_ref="generation-1",
            interval_start=_START + timedelta(minutes=i),
            interval_end=_START + timedelta(minutes=i + 1),
            complete=True,
            conflict_count=0,
        )
        assert legacy.event_at == revision.observed_at
        assert legacy.source_partition_digest == revision.payload_digest
        observations.append(observation)
    result = _build(policy, observations, end=2)
    temporal = _temporal(result)
    assert temporal["time_basis"] == "effective_at"
    assert [run["value"] for run in temporal["timeline"]] == ["added", "removed"]
    archive = semantic_rollup_to_archive_partition(
        result,
        partition_id="partition",
        schema_version="1",
    )
    assert archive.complete and archive.relationship_count == 2
    assert archive.content_digest == result.digest


def test_conflicting_state_transition_retains_order_but_not_resolved_transition():
    policy = _policy(RollupFactKind.CATEGORICAL_STATE, ("state_timeline",))
    result = _build(
        policy,
        (
            _observation(policy, 0, "healthy"),
            _observation(policy, 1, "bad", conflict_count=1),
        ),
        end=2,
    )
    assert not result.complete and result.conflict_count == 1
    temporal = _temporal(result)
    assert [run["value"] for run in temporal["timeline"]] == ["healthy", "bad"]
    assert temporal["transitions"][0]["evidence_status"] == "unresolved"
