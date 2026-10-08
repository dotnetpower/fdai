#!/usr/bin/env python3
"""Compare inert Azure Policy translation candidates with live Azure Policy compliance state.

Usage (operator-approved live read; local loopback database only):
    FDAI_STATE_STORE_DSN=... uv run python \\
        scripts/deployment/local/run-azure-policy-differential.py \\
        --candidates <translate output dir> --snapshot-tree <collector snapshot tree>

For each candidate, the script reads the policy's compliance states through Azure Resource Graph
with the Azure CLI identity, finds the same resources in the active local inventory snapshot, and
evaluates the candidate Rego with the real OPA evaluator. A state is compared only when the policy
definition version matches the candidate, any non-effect parameter the condition reads is
provably the default, and the resource carries every property the candidate requires; otherwise
it is counted as skipped or abstained. Any mismatch blocks the candidate, and a candidate is
eligible for the quality gate only after it also agrees on at least one non-compliant resource.
Output carries counts only, never resource identifiers, and nothing is written to the catalog or
the database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg
import yaml
from fdai.core.tiers.t0_deterministic import OpaRegoEvaluator
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.shared.contracts.models import Rule

_ARG = "https://management.azure.com/providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01"
_AUDIENCE = "https://management.azure.com/.default"
_MAX_PAGES = 50
_STALE_HOURS = 48


async def _policy_states(names: list[str]) -> list[dict[str, Any]]:
    identity = AsyncAzureCliWorkloadIdentity.from_env()
    token = await identity.get_token(_AUDIENCE)
    quoted = ", ".join(f"'{name}'" for name in names)
    query = (
        "policyresources | where type =~ 'microsoft.policyinsights/policystates' "
        f"| where tolower(tostring(properties.policyDefinitionName)) in ({quoted}) "
        "| project resource=tolower(tostring(properties.resourceId)), "
        "definition=tolower(tostring(properties.policyDefinitionName)), "
        "state=tostring(properties.complianceState), "
        "version=tostring(properties.policyDefinitionVersion), "
        "parameters=properties.policyAssignmentParameters, "
        "in_set=isnotempty(tostring(properties.policySetDefinitionName)), "
        "timestamp=format_datetime(todatetime(properties.timestamp), 'yyyy-MM-dd HH:mm:ss')"
    )
    rows: list[dict[str, Any]] = []
    body: dict[str, Any] = {"query": query, "options": {"$top": 1000}}
    async with httpx.AsyncClient(timeout=60) as client:
        for _page in range(_MAX_PAGES):
            response = await client.post(
                _ARG, json=body, headers={"Authorization": f"Bearer {token.token}"}
            )
            response.raise_for_status()
            payload = response.json()
            rows.extend(payload.get("data", []))
            skip = payload.get("$skipToken")
            if not skip:
                return rows
            body["options"]["$skipToken"] = skip
    raise SystemExit("policy state listing exceeded its page bound")


def _inventory(dsn: str, references: set[str]) -> tuple[dict[str, dict[str, Any]], datetime]:
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT lower(r.provider_ref), r.resource_type, r.props, a.updated_at "
            "FROM inventory_snapshot_resource r "
            "JOIN inventory_active a ON r.snapshot_id = a.snapshot_id "
            "WHERE lower(r.provider_ref) = ANY(%s)",
            (sorted(references),),
        )
        rows = cursor.fetchall()
        cursor.execute("SELECT updated_at FROM inventory_active")
        active = cursor.fetchone()
    if active is None:
        raise SystemExit("no active inventory snapshot")
    return {
        reference: {"type": resource_type, "props": props}
        for reference, resource_type, props, _updated in rows
    }, active[0]


def _parameters_are_default(
    row: dict[str, Any], candidate: dict[str, Any], keys: list[str]
) -> bool:
    if not keys:
        return True
    if row.get("in_set"):
        # Initiative parameters map onto definition parameters through the set; not verified here.
        return False
    raw = row.get("parameters")
    values = json.loads(raw) if isinstance(raw, str) and raw else raw or {}
    defaults = candidate["defaults"]
    return all(
        key not in values
        or (isinstance(values[key], dict) and values[key].get("value") == defaults.get(key))
        for key in keys
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--snapshot-tree", type=Path, required=True)
    args = parser.parse_args()
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "")
    if not dsn:
        print("FDAI_STATE_STORE_DSN is required", file=sys.stderr)
        return 2
    candidates: dict[str, dict[str, Any]] = {}
    for path in sorted((args.candidates / "candidates").glob("*.yaml")):
        guid = path.stem
        translation = json.loads(path.with_name(f"{guid}.translation.json").read_text())
        parsed = Rule.model_validate(yaml.safe_load(path.read_text()))
        definition = next(
            json.loads(item.read_text())
            for item in sorted(args.snapshot_tree.rglob("*.json"))
            if guid in item.read_text()[:4096]
            and str(json.loads(item.read_text()).get("name", "")).casefold() == guid
        )
        parameters = definition["properties"].get("parameters") or {}
        candidates[guid] = {
            "rule": parsed,
            "translation": translation,
            "defaults": {key: value.get("defaultValue") for key, value in parameters.items()},
        }
    states = asyncio.run(_policy_states(sorted(candidates)))
    inventory, inventory_time = _inventory(dsn, {str(row["resource"]) for row in states})
    evaluator = OpaRegoEvaluator(policies_root=args.candidates / "policies")
    outcomes: dict[str, Counter[str]] = {guid: Counter() for guid in candidates}
    for row in states:
        candidate = candidates[str(row["definition"])]
        counter = outcomes[str(row["definition"])]
        rule: Rule = candidate["rule"]
        state = str(row["state"])
        if state not in {"Compliant", "NonCompliant"}:
            counter["skipped_state"] += 1
            continue
        if str(row["version"]) != rule.version:
            counter["skipped_version"] += 1
            continue
        if not _parameters_are_default(
            row, candidate, candidate["translation"]["condition_parameters"]
        ):
            counter["skipped_parameters"] += 1
            continue
        observed = datetime.strptime(str(row["timestamp"]), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        if abs((inventory_time - observed).total_seconds()) > _STALE_HOURS * 3600:
            counter["skipped_stale"] += 1
            continue
        resource = inventory.get(str(row["resource"]))
        if resource is None or resource["type"] != rule.resource_type:
            counter["abstained_not_in_inventory"] += 1
            continue
        props = resource["props"]
        if any(item.rsplit(".", 1)[-1] not in props for item in rule.evaluates):
            counter["abstained_property_unobserved"] += 1
            continue
        result = evaluator.evaluate(rule, props)
        if result is None:
            counter["abstained_not_evaluable"] += 1
            continue
        agrees = result.denied == (state == "NonCompliant")
        counter[f"{'matched' if agrees else 'mismatched'}_{state.lower()}"] += 1
    report: dict[str, Any] = {"inventory_snapshot_at": inventory_time.astimezone(UTC).isoformat()}
    for guid, counter in sorted(outcomes.items()):
        mismatched = counter["mismatched_compliant"] + counter["mismatched_noncompliant"]
        matched = counter["matched_compliant"] + counter["matched_noncompliant"]
        # Agreement only on compliant resources can't tell a working check from one that never
        # denies, so the quality gate also needs a matched non-compliant resource.
        decision = (
            "blocked"
            if mismatched
            else "eligible_for_quality_gate"
            if counter["matched_noncompliant"]
            else "agreement_without_violations"
            if matched
            else "inconclusive"
        )
        report[guid] = {"decision": decision, **dict(sorted(counter.items()))}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
