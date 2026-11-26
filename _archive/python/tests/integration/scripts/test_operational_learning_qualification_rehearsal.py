"""Integration tests for the Issue #2194 operational learning qualification rehearsal."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/deployment/local/rehearse_operational_learning_qualification.py"


def _load_rehearsal_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "rehearse_operational_learning_qualification", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def test_operational_learning_qualification_rehearsal_verifies_all_nine_criteria() -> None:
    module = _load_rehearsal_module()
    receipt = await module.run_rehearsal()

    assert receipt["kind"] == "fdai.operational-learning-qualification-receipt.v1"
    assert receipt["issue"] == 2194
    assert len(receipt["receipt_sha256"]) == 64

    c1 = receipt["criterion_1_scope_selection"]
    assert c1["venue"] == "local-isolated-validation"
    assert str(c1["scope_manifest_digest"]).startswith("sha256:")
    assert c1["refused_unauthorized_venues"] == ["runtime", "port:5432", "production-unscoped"]

    c2 = receipt["criterion_2_coherent_final_qualifier"]
    assert c2["purpose_id"] == "retained-pattern-final-qualification"
    assert str(c2["receipt_digest"]).startswith("sha256:")
    assert str(c2["tuple_digest"]).startswith("sha256:")
    assert c2["baseline_preserved"] is True

    c3 = receipt["criterion_3_withdrawals_and_bounds"]
    assert c3["withdrawal_count"] == 7
    assert c3["baseline_preserved_across_all"] is True

    c4 = receipt["criterion_4_server_owned_bindings"]
    assert str(c4["authentication_receipt_digest"]).startswith("sha256:")
    assert c4["registered_action_type"] == "ops.restart-service"
    assert len(c4["measured_statistics_ref"]) == 64

    c5 = receipt["criterion_5_frozen_provenance_and_retention"]
    assert c5["qualified_interventions_count"] == 1
    assert c5["unknown_preserved_count"] == 1
    assert c5["rebuild_accepted_episodes"] == 1
    assert c5["rebuild_held_episodes"] == 1

    c6 = receipt["criterion_6_predeclared_gates_and_deduplication"]
    assert str(c6["gate_plan_digest"]).startswith("sha256:")
    assert c6["gates_passed"] is True
    assert c6["baseline_excluded_retries"] == 1
    assert c6["baseline_excluded_duplicates"] == 1
    assert c6["baseline_independent_episodes"] == 5
    assert c6["challenger_independent_episodes"] == 5

    c7 = receipt["criterion_7_frozen_t1_and_shadow_intake"]
    assert c7["evaluated_events"] == 8
    assert c7["baseline_selections_preserved"] == 8
    assert c7["withdrawal_rejections_verified"] == 7
    assert c7["execution_authority_granted"] is False
    assert c7["promotion_authority_granted"] is False

    c8 = receipt["criterion_8_separate_metrics_and_uncertainty"]
    assert c8["gates_passed"] is True
    assert c8["challenger"]["recovery"]["recovery_rate"] == 1.0
    assert c8["challenger"]["recurrence"]["recurrence_rate"] == 0.0
    assert c8["challenger"]["rollback_and_side_effects"]["rollback_rate"] == 0.0
    assert c8["challenger"]["abstention_and_coverage"]["recommendation_coverage"] == 0.8
    assert c8["challenger"]["prediction_and_calibration"]["interval_coverage"] == 1.0

    c9 = receipt["criterion_9_no_fabricated_policy_effect"]
    assert c9["policy_effect_claimed"] is False
    assert c9["unverified_claim_blocked"] is True


def test_operational_learning_qualification_cli_writes_json_receipt(tmp_path: Path) -> None:
    module = _load_rehearsal_module()
    output_file = tmp_path / "issue-2194-receipt.json"
    exit_code = module.main(["--output", str(output_file)])
    assert exit_code == 0
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["issue"] == 2194
    assert payload["criterion_6_predeclared_gates_and_deduplication"]["gates_passed"] is True
