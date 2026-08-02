from __future__ import annotations

import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SCHEMA = json.loads((HERE / "schema.json").read_text(encoding="utf-8"))
MANIFEST = json.loads((HERE / "v2026.08-planning.json").read_text(encoding="utf-8"))


def test_operational_planning_manifest_is_complete_and_schema_valid() -> None:
    Draft202012Validator.check_schema(SCHEMA)
    Draft202012Validator(SCHEMA).validate(MANIFEST)
    dimensions = [scenario["dimension"] for scenario in MANIFEST["scenarios"]]
    assert len(dimensions) == len(set(dimensions)) == 9
    evidence_statuses = [scenario["evidence_status"] for scenario in MANIFEST["scenarios"]]
    assert (MANIFEST["status"] == "complete") is all(
        status == "verified" for status in evidence_statuses
    )


def test_operational_planning_manifest_exposes_release_evidence_gaps() -> None:
    proxies = {
        scenario["dimension"]
        for scenario in MANIFEST["scenarios"]
        if scenario["evidence_status"] == "proxy"
    }

    assert MANIFEST["status"] == "partial"
    assert proxies == {"partial_failure_recovery", "a3e_non_applicability"}


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
    assert "Palantir" not in text
    assert re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}", text) is None
