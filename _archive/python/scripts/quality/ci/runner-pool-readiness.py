#!/usr/bin/env python3
"""Verify complete performance-first pool evidence; never infer readiness from a resource apply."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.quality.ci import ci_pool_canary, ci_pool_routes  # noqa: E402

DEFAULT_POLICY = Path("config/ci-runner-pools.json")


def integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}")
    return value


def validate_policy(policy: dict[str, Any], workflow: dict[str, Any]) -> None:
    if not isinstance(policy, dict) or not isinstance(workflow, dict):
        raise ValueError("policy and workflow must be objects")
    if policy.get("schema_version") != 1 or policy.get("mode") != "plan":
        raise ValueError("unsupported pool policy or automatic activation request")
    expected = {"control", "general", "docker"}
    if (
        not isinstance(policy.get("pools"), dict)
        or not isinstance(policy.get("jobs"), dict)
        or not isinstance(workflow.get("jobs"), dict)
        or not isinstance(policy.get("slo"), dict)
        or not all(isinstance(item, dict) for item in policy["pools"].values())
        or not all(isinstance(item, dict) for item in workflow["jobs"].values())
    ):
        raise ValueError("pool, job, and SLO mappings must be objects")
    if set(policy["pools"]) != expected:
        raise ValueError("control, general and docker pool policies are required")
    seen: set[tuple[str, ...]] = set()
    for name, pool in policy["pools"].items():
        warm = integer(pool["warm_idle"], f"{name}.warm_idle")
        low = integer(pool.get("warm_idle_low", warm), f"{name}.warm_idle_low")
        ceiling = integer(pool["maximum"], f"{name}.maximum", minimum=1)
        integer(pool["cpu_per_runner"], f"{name}.cpu_per_runner", minimum=1)
        if pool["quota_group"] not in {"container_cpu", "vm_cpu"}:
            raise ValueError(f"unknown quota group: {name}")
        integer(pool["cooldown_seconds"], f"{name}.cooldown_seconds", minimum=1)
        labels = pool["labels"]
        if (
            ceiling > 128
            or warm > ceiling
            or low > warm
            or not isinstance(labels, list)
            or not labels
            or not all(isinstance(item, str) and item for item in labels)
            or "self-hosted" not in labels
            or len(labels) != len(set(labels))
            or not isinstance(pool["docker"], bool)
        ):
            raise ValueError(f"invalid pool capacity, labels or capability: {name}")
        signature = tuple(sorted(labels))
        if signature in seen:
            raise ValueError("pool labels must identify distinct pools")
        seen.add(signature)
    if not policy["pools"]["docker"]["docker"]:
        raise ValueError("Docker pool must explicitly support Docker")
    if set(workflow["jobs"]) != set(policy["jobs"]):
        raise ValueError("job routing inventory differs from the complete CI workflow")
    for name, job in workflow["jobs"].items():
        if integer(job.get("timeout-minutes", 360), f"{name}.timeout-minutes", minimum=1) > 360:
            raise ValueError("runner pool CI jobs must finish within six hours")
        pool = policy["jobs"][name]
        if pool not in expected:
            raise ValueError(f"unknown pool for job: {name}")
        if job.get("services") and not policy["pools"][pool]["docker"]:
            raise ValueError(f"service containers require the Docker pool: {name}")
    slo = policy["slo"]
    for field in ("warm_queue_p95_seconds", "burst_queue_p99_seconds", "maximum_queue_seconds"):
        integer(slo[field], f"slo.{field}", minimum=1)
    stages = slo["burst_stages"]
    if not isinstance(stages, list) or not stages:
        raise ValueError("burst stages are required")
    if any(integer(stage, "burst stage", minimum=1) > 128 for stage in stages):
        raise ValueError("burst stage exceeds the supported ceiling")
    if stages != sorted(set(stages)):
        raise ValueError("burst stages must be unique and increasing")


def assess(
    policy: dict[str, Any],
    workflow: dict[str, Any],
    evidence: dict[str, Any],
    now: datetime,
    workflows: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_policy(policy, workflow)
    if not isinstance(evidence, dict):
        raise ValueError("readiness evidence must be an object")
    if evidence.get("schema_version") != 1 or evidence.get("complete") is not True:
        raise ValueError("complete evidence schema v1 is required")
    observed = datetime.fromisoformat(evidence["observed_at"])
    if (
        observed.tzinfo is None
        or now.tzinfo is None
        or not 0 <= (now - observed).total_seconds() <= 60
    ):
        raise ValueError("evidence must be timezone-aware, fresh and not future-dated")
    if (
        not isinstance(evidence.get("pools"), dict)
        or not isinstance(evidence.get("quotas"), dict)
        or not isinstance(evidence.get("active_routes"), dict)
        or not all(isinstance(item, dict) for item in evidence["pools"].values())
    ):
        raise ValueError("pool, quota and route evidence must be objects")
    if set(evidence["pools"]) != set(policy["pools"]):
        raise ValueError("evidence must account for every pool")
    blockers: list[str] = []
    quota_totals: dict[str, int] = {}
    for pool in policy["pools"].values():
        group = pool["quota_group"]
        quota_totals[group] = quota_totals.get(group, 0) + (
            pool["maximum"] * pool["cpu_per_runner"]
        )
    if set(evidence["quotas"]) != set(quota_totals):
        raise ValueError("all shared quota groups must be accounted for")
    for group, required in quota_totals.items():
        available = integer(evidence["quotas"][group], f"quotas.{group}")
        if available < required:
            blockers.append(f"{group}:shared-cpu-quota:{available}<{required}")
    for name, pool in policy["pools"].items():
        receipt = evidence["pools"][name]
        if integer(receipt["actual_maximum"], f"{name}.actual_maximum") != pool["maximum"]:
            blockers.append(f"{name}:configured-ceiling-not-applied")
        required_cpu = pool["maximum"] * pool["cpu_per_runner"]
        available = integer(receipt["available_cpu"], f"{name}.available_cpu")
        if available < required_cpu:
            blockers.append(f"{name}:cpu-quota:{available}<{required_cpu}")
        if receipt.get("exclusive_reconciler") is not True:
            blockers.append(f"{name}:exclusive-reconciler-unverified")
        if receipt.get("provider_trigger_type") != "Manual":
            blockers.append(f"{name}:external-reconciler-conflicts-with-provider-scaling")
        if receipt.get("idle_drain_protocol") != "atomic-idle-reservation":
            blockers.append(f"{name}:idle-drain-race-unresolved")
        if receipt.get("manager_credentials_isolated") is not True:
            blockers.append(f"{name}:management-identity-isolation-unverified")
        if integer(receipt["ready_idle"], f"{name}.ready_idle") < pool["warm_idle"]:
            blockers.append(f"{name}:warm-reserve-not-ready")
        for field in ("successful_job", "scale_out_verified", "safe_drain_verified"):
            if receipt.get(field) is not True:
                blockers.append(f"{name}:{field}-unverified")
    for field in (
        "trusted_control_bootstrap",
        "fork_admission",
        "busy_drain_interlock",
        "short_lived_registration_broker",
        "controller_scope_verified",
    ):
        if evidence.get(field) is not True:
            blockers.append(f"{field}-unverified")
    routing_variables = evidence.get("routing_variables", {})
    enabled = isinstance(routing_variables, dict) and (
        routing_variables.get("FDAI_CI_POOLS_ENABLED") == "true"
    )
    if not enabled:
        blockers.append("pool-flag-not-observed-enabled")
    actual_routes = evidence["active_routes"]
    if set(actual_routes) != set(policy["jobs"]):
        raise ValueError("active routing evidence is incomplete")
    for name, expected in policy["jobs"].items():
        if actual_routes[name] != expected:
            blockers.append(f"{name}:route-not-on-{expected}")
        selection = workflow["jobs"][name]["runs-on"]
        if selection != policy["pools"][expected]["labels"] and not (
            enabled
            and selection
            == ci_pool_routes.runner_expression(
                policy["pools"][expected]["labels"], ci_pool_routes.LEGACY_RUNNERS.get(name)
            )
        ):
            blockers.append(f"{name}:workflow-source-route-not-on-{expected}")
    documents = {ci_pool_routes.CI: workflow, **(workflows or {})}
    if set(documents) != set(ci_pool_routes.VALIDATION_WORKFLOWS):
        blockers.append("complete-validation-workflow-inventory-unverified")
    else:
        blockers.extend(ci_pool_routes.routing_errors(policy, documents))
        observed_routes = evidence.get("active_workflow_routes")
        expected_routes = {
            path: ci_pool_routes.job_routes(policy, path)
            for path in ci_pool_routes.VALIDATION_WORKFLOWS
        }
        if observed_routes != expected_routes:
            blockers.append("complete-validation-workflow-routes-unverified")
    return {
        "ready": not blockers,
        "blockers": blockers,
        "observed_at": observed.isoformat(),
        "authority": "none",
        "routing_changed": False,
    }


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        raise ValueError("no queue samples")
    return sorted(values)[math.ceil(len(values) * quantile) - 1]


def validate_burst(policy: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise ValueError("burst receipt must be an object")
    if receipt.get("complete") is not True or receipt.get("successful") is not True:
        raise ValueError("a complete successful burst is required")
    slo = policy["slo"]
    requested = integer(receipt["requested_concurrency"], "requested_concurrency", minimum=1)
    if requested not in slo["burst_stages"]:
        raise ValueError("requested concurrency is not a configured acceptance stage")
    if receipt.get("kind") not in {"warm", "burst"}:
        raise ValueError("queue evidence must distinguish warm and burst work")
    pool = receipt.get("pool")
    if not isinstance(pool, str) or pool not in policy["pools"]:
        raise ValueError("burst evidence must name one configured pool")
    jobs = receipt["jobs"]
    if not isinstance(jobs, list) or not all(isinstance(item, dict) for item in jobs):
        raise ValueError("burst jobs must be a list of objects")
    ids = [row["job_id"] for row in jobs]
    if not jobs or len(ids) != len(set(ids)) or len(ids) != receipt["expected_jobs"]:
        raise ValueError("burst job accounting is missing or duplicated")
    if any(row["conclusion"] != "success" for row in jobs):
        raise ValueError("failed jobs cannot establish the queue SLO")
    queues = [row["queue_seconds"] for row in jobs]
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        for value in queues
    ):
        raise ValueError("queue durations must be finite nonnegative numbers")
    expected = integer(receipt["expected_jobs"], "expected_jobs", minimum=1)
    if expected < requested:
        raise ValueError("burst contains fewer jobs than requested concurrency")
    peak = integer(receipt.get("peak_concurrency"), "peak_concurrency")
    if peak > policy["pools"][pool]["maximum"]:
        raise ValueError("observed concurrency exceeded the pool ceiling")
    if (
        integer(receipt.get("busy_jobs_interrupted"), "busy_jobs_interrupted") != 0
        or receipt.get("scaled_to_reserve") is not True
        or peak < requested
    ):
        raise ValueError("burst or safe-drain evidence is incomplete")
    p95, p99 = percentile(queues, 0.95), percentile(queues, 0.99)
    passed = p99 <= slo["burst_queue_p99_seconds"] and max(queues) <= slo["maximum_queue_seconds"]
    if receipt["kind"] == "warm":
        passed = passed and p95 <= slo["warm_queue_p95_seconds"]
    return {
        "passed": passed,
        "samples": len(queues),
        "queue_p95_seconds": p95,
        "queue_p99_seconds": p99,
        "queue_max_seconds": max(queues),
        "statistical_limit": "single-burst nearest-rank observations, not a population guarantee",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--workflow", type=Path, default=Path(".github/workflows/ci.yml"))
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--evidence", type=Path)
    operation.add_argument("--burst-receipt", type=Path)
    operation.add_argument("--canary-receipt", type=Path)
    operation.add_argument("--check-policy", action="store_true")
    args = parser.parse_args(argv)
    try:
        policy = json.loads(args.policy.read_text(encoding="utf-8"))
        workflow = yaml.safe_load(args.workflow.read_text(encoding="utf-8"))
        validate_policy(policy, workflow)
        if args.check_policy:
            result = {"policy_valid": True, "mode": "plan", "authority": "none"}
        elif args.burst_receipt:
            result = validate_burst(
                policy, json.loads(args.burst_receipt.read_text(encoding="utf-8"))
            )
        elif args.canary_receipt:
            result = ci_pool_canary.validate_receipt(
                json.loads(args.canary_receipt.read_text(encoding="utf-8")), policy["slo"]
            )
        else:
            result = assess(
                policy,
                workflow,
                json.loads(args.evidence.read_text(encoding="utf-8")),
                datetime.now(UTC),
                {
                    path: yaml.safe_load(Path(path).read_text(encoding="utf-8"))
                    for path in ci_pool_routes.VALIDATION_WORKFLOWS
                },
            )
    except (OSError, ValueError, KeyError, TypeError, ci_pool_canary.CanaryError) as error:
        print(f"runner-pools: invalid or incomplete evidence: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if args.check_policy or result.get("ready") or result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
