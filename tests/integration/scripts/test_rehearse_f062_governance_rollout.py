"""Integration tests for the Issue #2204 F06.2 governance rollout rehearsal."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/governance/rehearse_f062_governance_rollout.py"
BUILD_SCRIPT_PATH = ROOT / "scripts/governance/build-governance-qualification.py"
LEDGER_PATH = ROOT / "docs/roadmap-implementation/rules-and-detection/rule-governance.md"
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")

EXPECTED_RECORD_DIGEST = "sha256:09b4b4000c366cdc85b4553502f7bf5f01a63f6ecdd20b403973e65e8120db3e"
EXPECTED_SOURCES_DIGEST = "sha256:861e05f2eb1f8ead976e30ea05993663471205b991431b9c3d711923a65fba6a"
EXPECTED_MEASUREMENT_DIGEST = (
    "sha256:0e5ba50f706a595b868eee4602e1a4384fd647db1b538a21a1f01bace1777cef"
)
EXPECTED_COHORT_DIGEST = "sha256:f9a31af1871e254242c2bc3c1b4e28d6ac7fab8ed10332fee6727380b4182f40"


def _load_rehearsal_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "rehearse_f062_governance_rollout",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def test_f062_governance_rollout_rehearsal_satisfies_all_13_criteria() -> None:
    module = _load_rehearsal_module()
    summary = await module.run_f062_qualification_rehearsal()

    assert summary["schema_version"] == "fdai.f062-governance-rollout-receipt.v1"
    assert summary["issue"] == 2204
    assert summary["authority"] == "none"

    c1 = summary["criterion_1_binding"]
    assert c1["installation_id"] == "installation-fdai-dev-wus3"
    assert c1["management_scope_id"] == "scope-ed8b63ea22cd3133"
    assert c1["environment_class"] == "development"
    assert c1["provider_count"] == 12

    c23 = summary["criterion_2_3_nine_phase_migration"]
    assert c23["upgrade_release_id"] == "release-1.1.1"
    assert c23["forward_release_id"] == "release-1.1.2"
    assert c23["rollback_release_id"] == "release-1.1.1-rb"
    assert c23["audit_chain_verified"] is True

    c4 = summary["criterion_4_provider_collection"]
    assert c4["admitted_count"] == 12
    assert c4["holds_count"] == 0
    assert c4["sources_digest"] == EXPECTED_SOURCES_DIGEST

    c56 = summary["criterion_5_6_governance_review"]
    assert "self_approval" in c56["self_approval_denied_codes"]
    assert "quorum_not_met" in c56["sub_quorum_denied_codes"]
    assert c56["cleared_allowed"] is True
    assert c56["cleared_original_quorum"] == 2
    assert c56["cleared_effective_quorum"] == 1
    assert c56["cleared_self_review"] is True

    c7 = summary["criterion_7_exemption_expiry"]
    assert c7["linked_live_audit_id"] == "exemption-expiry-digest:f8a9ebb21cdcb07587e89e91e457396d"
    assert c7["first_sweep"] == {
        "evaluated": 2,
        "alerted": 1,
        "expired_due": 1,
        "commands_published": 1,
    }
    assert c7["second_sweep"] == {
        "evaluated": 2,
        "alerted": 0,
        "expired_due": 0,
        "commands_published": 0,
    }

    c8 = summary["criterion_8_override_discovery"]
    assert c8["signal_count"] == 1
    assert c8["integrated_count"] == 1
    assert c8["override_trigger_rate"] == 1.0
    assert c8["norns_self_admission_rejected"] is True

    c910 = summary["criterion_9_10_activation_and_convergence"]
    assert c910["replica_convergence_verified"] is True
    assert c910["offline_generation_digest"] == c910["rollback_generation_digest"]
    assert c910["direct_generation_digest"] != c910["offline_generation_digest"]

    c11 = summary["criterion_11_frozen_cohort"]
    assert c11["cohort_digest"] == EXPECTED_COHORT_DIGEST
    assert c11["measurement_digest"] == EXPECTED_MEASUREMENT_DIGEST
    assert c11["total"] == 24
    assert c11["independent_groups"] == 24
    assert c11["coverage"] == 1.0
    assert c11["false_positive_rate"] == 0.0
    assert c11["false_negative_rate"] == 0.0
    assert c11["false_negative_rate_worst_case"] == 0.0

    c12 = summary["criterion_12_explicit_holds"]
    assert c12["blocked_readiness"] == "blocked"
    assert c12["verified_hold_reasons"] == [
        "conflicting",
        "duplicate_conflict",
        "incomplete",
        "missing_required",
        "observed_after_cutoff",
        "revoked",
        "stale",
        "unavailable",
    ]

    c13 = summary["criterion_13_qualification_record"]
    assert c13["readiness"] == "ready_for_review"
    assert c13["record_digest"] == EXPECTED_RECORD_DIGEST
    assert c13["sources_digest"] == EXPECTED_SOURCES_DIGEST
    assert c13["measurement_digest"] == EXPECTED_MEASUREMENT_DIGEST
    assert c13["ledger_missing_digests"] == []


def test_f062_governance_rollout_rehearsal_cli_writes_deterministic_receipt(
    tmp_path: Path,
) -> None:
    module = _load_rehearsal_module()
    output_file = tmp_path / "f062-receipt.json"
    exit_code = module.main(["--output", str(output_file)])
    assert exit_code == 0
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["criterion_13_qualification_record"]["record_digest"] == EXPECTED_RECORD_DIGEST


async def test_f062_governance_rollout_reconciles_with_rule_governance_ledger_digests() -> None:
    ledger_text = LEDGER_PATH.read_text(encoding="utf-8")
    cited_digests = set(_DIGEST_RE.findall(ledger_text))
    assert EXPECTED_RECORD_DIGEST in cited_digests
    assert EXPECTED_SOURCES_DIGEST in cited_digests
    assert EXPECTED_MEASUREMENT_DIGEST in cited_digests


def test_build_governance_qualification_matches_rehearsal_record_digest() -> None:
    rehearsal = _load_rehearsal_module()
    spec = importlib.util.spec_from_file_location(
        "build_governance_qualification",
        BUILD_SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = builder
    spec.loader.exec_module(builder)

    document = {
        "binding": {
            "installation_id": rehearsal.INSTALLATION_ID,
            "management_scope_id": rehearsal.MANAGEMENT_SCOPE_ID,
            "environment_class": rehearsal.ENVIRONMENT_CLASS,
            "rule_generation_digest": rehearsal.RULE_GENERATION_DIGEST,
            "ontology_release_digest": rehearsal.ONTOLOGY_RELEASE_DIGEST,
            "provider_revisions": dict(rehearsal.PROVIDER_REVISIONS),
            "evidence_cutoff": rehearsal.CUTOFF.isoformat(),
        },
        "required_source_ids": sorted(rehearsal.PROVIDER_REVISIONS),
        "max_age_seconds": 3600,
        "observations": [
            {
                "source_id": source_id,
                "scope_id": rehearsal.MANAGEMENT_SCOPE_ID,
                "identity_ref": f"uami-observer-{source_id}",
                "state": "available",
                "observed_at": "2026-11-03T23:55:00+00:00",
                "evidence_digest": rehearsal._digest_for(f"provider-obs:{source_id}:{revision}"),
            }
            for source_id, revision in sorted(rehearsal.PROVIDER_REVISIONS.items())
        ],
        "cohort": {
            "digest": EXPECTED_COHORT_DIGEST,
            "cases": [
                *(
                    {
                        "case_id": f"violation-{idx:02d}",
                        "group_id": f"rg-violation-{idx:02d}",
                        "truth": "violation",
                        "verdict": "flagged",
                    }
                    for idx in range(1, 13)
                ),
                *(
                    {
                        "case_id": f"compliant-{idx:02d}",
                        "group_id": f"rg-compliant-{idx:02d}",
                        "truth": "compliant",
                        "verdict": "not_flagged",
                    }
                    for idx in range(1, 13)
                ),
            ],
        },
    }
    output, readiness = builder.build(document)
    assert readiness.value == "ready_for_review"
    assert output["record_digest"] == EXPECTED_RECORD_DIGEST
    assert output["sources_digest"] == EXPECTED_SOURCES_DIGEST
    assert output["measurement"]["digest"] == EXPECTED_MEASUREMENT_DIGEST


async def test_f062_governance_rollout_rehearsal_postgres() -> None:
    if not os.environ.get("FDAI_DATABASE_URL"):
        pytest.skip("FDAI_DATABASE_URL is unset")
    module = _load_rehearsal_module()
    summary = await module._run_with_optional_postgres(use_postgres=True)
    assert summary["criterion_2_3_nine_phase_migration"]["audit_chain_verified"] is True
    assert summary["criterion_13_qualification_record"]["record_digest"] == EXPECTED_RECORD_DIGEST
