"""A capacity plan is not a successful no-hosted runner rollout."""

from __future__ import annotations

import copy
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "runner_pool_readiness", ROOT / "scripts/quality/ci/runner-pool-readiness.py"
)
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
POLICY = json.loads((ROOT / "config/ci-runner-pools.json").read_text(encoding="utf-8"))
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
NOW = datetime(2026, 10, 30, tzinfo=UTC)


def _evidence() -> dict:
    return {
        "schema_version": 1,
        "complete": True,
        "observed_at": NOW.isoformat(),
        "trusted_control_bootstrap": True,
        "fork_admission": True,
        "busy_drain_interlock": True,
        "short_lived_registration_broker": True,
        "controller_scope_verified": True,
        "active_routes": dict(POLICY["jobs"]),
        "quotas": {"container_cpu": 500, "vm_cpu": 66},
        "pools": {
            name: {
                "available_cpu": item["maximum"] * item["cpu_per_runner"],
                "actual_maximum": item["maximum"],
                "ready_idle": item["warm_idle"],
                "exclusive_reconciler": True,
                "provider_trigger_type": "Manual",
                "idle_drain_protocol": "atomic-idle-reservation",
                "manager_credentials_isolated": True,
                "successful_job": True,
                "scale_out_verified": True,
                "safe_drain_verified": True,
            }
            for name, item in POLICY["pools"].items()
        },
    }


@pytest.mark.parametrize("minutes", [0, 361, True, 360.5])
def test_job_execution_budget_must_fit_the_worker_lifetime(minutes) -> None:
    workflow = copy.deepcopy(WORKFLOW)
    workflow["jobs"]["changes"]["timeout-minutes"] = minutes
    with pytest.raises(ValueError):
        CHECK.validate_policy(POLICY, workflow)


@pytest.mark.parametrize("low", [-1, 9, True])
def test_low_demand_reserve_cannot_exceed_warm_capacity(low) -> None:
    policy = copy.deepcopy(POLICY)
    policy["pools"]["general"]["warm_idle_low"] = low
    with pytest.raises(ValueError):
        CHECK.validate_policy(policy, WORKFLOW)


def test_policy_accounts_for_every_ci_job_and_docker_capability() -> None:
    CHECK.validate_policy(POLICY, WORKFLOW)
    assert POLICY["mode"] == "plan"
    assert POLICY["jobs"]["db-integration"] == "docker"
    assert POLICY["pools"]["general"]["warm_idle"] == 8
    assert POLICY["pools"]["general"]["maximum"] == 64


def test_new_workflow_jobs_cannot_escape_pool_inventory() -> None:
    workflow = copy.deepcopy(WORKFLOW)
    workflow["jobs"]["new-unclassified-job"] = {"runs-on": "ubuntu-24.04"}
    with pytest.raises(ValueError, match="inventory"):
        CHECK.validate_policy(POLICY, workflow)


@pytest.mark.parametrize("value", [True, -1, 0.5])
def test_invalid_capacity_cannot_be_a_successful_plan(value: object) -> None:
    policy = copy.deepcopy(POLICY)
    policy["pools"]["general"]["maximum"] = value
    with pytest.raises(ValueError):
        CHECK.validate_policy(policy, WORKFLOW)


def test_service_container_job_cannot_be_routed_to_non_docker_pool() -> None:
    policy = copy.deepcopy(POLICY)
    policy["jobs"]["db-integration"] = "general"
    with pytest.raises(ValueError, match="Docker"):
        CHECK.validate_policy(policy, WORKFLOW)


def test_ready_evidence_is_an_observation_and_never_grants_execution() -> None:
    workflow = copy.deepcopy(WORKFLOW)
    for name, pool in POLICY["jobs"].items():
        workflow["jobs"][name]["runs-on"] = POLICY["pools"][pool]["labels"]
    receipt = CHECK.assess(POLICY, workflow, _evidence(), NOW)
    assert receipt["ready"] is True
    assert receipt["routing_changed"] is False
    assert receipt["authority"] == "none"


def test_snapshot_claims_cannot_override_the_actual_workflow_runner_selection() -> None:
    receipt = CHECK.assess(POLICY, WORKFLOW, _evidence(), NOW)
    assert receipt["ready"] is False
    assert "changes:workflow-source-route-not-on-control" in receipt["blockers"]


@pytest.mark.parametrize("seconds", [-1, 61])
def test_stale_or_future_inventory_is_refused(seconds: int) -> None:
    evidence = _evidence()
    evidence["observed_at"] = (NOW - timedelta(seconds=seconds)).isoformat()
    with pytest.raises(ValueError, match="fresh"):
        CHECK.assess(POLICY, WORKFLOW, evidence, NOW)


