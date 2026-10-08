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

``--quality-gate`` then replays every eligible candidate through the rule pipeline's quality gate
(shadow evaluation, regression gate, and promotion controller) on in-memory scenarios built from
the compared resources, with Azure Policy's compliance state as the expected outcome and synthetic
scenario identifiers. The gate's decision is reported; nothing is promoted or activated.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg
import yaml
from fdai.core.tiers.t0_deterministic import OpaRegoEvaluator
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.rule_catalog.pipeline.orchestrator import build_pipeline
from fdai.shared.contracts.models import Rule
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_ARG = "https://management.azure.com/providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01"
_AUDIENCE = "https://management.azure.com/.default"
_MAX_PAGES = 50
_STALE_HOURS = 48
_POLICY_NAME = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


async def _policy_states(names: list[str]) -> list[dict[str, Any]]:
    if any(_POLICY_NAME.fullmatch(name) is None for name in names):
        raise SystemExit("candidate policy names MUST be lowercase GUIDs")
    identity = AsyncAzureCliWorkloadIdentity.from_env()
    token = await identity.get_token(_AUDIENCE)
    quoted = ", ".join(f"'{name}'" for name in names)
    query = (
        "policyresources | where type =~ 'microsoft.policyinsights/policystates' "
        f"| where tolower(tostring(properties.policyDefinitionName)) in ({quoted}) "
        "| project resource=tolower(tostring(properties.resourceId)), "
        "definition=tolower(tostring(properties.policyDefinitionName)), "
        "resource_type=tolower(tostring(properties.resourceType)), "
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


async def _quality_gate(
    rule: Rule,
    compared: list[tuple[dict[str, Any], bool]],
    evaluator: OpaRegoEvaluator,
) -> dict[str, Any]:
    scenarios = [
        _scenario(rule, index, props, noncompliant)
        for index, (props, noncompliant) in enumerate(compared)
    ]
    run = await build_pipeline(audit_store=InMemoryStateStore(), evaluator=evaluator).run(
        candidate_rules=(rule,),
        scenario_set_id=f"azure-policy-differential::{rule.id}",
        scenarios=scenarios,
    )
    report = run.candidate_report
    return {
        "regression_outcome": str(run.decision.outcome.value),
        "failed_thresholds": list(run.decision.reasons),
        "scenarios": report.scenario_count,
        "matched": report.matched_count,
        "policy_violation_escapes": report.policy_violation_escapes,
        "decision_mismatches": report.decision_mismatches,
        "promotion_outcome": str(run.promotion.outcome.value),
    }


def _scenario(rule: Rule, index: int, props: dict[str, Any], noncompliant: bool) -> dict[str, Any]:
    scenario_id = f"{rule.id}-{index}"
    return {
        "schema_version": "1.0.0",
        "id": scenario_id,
        "version": "azure-policy-differential",
        "domain": "change",
        "tags": ["azure-policy-differential"],
        "event": {
            "schema_version": "1.0.0",
            "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, scenario_id)),
            "idempotency_key": scenario_id,
            "source": "azure-policy-differential",
            "event_type": "change_detected",
            "detected_at": "2026-10-08T00:00:00Z",
            "ingested_at": "2026-10-08T00:00:01Z",
            "mode": "shadow",
            "payload": {
                "resource": {
                    "type": rule.resource_type,
                    "resource_id": f"{rule.resource_type}::{scenario_id}",
                    "props": props,
                }
            },
        },
        "expected": {
            "tier": "t0",
            "decision": "auto" if noncompliant else "abstain",
            "citing_rule_ids": [rule.id] if noncompliant else [],
            "guard": {
                "should_execute": False,
                "should_rollback": False,
                "should_trigger_policy_violation": noncompliant,
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--snapshot-tree", type=Path, required=True)
    parser.add_argument("--quality-gate", action="store_true")
    args = parser.parse_args()
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "")
    if not dsn:
        print("FDAI_STATE_STORE_DSN is required", file=sys.stderr)
        return 2
    candidates: dict[str, dict[str, Any]] = {}
    by_policy_type: dict[tuple[str, str], str] = {}
    for path in sorted((args.candidates / "candidates").glob("*.yaml")):
        rule_id = path.stem
        translation = json.loads(path.with_name(f"{rule_id}.translation.json").read_text())
        parsed = Rule.model_validate(yaml.safe_load(path.read_text()))
        policy = str(translation["policy_name"]).casefold()
        definition = next(
            json.loads(item.read_text())
            for item in sorted(args.snapshot_tree.rglob("*.json"))
            if policy in item.read_text()[:4096]
            and str(json.loads(item.read_text()).get("name", "")).casefold() == policy
        )
        parameters = definition["properties"].get("parameters") or {}
        candidates[rule_id] = {
            "rule": parsed,
            "translation": translation,
            "defaults": {key: value.get("defaultValue") for key, value in parameters.items()},
        }
        by_policy_type[(policy, str(translation["provider_type"]).casefold())] = rule_id
    states = asyncio.run(_policy_states(sorted({policy for policy, _ in by_policy_type})))
    inventory, inventory_time = _inventory(dsn, {str(row["resource"]) for row in states})
    evaluator = OpaRegoEvaluator(policies_root=args.candidates / "policies")
    outcomes: dict[str, Counter[str]] = {rule_id: Counter() for rule_id in candidates}
    compared: dict[str, list[tuple[dict[str, Any], bool]]] = {rule_id: [] for rule_id in candidates}
    for row in states:
        # A state for a resource type no candidate translated belongs to no comparison.
        rule_id_for_row = by_policy_type.get((str(row["definition"]), str(row["resource_type"])))
        if rule_id_for_row is None:
            continue
        candidate = candidates[rule_id_for_row]
        counter = outcomes[rule_id_for_row]
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
        compared[rule_id_for_row].append((props, state == "NonCompliant"))
        counter[f"{'matched' if agrees else 'mismatched'}_{state.lower()}"] += 1
    report: dict[str, Any] = {"inventory_snapshot_at": inventory_time.astimezone(UTC).isoformat()}
    for rule_id, counter in sorted(outcomes.items()):
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
        report[rule_id] = {"decision": decision, **dict(sorted(counter.items()))}
        if args.quality_gate and decision == "eligible_for_quality_gate":
            report[rule_id]["quality_gate"] = asyncio.run(
                _quality_gate(candidates[rule_id]["rule"], compared[rule_id], evaluator)
            )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
