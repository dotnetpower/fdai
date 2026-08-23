"""Focused semantic rollup coverage tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fdai.core.ontology_platform.semantic_rollup import (
    EvidenceHealth,
    RelationshipChange,
    RollupFactKind,
    RollupObservation,
    SemanticRollupPolicy,
    build_semantic_rollup,
)
from fdai.core.ontology_platform.semantic_rollup_merge import merge_semantic_rollups

_START = datetime(2026, 8, 22, tzinfo=UTC)
_DIGEST_A = "sha256:" + "a" * 64
_DIGEST_B = "sha256:" + "b" * 64


def _policy(
    fact_kind: RollupFactKind,
    statistics: tuple[str, ...],
) -> SemanticRollupPolicy:
    return SemanticRollupPolicy(
        semantic_id=f"semantic.{fact_kind.value}",
        revision="policy-1",
        ontology_release_digest=_DIGEST_B,
        fact_kind=fact_kind,
        expected_interval_seconds=60,
        statistics=statistics,
    )


def _observation(
    policy: SemanticRollupPolicy,
    index: int,
    value: Decimal | str | RelationshipChange | EvidenceHealth,
    *,
    complete: bool = True,
    conflict_count: int = 0,
) -> RollupObservation:
    return RollupObservation(
        observation_id=f"{policy.fact_kind.value}-{index}",
        semantic_id=policy.semantic_id,
        fact_kind=policy.fact_kind,
        source_id="provider",
        source_revision=f"revision-{index}",
        source_partition_digest=_DIGEST_A,
        generation_ref="generation-1",
        ontology_release_digest=policy.ontology_release_digest,
        interval_start=_START + timedelta(minutes=index),
        interval_end=_START + timedelta(minutes=index + 1),
        effective_at=_START + timedelta(minutes=index + 1),
        event_at=_START + timedelta(minutes=index + 1),
        recorded_at=_START + timedelta(minutes=index + 1, seconds=1),
        value=value,
        complete=complete,
        conflict_count=conflict_count,
    )


def test_gauge_rollup_preserves_observed_zero_and_average_parts() -> None:
    policy = SemanticRollupPolicy(
        semantic_id="metric.cpu.utilization",
        revision="policy-1",
        ontology_release_digest=_DIGEST_B,
        fact_kind=RollupFactKind.GAUGE,
        expected_interval_seconds=60,
        statistics=("count", "sum", "minimum", "maximum", "average"),
    )
    observations = tuple(
        RollupObservation(
            observation_id=f"observation-{index}",
            semantic_id=policy.semantic_id,
            fact_kind=policy.fact_kind,
            source_id="monitor",
            source_revision=f"revision-{index}",
            source_partition_digest=_DIGEST_A,
            generation_ref="generation-1",
            ontology_release_digest=_DIGEST_B,
            interval_start=_START + timedelta(minutes=index),
            interval_end=_START + timedelta(minutes=index + 1),
            effective_at=_START + timedelta(minutes=index + 1),
            event_at=_START + timedelta(minutes=index + 1),
            recorded_at=_START + timedelta(minutes=index + 1, seconds=1),
            value=value,
        )
        for index, value in enumerate((Decimal(0), Decimal(2)))
    )

    result = build_semantic_rollup(
        policy,
        observations,
        window_start=_START,
        window_end=_START + timedelta(minutes=2),
    )

    assert result.observed_zero is True
    assert result.complete is True
    assert result.source_count == 1
    assert result.observation_count == 2
    assert result.statistics_json == (
        '{"average":"1","count":2,"maximum":"2","minimum":"0","sum":"2"}'
    )
    assert result.percentiles_available is False


def test_missing_partial_and_conflict_never_become_complete() -> None:
    policy = _policy(RollupFactKind.GAUGE, ("count", "sum", "average"))

    missing = build_semantic_rollup(
        policy,
        (),
        window_start=_START,
        window_end=_START + timedelta(minutes=2),
    )
    partial = build_semantic_rollup(
        policy,
        (_observation(policy, 0, Decimal(1), complete=False),),
        window_start=_START,
        window_end=_START + timedelta(minutes=1),
    )
    conflicting = build_semantic_rollup(
        policy,
        (_observation(policy, 0, Decimal(1), conflict_count=2),),
        window_start=_START,
        window_end=_START + timedelta(minutes=1),
    )

    assert missing.missing_intervals == (
        (_START, _START + timedelta(minutes=1)),
        (_START + timedelta(minutes=1), _START + timedelta(minutes=2)),
    )
    assert missing.complete is False
    assert missing.event_time_missing is True
    assert partial.complete is False
    assert conflicting.complete is False
    assert conflicting.conflict_count == 2


def test_counter_is_separate_and_average_requires_mergeable_parts() -> None:
    with pytest.raises(ValueError, match="average requires count and sum"):
        _policy(RollupFactKind.COUNTER, ("average",))
    policy = _policy(RollupFactKind.COUNTER, ("count", "sum", "average"))

    result = build_semantic_rollup(
        policy,
        (
            _observation(policy, 0, Decimal(3)),
            _observation(policy, 1, Decimal(5)),
        ),
        window_start=_START,
        window_end=_START + timedelta(minutes=2),
    )

    assert result.statistics_json == '{"average":"4","count":2,"sum":"8"}'


def test_fact_kinds_use_distinct_aggregation_families() -> None:
    categorical = _policy(
        RollupFactKind.CATEGORICAL_STATE,
        ("state_counts", "latest"),
    )
    relationship = _policy(
        RollupFactKind.RELATIONSHIP_CHANGE,
        ("change_counts",),
    )
    health = _policy(RollupFactKind.EVIDENCE_HEALTH, ("health_counts",))

    categorical_result = build_semantic_rollup(
        categorical,
        (
            _observation(categorical, 0, "ready"),
            _observation(categorical, 1, "degraded"),
        ),
        window_start=_START,
        window_end=_START + timedelta(minutes=2),
    )
    relationship_result = build_semantic_rollup(
        relationship,
        (
            _observation(relationship, 0, RelationshipChange.ADDED),
            _observation(relationship, 1, RelationshipChange.REMOVED),
        ),
        window_start=_START,
        window_end=_START + timedelta(minutes=2),
    )
    health_result = build_semantic_rollup(
        health,
        (
            _observation(health, 0, EvidenceHealth.HEALTHY),
            _observation(health, 1, EvidenceHealth.CONFLICTING),
        ),
        window_start=_START,
        window_end=_START + timedelta(minutes=2),
    )

    assert categorical_result.statistics_json == (
        '{"latest":"degraded","state_counts":{"degraded":1,"ready":1}}'
    )
    assert relationship_result.statistics_json == '{"added":1,"removed":1}'
    assert health_result.statistics_json == ('{"conflicting":1,"healthy":1,"incomplete":0}')


def test_merge_recomputes_average_from_count_and_sum_and_deduplicates() -> None:
    policy = _policy(
        RollupFactKind.GAUGE,
        ("count", "sum", "minimum", "maximum", "average"),
    )
    first = build_semantic_rollup(
        policy,
        (_observation(policy, 0, Decimal(0)),),
        window_start=_START,
        window_end=_START + timedelta(minutes=1),
    )
    second = build_semantic_rollup(
        policy,
        (_observation(policy, 1, Decimal(4)),),
        window_start=_START + timedelta(minutes=1),
        window_end=_START + timedelta(minutes=2),
    )

    result = merge_semantic_rollups(policy, (second, first, first))

    assert result.observation_count == 2
    assert result.observed_zero is True
    assert result.complete is True
    assert result.generation_refs == ("generation-1",)
    assert result.statistics_json == (
        '{"average":"2","count":2,"maximum":"4","minimum":"0","sum":"4"}'
    )


def test_merge_preserves_each_nonnumeric_statistic_family() -> None:
    cases = (
        (
            _policy(
                RollupFactKind.CATEGORICAL_STATE,
                ("state_counts", "latest"),
            ),
            "ready",
            "degraded",
            '{"latest":"degraded","state_counts":{"degraded":1,"ready":1}}',
        ),
        (
            _policy(RollupFactKind.RELATIONSHIP_CHANGE, ("change_counts",)),
            RelationshipChange.ADDED,
            RelationshipChange.REMOVED,
            '{"added":1,"removed":1}',
        ),
        (
            _policy(RollupFactKind.EVIDENCE_HEALTH, ("health_counts",)),
            EvidenceHealth.HEALTHY,
            EvidenceHealth.INCOMPLETE,
            '{"conflicting":0,"healthy":1,"incomplete":1}',
        ),
    )
    for policy, first_value, second_value, expected in cases:
        first = build_semantic_rollup(
            policy,
            (_observation(policy, 0, first_value),),
            window_start=_START,
            window_end=_START + timedelta(minutes=1),
        )
        second = build_semantic_rollup(
            policy,
            (_observation(policy, 1, second_value),),
            window_start=_START + timedelta(minutes=1),
            window_end=_START + timedelta(minutes=2),
        )

        result = merge_semantic_rollups(policy, (first, second))

        assert result.statistics_json == expected
