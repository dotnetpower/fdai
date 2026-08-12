from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
SCHEMA = json.loads((HERE / "schema.json").read_text(encoding="utf-8"))
MANIFEST = json.loads((HERE / "v2026.08-planning.json").read_text(encoding="utf-8"))
EVIDENCE_CONFIG = json.loads(
    (ROOT / "config/ohl-scale-out-evidence.json").read_text(encoding="utf-8")
)
EVIDENCE_SCHEMA = json.loads(
    (ROOT / "config/ohl-scale-out-evidence.schema.json").read_text(encoding="utf-8")
)
RUNBOOK = (ROOT / "docs/runbooks/ohl-scale-out-evidence.md").read_text(encoding="utf-8")


def test_operational_planning_manifest_is_complete_and_schema_valid() -> None:
    Draft202012Validator.check_schema(SCHEMA)
    Draft202012Validator(SCHEMA).validate(MANIFEST)
    dimensions = [scenario["dimension"] for scenario in MANIFEST["scenarios"]]
    assert len(dimensions) == len(set(dimensions)) == 9
    evidence_statuses = [scenario["evidence_status"] for scenario in MANIFEST["scenarios"]]
    assert (MANIFEST["status"] == "complete") is (
        all(status == "verified" for status in evidence_statuses)
        and EVIDENCE_CONFIG["status"] == "complete"
    )


def test_operational_planning_manifest_exposes_release_evidence_gaps() -> None:
    proxies = {
        scenario["dimension"]
        for scenario in MANIFEST["scenarios"]
        if scenario["evidence_status"] == "proxy"
    }

    assert MANIFEST["status"] == "partial"
    assert proxies == {"partial_failure_recovery"}


def test_ohl_scale_out_evidence_contract_is_bounded_and_schema_valid() -> None:
    Draft202012Validator.check_schema(EVIDENCE_SCHEMA)
    Draft202012Validator(EVIDENCE_SCHEMA).validate(EVIDENCE_CONFIG)

    assert EVIDENCE_CONFIG["status"] == "prepared"
    assert EVIDENCE_CONFIG["action_type_ref"] == "ops.scale-out@1.0.0"
    assert EVIDENCE_CONFIG["target"]["max_targets"] == 1
    assert EVIDENCE_CONFIG["target"]["environment"] == "non_production"
    assert EVIDENCE_CONFIG["target"]["orchestration_mode"] == "Uniform"
    assert EVIDENCE_CONFIG["execution"]["azure_apply_allowed"] is False
    assert EVIDENCE_CONFIG["execution"]["max_capacity_delta"] == 1
    assert {
        "approval",
        "dry_run",
        "stop_condition",
        "logical_target_lock",
        "idempotency",
        "audit_intent",
        "automation_hold",
        "rollback",
        "independent_recovery",
    } <= set(EVIDENCE_CONFIG["evidence"]["required_receipts"])
    assert EVIDENCE_CONFIG["observation"] == {
        "prediction_horizon_seconds": 300,
        "telemetry_grace_seconds": 300,
        "metric_observation_window_seconds": 60,
        "recurrence_window_seconds": 1209600,
        "minimum_live_shadow_days": 14,
    }
    assert EVIDENCE_CONFIG["acceptance"]["minimum_live_shadow_samples"] == 100
    assert EVIDENCE_CONFIG["acceptance"]["minimum_accuracy"] == 0.98
    assert EVIDENCE_CONFIG["acceptance"]["max_policy_escapes"] == 0
    assert EVIDENCE_CONFIG["acceptance"]["require_verified_rollback"] is True
    assert EVIDENCE_CONFIG["acceptance"]["require_verified_cleanup"] is True
    assert EVIDENCE_CONFIG["acceptance"]["allow_synthetic_live_evidence"] is False
    assert "synthetic" in EVIDENCE_CONFIG["evidence"]["common_receipt_fields"]
    assert {
        "prediction_digest",
        "horizon_end",
        "active_model_refs",
        "challenger_model_refs",
        "invariant_evidence_digests",
        "mode",
        "execution_authority",
    } <= set(EVIDENCE_CONFIG["evidence"]["graph_prediction_fields"])
    assert {
        "prediction_digest",
        "observation_digest",
        "observer_executor_distinct",
        "censoring_refs",
        "active_model_mutated",
        "promotion_applied",
    } <= set(EVIDENCE_CONFIG["evidence"]["graph_outcome_fields"])
    assert EVIDENCE_CONFIG["result"] == {
        "status": "pending",
        "source_receipt_digest": None,
        "completed_at": None,
    }


def test_ohl_scale_out_completion_transition_requires_verified_live_evidence() -> None:
    incomplete = deepcopy(EVIDENCE_CONFIG)
    incomplete["status"] = "complete"
    incomplete["evidence_level"] = "live_execution"
    errors = tuple(Draft202012Validator(EVIDENCE_SCHEMA).iter_errors(incomplete))

    assert errors

    complete = deepcopy(incomplete)
    complete["result"] = {
        "status": "verified",
        "source_receipt_digest": "a" * 64,
        "completed_at": "2026-08-26T00:00:00Z",
    }
    complete["residuals"] = []

    Draft202012Validator(EVIDENCE_SCHEMA).validate(complete)


def test_ohl_scale_out_runbook_pins_exact_live_and_rollback_commands() -> None:
    required_commands = (
        "az account show --query id --output tsv",
        'az resource show --ids "$FDAI_OHL_TARGET_RESOURCE_ID"',
        'az vmss show --subscription "$FDAI_OHL_EXPECTED_SUBSCRIPTION_ID"',
        'az vmss scale --ids "$FDAI_OHL_TARGET_RESOURCE_ID"',
        'az vmss wait --ids "$FDAI_OHL_TARGET_RESOURCE_ID" --updated',
        'az vmss list-instances --subscription "$FDAI_OHL_EXPECTED_SUBSCRIPTION_ID"',
        'az monitor activity-log list --resource-id "$FDAI_OHL_TARGET_RESOURCE_ID"',
    )
    for command in required_commands:
        assert command in RUNBOOK
    assert "terraform apply" not in RUNBOOK
    assert "azd up" not in RUNBOOK
    assert "az deployment" not in RUNBOOK
    assert "synthetic evidence is not live evidence" in RUNBOOK.lower()


def test_operational_planning_scenarios_reference_executable_tests() -> None:
    for scenario in MANIFEST["scenarios"]:
        relative, separator, test_name = scenario["test_ref"].partition("::")
        assert separator
        path = ROOT / relative
        assert path.is_file(), scenario["test_ref"]
        source = path.read_text(encoding="utf-8")
        assert re.search(rf"^(?:async )?def {re.escape(test_name)}\(", source, re.MULTILINE)


def test_operational_planning_manifest_is_customer_agnostic_and_product_neutral() -> None:
    text = (HERE / "v2026.08-planning.json").read_text(encoding="utf-8")
    assert re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}", text) is None
