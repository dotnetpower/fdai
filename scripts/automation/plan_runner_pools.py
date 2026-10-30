#!/usr/bin/env python3
"""Produce bounded scale decisions from complete pool snapshots without executing mutations."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation.runner_pool_policy import (  # noqa: E402
    PoolPolicy,
    PoolSnapshot,
    RunnerSnapshot,
    plan_capacity,
)


def timestamp(raw: object, field: str) -> datetime:
    if not isinstance(raw, str):
        raise ValueError(f"{field} must be an ISO timestamp")
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        raise ValueError(f"{field} requires an explicit timezone")
    return parsed


def plans(policy: dict[str, Any], observations: dict[str, Any], now: datetime) -> dict[str, Any]:
    if not isinstance(policy, dict) or not isinstance(observations, dict):
        raise ValueError("policy and observations must be objects")
    if policy.get("schema_version") != 1 or policy.get("mode") != "plan":
        raise ValueError("supported plan-only policy is required")
    if observations.get("schema_version") != 1:
        raise ValueError("pool snapshot schema v1 is required")
    if (
        not isinstance(policy.get("pools"), dict)
        or not isinstance(observations.get("pools"), dict)
        or not isinstance(observations.get("quotas"), dict)
        or not all(isinstance(item, dict) for item in policy["pools"].values())
        or not all(isinstance(item, dict) for item in observations["pools"].values())
    ):
        raise ValueError("pool and quota mappings must be objects")
    if set(policy["pools"]) != {"control", "general", "docker"}:
        raise ValueError("control, general and docker pool policy is required")
    if set(policy["pools"]) != set(observations["pools"]):
        raise ValueError("pool snapshots must cover exactly the configured pools")
    quota_totals: dict[str, int] = {}
    for config in policy["pools"].values():
        group = config["quota_group"]
        if group not in {"container_cpu", "vm_cpu"}:
            raise ValueError("unknown quota group")
        for field in ("maximum", "cpu_per_runner"):
            if (
                isinstance(config[field], bool)
                or not isinstance(config[field], int)
                or config[field] < 1
            ):
                raise ValueError(f"{field} must be a positive integer")
        quota_totals[group] = quota_totals.get(group, 0) + (
            config["maximum"] * config["cpu_per_runner"]
        )
    if set(observations["quotas"]) != set(quota_totals):
        raise ValueError("all shared quotas must be observed")
    insufficient = []
    for group, required in quota_totals.items():
        available = observations["quotas"][group]
        if isinstance(available, bool) or not isinstance(available, int) or available < 0:
            raise ValueError("available CPU must be a nonnegative integer")
        if available < required:
            insufficient.append(group)
    seen: set[str] = set()
    result: dict[str, Any] = {}
    for name, config in policy["pools"].items():
        settings = PoolPolicy(
            pool=name,
            warm_idle=config["warm_idle"],
            maximum=config["maximum"],
            cooldown_seconds=config["cooldown_seconds"],
        )
        data = observations["pools"][name]
        if not isinstance(data["runners"], list):
            raise ValueError("runners must be a list")
        runners = []
        for item in data["runners"]:
            if not isinstance(item, dict):
                raise ValueError("runner must be an object")
            identity = item["id"]
            if not isinstance(identity, str) or not identity:
                raise ValueError("runner identity must be a nonempty string")
            if identity in seen:
                raise ValueError("one runner cannot be counted twice or assigned to multiple pools")
            seen.add(identity)
            runners.append(
                RunnerSnapshot(
                    id=identity, state=item["state"], since=timestamp(item["since"], "runner.since")
                )
            )
        snapshot = PoolSnapshot(
            observed_at=timestamp(data["observed_at"], "observed_at"),
            queued_runnable=data["queued_runnable"],
            runners=tuple(runners),
            low_demand_since=timestamp(data["low_demand_since"], "low_demand_since")
            if data.get("low_demand_since") is not None
            else None,
            complete=data["complete"],
        )
        result[name] = asdict(plan_capacity(settings, snapshot, now))
        if insufficient:
            result[name]["start_count"] = 0
            result[name]["drain_ids"] = ()
            result[name]["blocked_reason"] = "shared_quota_unavailable:" + ",".join(insufficient)
    return {
        "schema_version": 1,
        "mode": "plan",
        "observed_at": now.isoformat(),
        "pool_plans": result,
        "authority": "none",
        "mutations_executed": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=Path("config/ci-runner-pools.json"))
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = plans(
            json.loads(args.policy.read_text(encoding="utf-8")),
            json.loads(args.snapshot.read_text(encoding="utf-8")),
            datetime.now(UTC),
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"runner-pool-plan: refused incomplete or invalid input: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 1 if any(plan["blocked_reason"] for plan in result["pool_plans"].values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
