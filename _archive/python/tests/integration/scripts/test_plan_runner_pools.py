"""Plan every pool exactly once; do not turn incomplete observations into mutations."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from scripts.automation.plan_runner_pools import plans

ROOT = Path(__file__).resolve().parents[3]
POLICY = json.loads((ROOT / "config/ci-runner-pools.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 10, 30, tzinfo=UTC)


def _snapshots() -> dict:
    return {
        "schema_version": 1,
        "quotas": {"container_cpu": 500, "vm_cpu": 66},
        "pools": {
            name: {
                "observed_at": NOW.isoformat(),
                "queued_runnable": 0,
                "runners": [],
                "low_demand_since": None,
                "complete": True,
            }
            for name in POLICY["pools"]
        },
    }


def test_fresh_empty_pools_request_warm_reserves_without_mutating() -> None:
    result = plans(POLICY, _snapshots(), NOW)
    assert {name: item["start_count"] for name, item in result["pool_plans"].items()} == {
        "control": 2,
        "general": 8,
        "docker": 2,
    }
    assert result["mutations_executed"] == 0
    assert result["authority"] == "none"


def test_starting_and_ready_runners_are_counted_once() -> None:
    snapshots = _snapshots()
    general = snapshots["pools"]["general"]
    general["queued_runnable"] = 4
    general["runners"] = [
        {"id": f"execution-{i}", "state": state, "since": NOW.isoformat()}
        for i, state in enumerate(["idle"] * 4 + ["starting"] * 4 + ["busy"] * 2)
    ]
    result = plans(POLICY, snapshots, NOW)["pool_plans"]["general"]
    assert result["start_count"] == 4


def test_missing_pool_or_duplicate_cross_pool_identity_is_refused() -> None:
    snapshots = _snapshots()
    del snapshots["pools"]["docker"]
    with pytest.raises(ValueError, match="exactly"):
        plans(POLICY, snapshots, NOW)
    snapshots = _snapshots()
    runner = {"id": "shared", "state": "idle", "since": NOW.isoformat()}
    snapshots["pools"]["control"]["runners"] = [runner]
    snapshots["pools"]["general"]["runners"] = [runner]
    with pytest.raises(ValueError, match="multiple pools"):
        plans(POLICY, snapshots, NOW)


def test_stale_pool_blocks_decisions_instead_of_starting_replacements() -> None:
    snapshots = _snapshots()
    snapshots["pools"]["general"]["observed_at"] = (NOW - timedelta(seconds=61)).isoformat()
    result = plans(POLICY, snapshots, NOW)["pool_plans"]["general"]
    assert result["blocked_reason"]
    assert result["start_count"] == 0
    assert not result["drain_ids"]


def test_no_apply_mode_is_silently_accepted() -> None:
    policy = copy.deepcopy(POLICY)
    policy["mode"] = "apply"
    with pytest.raises(ValueError, match="plan-only"):
        plans(policy, _snapshots(), NOW)


def test_shared_quota_shortage_blocks_the_entire_mutation_plan() -> None:
    snapshot = _snapshots()
    snapshot["quotas"]["container_cpu"] = 257
    result = plans(POLICY, snapshot, NOW)
    assert all(item["start_count"] == 0 for item in result["pool_plans"].values())
    assert all("shared_quota" in item["blocked_reason"] for item in result["pool_plans"].values())
