"""Integration tests for the Issue #2128 operational acceptance rehearsal."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/deployment/local/rehearse_operational_acceptance.py"


def _load_rehearsal_module() -> Any:
    spec = importlib.util.spec_from_file_location("rehearse_operational_acceptance", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def test_operational_acceptance_rehearsal_verifies_all_seven_criteria() -> None:
    module = _load_rehearsal_module()
    receipt = await module.run_rehearsal()

    assert receipt["kind"] == "fdai.operational-acceptance-receipt.v1"
    assert receipt["issue"] == 2128

    c1 = receipt["criterion_1_identity"]
    assert c1["authenticated"] is True
    assert "Owner" in c1["roles"]
    assert str(c1["principal_digest"]).startswith("sha256:")
    assert str(c1["owners_group_digest"]).startswith("sha256:")

    c2 = receipt["criterion_2_code_scanning"]
    assert c2["repository_alias"] == "aks-store-demo"
    assert c2["connected_initial_enabled"] is False
    assert c2["governed_enable_status"] == "published"
    assert c2["finding_decision"] == "open"
    assert c2["no_finding_decision"] == "clear"

    c3 = receipt["criterion_3_notifications"]
    assert c3["channels_converged"] == ["slack-ops-prd", "teams-ops-prd"]
    assert len(c3["receipt_ids"]["teams-ops-prd"]) == 64
    assert len(c3["receipt_ids"]["slack-ops-prd"]) == 64

    c4 = receipt["criterion_4_stewardship"]
    assert c4["schema_version"] == 2
    assert c4["maintainer_count"] == 2
    assert c4["total_agents"] == 15
    assert c4["autonomous_agents"] == 1
    assert c4["warnings_count"] == 0
    assert c4["is_clean"] is True
    assert c4["deployment_readiness"] == "ready"
    assert c4["identity_health_transitions"] == ["degraded", "healthy"]

    c5 = receipt["criterion_5_incident_pipeline"]
    assert c5["incident_count"] == 1
    assert c5["thor_shadow_mode"] is True
    assert c5["thor_outcome"] == "shadow_success"
    assert c5["managed_resource_mutations"] == 0
    assert c5["saga_audit_entries"] >= 10

    c6 = receipt["criterion_6_correlated_receipts"]
    assert c6["duplicate_upload_reused"] is True
    assert c6["merge_notification_outcome"] == "no_eligible_channels"
    assert c6["single_operator_receipt"]["original_quorum"] == 2
    assert c6["single_operator_receipt"]["effective_quorum"] == 1
    assert c6["single_operator_receipt"]["self_review"] is True

    c7 = receipt["criterion_7_replay_idempotency"]
    assert c7 == {
        "duplicate_incidents": 0,
        "duplicate_notifications": 0,
        "duplicate_audit_transitions": 0,
        "duplicate_handover_records": 0,
    }


def test_operational_acceptance_cli_writes_json_receipt(tmp_path: Path) -> None:
    module = _load_rehearsal_module()
    output_file = tmp_path / "issue-2128-receipt.json"
    exit_code = module.main(["--output", str(output_file)])
    assert exit_code == 0
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["issue"] == 2128
    assert payload["criterion_4_stewardship"]["deployment_readiness"] == "ready"