@pytest.mark.parametrize(
    ("field", "value", "blocker"),
    [
        ("ready_idle", 0, "warm-reserve-not-ready"),
        ("available_cpu", 100, "cpu-quota"),
        ("exclusive_reconciler", False, "exclusive-reconciler"),
        ("manager_credentials_isolated", False, "management-identity"),
        ("safe_drain_verified", False, "safe_drain_verified"),
        ("actual_maximum", 24, "configured-ceiling-not-applied"),
    ],
)
def test_quota_warm_capacity_and_single_ownership_are_independent_requirements(
    field: str, value: object, blocker: str
) -> None:
    evidence = _evidence()
    evidence["pools"]["general"][field] = value
    receipt = CHECK.assess(POLICY, WORKFLOW, evidence, NOW)
    assert receipt["ready"] is False
    assert any(blocker in item for item in receipt["blockers"])


def test_fork_and_current_routing_prerequisites_are_not_ignored() -> None:
    evidence = _evidence()
    evidence["fork_admission"] = False
    evidence["active_routes"]["python-tests"] = "hosted"
    receipt = CHECK.assess(POLICY, WORKFLOW, evidence, NOW)
    assert "fork_admission-unverified" in receipt["blockers"]
    assert "python-tests:route-not-on-general" in receipt["blockers"]


def test_shared_cpu_is_not_double_counted_between_control_and_general_pools() -> None:
    evidence = _evidence()
    evidence["quotas"]["container_cpu"] = 257
    result = CHECK.assess(POLICY, WORKFLOW, evidence, NOW)
    assert "container_cpu:shared-cpu-quota:257<260" in result["blockers"]


def test_keda_and_external_starts_cannot_both_claim_scaling_ownership() -> None:
    evidence = _evidence()
    evidence["pools"]["general"]["provider_trigger_type"] = "Event"
    result = CHECK.assess(POLICY, WORKFLOW, evidence, NOW)
    assert "general:external-reconciler-conflicts-with-provider-scaling" in result["blockers"]


def test_idle_observation_alone_does_not_close_the_assignment_drain_race() -> None:
    evidence = _evidence()
    evidence["pools"]["docker"]["idle_drain_protocol"] = "read-idle-then-delete"
    result = CHECK.assess(POLICY, WORKFLOW, evidence, NOW)
    assert "docker:idle-drain-race-unresolved" in result["blockers"]


def _burst() -> dict:
    return {
        "complete": True,
        "successful": True,
        "kind": "burst",
        "pool": "general",
        "expected_jobs": 8,
        "requested_concurrency": 8,
        "peak_concurrency": 8,
        "busy_jobs_interrupted": 0,
        "scaled_to_reserve": True,
        "jobs": [
            {"job_id": value, "conclusion": "success", "queue_seconds": value} for value in range(8)
        ],
    }


def test_burst_report_is_measured_not_an_unlimited_zero_wait_guarantee() -> None:
    receipt = CHECK.validate_burst(POLICY, _burst())
    assert receipt["passed"] is True
    assert receipt["queue_p99_seconds"] == 7
    assert "not a population guarantee" in receipt["statistical_limit"]


@pytest.mark.parametrize("field", ["complete", "successful", "scaled_to_reserve"])
def test_failed_incomplete_or_unproven_drain_does_not_pass(field: str) -> None:
    burst = _burst()
    burst[field] = False
    with pytest.raises(ValueError):
        CHECK.validate_burst(POLICY, burst)


def test_burst_duplicates_and_unstarted_work_do_not_pass() -> None:
    burst = _burst()
    burst["jobs"][1]["job_id"] = 0
    with pytest.raises(ValueError, match="duplicated"):
        CHECK.validate_burst(POLICY, burst)
    burst = _burst()
    burst["peak_concurrency"] = 7
    with pytest.raises(ValueError, match="incomplete"):
        CHECK.validate_burst(POLICY, burst)


def test_queue_slo_failure_is_not_hidden_by_successful_tests() -> None:
    burst = _burst()
    burst["jobs"][0]["queue_seconds"] = 121
    assert CHECK.validate_burst(POLICY, burst)["passed"] is False


def test_warm_reserve_has_a_stricter_queue_target_than_a_cold_burst() -> None:
    burst = _burst()
    for row in burst["jobs"]:
        row["queue_seconds"] = 20
    assert CHECK.validate_burst(POLICY, burst)["passed"] is True
    burst["kind"] = "warm"
    assert CHECK.validate_burst(POLICY, burst)["passed"] is False


def test_boolean_interruption_count_is_not_accepted_as_zero() -> None:
    burst = _burst()
    burst["busy_jobs_interrupted"] = False
    with pytest.raises(ValueError, match="integer"):
        CHECK.validate_burst(POLICY, burst)


def test_exceeding_the_safety_ceiling_is_not_a_passing_performance_result() -> None:
    burst = _burst()
    burst["peak_concurrency"] = 65
    with pytest.raises(ValueError, match="ceiling"):
        CHECK.validate_burst(POLICY, burst)


def test_policy_only_preflight_is_not_a_live_ready_claim(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert CHECK.main(["--check-policy"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {"policy_valid": True, "mode": "plan", "authority": "none"}
    assert "ready" not in result


@pytest.mark.parametrize("value", [[], None, "not-an-object"])
def test_invalid_evidence_shapes_fail_explicitly(value: object) -> None:
    with pytest.raises(ValueError, match="object"):
        CHECK.assess(POLICY, WORKFLOW, value, NOW)
