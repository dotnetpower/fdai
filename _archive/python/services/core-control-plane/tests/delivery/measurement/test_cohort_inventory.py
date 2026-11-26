"""Aggregate-only cohort evidence inventory tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.measurement.cohort_claim_policy import (
    COHORT_CLAIM_POLICY_PATH,
    load_cohort_claim_policy,
)
from fdai.delivery.measurement.cohort_inventory import (
    CohortEvidenceInventory,
    PostgresCohortEvidenceInventorySource,
    _missing,
    _required_counts,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
POLICY = load_cohort_claim_policy(REPO_ROOT / COHORT_CLAIM_POLICY_PATH)
REVISION = "0123456789abcdef0123456789abcdef01234567"
NOW = datetime(2026, 9, 9, tzinfo=UTC)


def test_required_counts_ignore_unknown_or_malformed_rows() -> None:
    counts = _required_counts(
        [
            {
                "arm": "baseline",
                "measure_id": "metric_a",
                "source_binding_id": "baseline-a",
                "source_workflow_path": ".github/workflows/baseline-a.yml",
                "sample_count": 31,
            },
            {
                "arm": "treatment",
                "measure_id": "metric_b",
                "source_binding_id": "treatment-b",
                "source_workflow_path": ".github/workflows/treatment-b.yml",
                "sample_count": 30,
            },
            {
                "arm": "unknown",
                "measure_id": "metric_a",
                "source_binding_id": "baseline-a",
                "source_workflow_path": ".github/workflows/baseline-a.yml",
                "sample_count": 99,
            },
            {
                "arm": "baseline",
                "measure_id": "unknown",
                "source_binding_id": "baseline-a",
                "source_workflow_path": ".github/workflows/baseline-a.yml",
                "sample_count": 99,
            },
            {
                "arm": "baseline",
                "measure_id": "metric_b",
                "source_binding_id": "baseline-b",
                "source_workflow_path": ".github/workflows/baseline-b.yml",
                "sample_count": "30",
            },
            {
                "arm": "baseline",
                "measure_id": "metric_b",
                "source_binding_id": "wrong-source",
                "source_workflow_path": ".github/workflows/baseline-b.yml",
                "sample_count": 99,
            },
        ],
        required=("metric_a", "metric_b"),
        allowed_sources={
            ("baseline", "metric_a"): (
                "baseline-a",
                ".github/workflows/baseline-a.yml",
            ),
            ("baseline", "metric_b"): (
                "baseline-b",
                ".github/workflows/baseline-b.yml",
            ),
            ("treatment", "metric_a"): (
                "treatment-a",
                ".github/workflows/treatment-a.yml",
            ),
            ("treatment", "metric_b"): (
                "treatment-b",
                ".github/workflows/treatment-b.yml",
            ),
        },
    )

    assert counts == {
        "baseline": {"metric_a": 31, "metric_b": 0},
        "treatment": {"metric_a": 0, "metric_b": 30},
    }


def test_missing_names_each_underfilled_arm_measure() -> None:
    missing = _missing(
        metric_counts={
            "baseline": {"a": 30, "b": 29},
            "treatment": {"a": 0, "b": 30},
        },
        guard_counts={
            "baseline": {"g": 30},
            "treatment": {"g": 29},
        },
        minimum=30,
    )

    assert missing == (
        "baseline:metric:b:29/30",
        "treatment:guard:g:29/30",
        "treatment:metric:a:0/30",
    )


def test_log_record_contains_counts_but_no_operational_identifiers() -> None:
    inventory = CohortEvidenceInventory(
        window_start=NOW,
        window_end=NOW,
        candidate_action_outcomes=1,
        candidate_resolved_incidents=2,
        candidate_changes=3,
        candidate_cost_units=4,
        metric_counts={"baseline": {"a": 0}, "treatment": {"a": 0}},
        guard_counts={"baseline": {"g": 0}, "treatment": {"g": 0}},
        minimum_sample_size=30,
        ready=False,
        missing=("baseline:metric:a:0/30",),
    )

    record = inventory.to_log_record()

    assert record["candidate_resolved_incidents"] == 2
    assert set(record) == {
        "window_start",
        "window_end",
        "candidate_action_outcomes",
        "candidate_resolved_incidents",
        "candidate_changes",
        "candidate_cost_units",
        "metric_counts",
        "guard_counts",
        "minimum_sample_size",
        "ready",
        "missing",
    }


@pytest.mark.parametrize("revision", ["main", "HEAD", "0123456789abcdef"])
def test_inventory_source_requires_an_immutable_revision(revision: str) -> None:
    with pytest.raises(ValueError, match="immutable full 40- or 64-hex"):
        PostgresCohortEvidenceInventorySource(
            dsn="postgresql://example",
            policy=POLICY,
            expected_revision=revision,
        )


async def test_measure_query_groups_the_single_bound_projection() -> None:
    class _Cursor:
        async def fetchall(self) -> list[dict[str, object]]:
            return []

    class _Connection:
        query = ""
        params: tuple[object, ...] = ()

        async def execute(
            self,
            query: str,
            params: tuple[object, ...],
        ) -> _Cursor:
            self.query = query
            self.params = params
            return _Cursor()

    source = PostgresCohortEvidenceInventorySource(
        dsn="postgresql://example",
        policy=POLICY,
        expected_revision=REVISION,
    )
    connection = _Connection()

    rows = await source._measure_counts(  # type: ignore[arg-type]
        connection,
        action_kind="measurement.cohort.metric.v1",
        identifier_key="metric_id",
        window_start=NOW,
        window_end=NOW,
    )

    assert rows == []
    assert "GROUP BY 1, 2, 3, 4" in connection.query
    assert "entry->>'synthetic' = 'false'" in connection.query
    assert "source_cluster_digest" in connection.query
    assert "observation_digest" in connection.query
    assert "source_binding_id" in connection.query
    assert "source_workflow_path" in connection.query
    assert "observed_at" in connection.query
    assert "::TIMESTAMPTZ >= %s" in connection.query
    assert "jsonb_typeof(entry->'value') = 'number'" in connection.query
    assert connection.query.count("%s") == len(connection.params) == 11
    assert REVISION in connection.params
