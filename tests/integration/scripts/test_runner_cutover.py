"""Infrastructure creation never proves a completed no-hosted CI cutover."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "ci_runner_cutover", ROOT / "scripts/quality/ci/check-runner-cutover.py"
)
assert SPEC is not None and SPEC.loader is not None
CUTOVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CUTOVER)


def _inventory(status: str = "online"):
    return {
        "total_count": 1,
        "runners": [
            {
                "status": status,
                "labels": [{"name": "self-hosted"}, {"name": "fdai-ci-aca"}],
            }
        ],
    }


def _receipt():
    return {
        "complete": True,
        "conclusion": "success",
        "test_count": 100,
        "environment_id": "ci-4cpu-w4",
        "jobs": [{"conclusion": "success", "labels": ["self-hosted", "fdai-ci-aca"]}],
    }


def test_hosted_control_jobs_keep_the_cutover_incomplete() -> None:
    result = CUTOVER.assess(
        {"jobs": {"verify": {"runs-on": "ubuntu-24.04"}}}, _inventory(), _receipt()
    )
    assert result["ready"] is False
    assert result["hosted_jobs"] == ["verify"]


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", None])
def test_a_failed_or_missing_live_run_does_not_authorize_cutover(conclusion: str | None) -> None:
    receipt = _receipt()
    receipt["conclusion"] = conclusion
    result = CUTOVER.assess(
        {"jobs": {"test": {"runs-on": ["self-hosted", "fdai-ci-aca"]}}},
        _inventory(),
        receipt,
    )
    assert result["ready"] is False


def test_an_offline_pool_and_an_unproven_elastic_route_are_named() -> None:
    result = CUTOVER.assess(
        {"jobs": {"test": {"runs-on": ["self-hosted", "fdai-ci-aca"]}}},
        _inventory("offline"),
        None,
    )
    assert result["ready"] is False
    assert result["unavailable_self_hosted_jobs"] == ["test"]
    assert result["elastic_success_evidence"] is False


def test_a_complete_snapshot_needs_no_secret_values() -> None:
    result = CUTOVER.assess(
        {"jobs": {"test": {"runs-on": ["self-hosted", "fdai-ci-aca"]}}},
        _inventory(),
        _receipt(),
    )
    assert result["ready"] is True
    assert result["credential_values_inspected"] is False


def test_paginated_inventory_is_not_an_absence_claim() -> None:
    inventory = _inventory()
    inventory["total_count"] = 2
    with pytest.raises(ValueError, match="incomplete"):
        CUTOVER.assess({"jobs": {}}, inventory, None)
