"""Integrity checks for the complete v2026.10 capability corpus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from tests.scenarios import test_v2026_09_frozen as v09

_ROOT = Path(__file__).resolve().parent
_SCENARIO_DIR = _ROOT / "v2026.10"
_ENRICHMENT_DIR = _ROOT / "enrichment" / "v2026.10"
_CONFLICT_DIR = _ROOT / "cross-objective"
_MANIFEST_PATH = _ROOT / "manifests" / "v2026.10.json"
_MANIFEST_SCHEMA_PATH = _ROOT / "manifest.schema.json"
_OUTCOME_TEST_PATH = "services/core-control-plane/tests/scenarios/test_v2026_10_outcomes.py"
_REVIEWED_OUTCOMES = {
    "sre": (
        "recovery_and_recurrence_closure",
        "sre.cluster-diagnostics-missing.001",
        f"{_OUTCOME_TEST_PATH}::test_sre_outcome_closes_recovery_and_recurrence",
    ),
    "arb_change_safety": (
        "approval_conditions_and_post_change_verification",
        "change.vm-managed-identity-missing.004",
        (
            f"{_OUTCOME_TEST_PATH}::"
            "test_arb_outcome_binds_approval_conditions_and_post_change_verification"
        ),
    ),
    "finops": (
        "realized_savings_with_reliability_valid",
        "finops.stop-idle-dev-vm-off-hours.003",
        f"{_OUTCOME_TEST_PATH}::test_finops_outcome_requires_realized_savings_and_reliability",
    ),
    "dr": (
        "data_integrity_and_measured_rto_rpo",
        "dr.backup-vault-restore-rehearsal.002",
        f"{_OUTCOME_TEST_PATH}::test_dr_outcome_binds_integrity_and_measured_rto_rpo",
    ),
    "chaos": (
        "human_approved_injection_and_verified_recovery",
        "dr.chaos-experiment-novel.003",
        (
            f"{_OUTCOME_TEST_PATH}::"
            "test_chaos_outcome_requires_human_approval_continuous_guards_and_recovery"
        ),
    ),
}


def _load(path: Path) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        v09._load_json_without_duplicates(path.read_text(encoding="utf-8")),
    )


def _normalize_version(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_version(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_version(item) for item in value]
    if isinstance(value, str):
        return value.replace("v2026.10", "v2026.09").replace(
            "v2026-10",
            "v2026-09",
        )
    return value


def _json_files(path: Path) -> dict[str, dict[str, Any]]:
    return {item.name: _load(item) for item in sorted(path.glob("*.json"))}


def test_v2026_10_corpus_preserves_the_reviewed_v2026_09_replay_inputs() -> None:
    old_scenarios = _json_files(_ROOT / "v2026.09")
    new_scenarios = _json_files(_SCENARIO_DIR)
    old_enrichments = _json_files(_ROOT / "enrichment" / "v2026.09")
    new_enrichments = _json_files(_ENRICHMENT_DIR)

    assert new_scenarios.keys() == old_scenarios.keys()
    assert new_enrichments.keys() == old_enrichments.keys()
    assert {
        name: _normalize_version(payload) for name, payload in new_scenarios.items()
    } == old_scenarios
    assert {
        name: _normalize_version(payload) for name, payload in new_enrichments.items()
    } == old_enrichments

    old_conflicts = {
        item.name.replace("v2026.09-", "", 1): _load(item)
        for item in sorted(_CONFLICT_DIR.glob("v2026.09-*.json"))
    }
    new_conflicts = {
        item.name.replace("v2026.10-", "", 1): _normalize_version(_load(item))
        for item in sorted(_CONFLICT_DIR.glob("v2026.10-*.json"))
    }
    assert new_conflicts == old_conflicts


def test_v2026_10_manifest_is_schema_valid_and_inventory_complete() -> None:
    manifest = _load(_MANIFEST_PATH)
    schema = _load(_MANIFEST_SCHEMA_PATH)
    errors = sorted(Draft202012Validator(schema).iter_errors(manifest), key=str)
    assert not errors, [error.message for error in errors]
    assert manifest["scenario_set_version"] == "v2026.10"
    assert manifest["status"] == "complete"

    scenario_ids = {payload["id"] for payload in _json_files(_SCENARIO_DIR).values()}
    enrichment_ids = {payload["scenario_id"] for payload in _json_files(_ENRICHMENT_DIR).values()}
    manifest_scenario_ids = {
        scenario_id
        for pack in manifest["capability_packs"].values()
        for scenario_id in pack["scenario_ids"]
    }
    conflict_ids = {_load(path)["id"] for path in sorted(_CONFLICT_DIR.glob("v2026.10-*.json"))}
    manifest_conflict_ids = {
        conflict_id
        for pack in manifest["capability_packs"].values()
        for conflict_id in pack["conflict_spec_ids"]
    }
    assert scenario_ids == enrichment_ids == manifest_scenario_ids
    assert conflict_ids == manifest_conflict_ids


def test_v2026_10_completion_uses_only_reviewed_replay_and_outcome_bindings() -> None:
    manifest = _load(_MANIFEST_PATH)
    for capability, pack in manifest["capability_packs"].items():
        assert pack["status"] == "complete"
        scenario_ids = frozenset(pack["scenario_ids"])
        for dimension, evidence_items in pack["coverage"].items():
            assert evidence_items
            for evidence in evidence_items:
                assert evidence["scenario_id"] in scenario_ids
                assert v09._test_ref_exists(evidence["test_ref"])
                assert v09._coverage_ref_supports_claim(
                    dimension,
                    evidence["test_ref"],
                    evidence["scenario_id"],
                )

        outcome_id, scenario_id, test_ref = _REVIEWED_OUTCOMES[capability]
        outcome = pack["required_outcome"]
        assert outcome == {
            "id": outcome_id,
            "status": "complete",
            "evidence": [{"scenario_id": scenario_id, "test_ref": test_ref}],
        }
        assert v09._test_ref_exists(test_ref)


def test_v2026_10_new_manifest_remains_customer_agnostic() -> None:
    manifest = _load(_MANIFEST_PATH)
    findings = v09._customer_data_findings(manifest)
    assert not findings
    assert not v09._NONZERO_GUID.findall(json.dumps(manifest))
    assert not v09._non_ascii_machine_fields(manifest)
