"""A faster failed or incomplete CI run is not performance evidence."""

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "ci_evidence_summary", ROOT / "scripts/quality/ci/summarize-ci-run.py"
)
assert SPEC is not None and SPEC.loader is not None
SUMMARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUMMARY)


def _receipt():
    return SUMMARY.summarize(
        {
            "id": 1,
            "run_attempt": 1,
            "head_sha": "a" * 40,
            "workflow_id": 7,
            "conclusion": "success",
            "status": "completed",
        },
        {
            "total_count": 1,
            "jobs": [
                {
                    "name": "regression shard 1",
                    "status": "completed",
                    "conclusion": "success",
                    "labels": ["self-hosted", "ci"],
                    "created_at": "2026-10-29T00:00:00Z",
                    "started_at": "2026-10-29T00:00:10Z",
                    "completed_at": "2026-10-29T00:01:10Z",
                }
            ],
        },
        environment_id="dedicated-ci-w4",
        test_count=100,
    )


def test_scheduling_delay_is_not_counted_as_runner_execution() -> None:
    result = _receipt()
    assert result["job_slot_seconds"] == 60
    assert result["jobs"][0]["scheduling_seconds"] == 10


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("conclusion", "failure"),
        ("complete", False),
        ("test_count", None),
        ("environment_id", None),
        ("revision", "b" * 40),
        ("test_count", 99),
        ("environment_id", "different"),
    ],
)
def test_failed_or_mismatched_results_are_not_speedups(field: str, value: object) -> None:
    baseline = _receipt()
    candidate = copy.deepcopy(baseline)
    candidate[field] = value
    candidate["job_slot_seconds"] = 1
    with pytest.raises(ValueError):
        SUMMARY.compare(baseline, candidate)


def test_runner_scope_and_failed_jobs_must_match_successful_evidence() -> None:
    baseline = _receipt()
    candidate = copy.deepcopy(baseline)
    candidate["jobs"][0]["labels"] = ["ubuntu-24.04"]
    with pytest.raises(ValueError, match="runner labels"):
        SUMMARY.compare(baseline, candidate)
    candidate = copy.deepcopy(baseline)
    candidate["jobs"][0]["conclusion"] = "failure"
    with pytest.raises(ValueError, match="successful"):
        SUMMARY.compare(baseline, candidate)


def test_complete_comparable_runs_report_only_measured_slot_time() -> None:
    baseline = _receipt()
    candidate = copy.deepcopy(baseline)
    candidate["job_slot_seconds"] = 30
    assert SUMMARY.compare(baseline, candidate) == {"job_slot_seconds_change_percent": -50}


def test_incomplete_pagination_is_refused() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        SUMMARY.summarize({}, {"total_count": 2, "jobs": []}, environment_id=None, test_count=None)
