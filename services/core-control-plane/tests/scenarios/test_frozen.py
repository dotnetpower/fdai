"""Frozen scenario-set integrity + balance + validity tests.

W2.4 exit criterion: no customer values, English-only, every scenario carries
both success and guard expectations, balance across domains.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

import pytest
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import JsonSchemaContractValidator
from jsonschema import Draft202012Validator

SCENARIO_DIR = Path(__file__).resolve().parent / "v2026.07"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.json"
MANIFEST_SCHEMA_PATH = Path(__file__).resolve().parent / "manifest.schema.json"
MANIFEST_PATH = Path(__file__).resolve().parent / "manifests" / "v2026.07.json"

# ── Guard patterns ──────────────────────────────────────────────────────────
# Any GUID whose first four groups are non-zero is a real customer identifier
# and MUST NOT appear in a committed scenario file. The synthetic pattern
# `00000000-0000-0000-0000-XXXXXXXXXXXX` (used to keep scenario event_ids
# unique) is exempt.
_NONZERO_GUID = re.compile(
    r"\b(?!00000000-0000-0000-0000-[0-9a-fA-F]{12}\b)"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def _load_scenario_schema() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def _load_scenarios() -> list[tuple[Path, dict[str, Any]]]:
    files = sorted(path for path in SCENARIO_DIR.glob("*.json") if path.name != "manifest.json")
    return [(p, cast(dict[str, Any], json.loads(p.read_text(encoding="utf-8")))) for p in files]


def _load_manifest() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))


def _test_ref_exists(test_ref: str) -> bool:
    relative_path, separator, test_name = test_ref.partition("::")
    if not separator:
        return False
    path = Path(__file__).resolve().parents[4] / relative_path
    if not path.is_file():
        return False
    pattern = re.compile(rf"^(?:async )?def {re.escape(test_name)}\(", re.MULTILINE)
    return pattern.search(path.read_text(encoding="utf-8")) is not None


# ---------------------------------------------------------------------------
# Schema validity
# ---------------------------------------------------------------------------


def test_scenario_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(_load_scenario_schema())


def test_capability_manifest_is_schema_valid() -> None:
    schema = cast(dict[str, Any], json.loads(MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8")))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_load_manifest())


def test_capability_manifest_assigns_every_scenario_exactly_once() -> None:
    scenarios = {raw["id"]: raw for _, raw in _load_scenarios()}
    manifest = _load_manifest()
    assigned: list[str] = []
    for capability, pack in manifest["capability_packs"].items():
        for scenario_id in pack["scenario_ids"]:
            assert scenarios[scenario_id]["capability"] == capability
            assigned.append(scenario_id)
    assert sorted(assigned) == sorted(scenarios)
    assert len(assigned) == len(set(assigned))


def test_capability_coverage_references_owned_scenarios_and_tests() -> None:
    manifest = _load_manifest()
    for pack in manifest["capability_packs"].values():
        scenario_ids = set(pack["scenario_ids"])
        for evidence_records in pack["coverage"].values():
            for evidence in evidence_records:
                assert evidence["scenario_id"] in scenario_ids
                assert _test_ref_exists(evidence["test_ref"])


def test_complete_pack_requires_every_coverage_dimension() -> None:
    manifest = _load_manifest()
    for pack in manifest["capability_packs"].values():
        expected_pack_status = (
            "missing"
            if not pack["scenario_ids"]
            else "complete"
            if all(pack["coverage"].values())
            else "partial"
        )
        assert pack["status"] == expected_pack_status
        if pack["status"] == "complete":
            assert all(pack["coverage"].values())
    expected_status = (
        "complete"
        if all(pack["status"] == "complete" for pack in manifest["capability_packs"].values())
        else "incomplete"
    )
    assert manifest["status"] == expected_status


@pytest.mark.parametrize(("path", "raw"), _load_scenarios())
def test_scenario_passes_its_schema(path: Path, raw: dict[str, Any]) -> None:
    validator = Draft202012Validator(_load_scenario_schema())
    errors = sorted(validator.iter_errors(raw), key=lambda e: list(e.path))
    assert not errors, f"{path.name}: {[e.message for e in errors[:5]]}"


@pytest.mark.parametrize(("path", "raw"), _load_scenarios())
def test_scenario_event_passes_event_schema(path: Path, raw: dict[str, Any]) -> None:
    """Every scenario event MUST validate against Event schema."""
    registry = PackageResourceSchemaRegistry()
    contract_v = JsonSchemaContractValidator(registry)
    contract_v.validate("event", raw["event"])


# ---------------------------------------------------------------------------
# Balance
# ---------------------------------------------------------------------------


def test_scenarios_balanced_within_10_percent_of_mean() -> None:
    per_domain: dict[str, int] = {}
    for _, raw in _load_scenarios():
        per_domain[raw["domain"]] = per_domain.get(raw["domain"], 0) + 1

    assert set(per_domain) == {"change", "dr", "finops"}, f"Missing a domain: {set(per_domain)}"
    mean = sum(per_domain.values()) / len(per_domain)
    for domain, count in per_domain.items():
        deviation = abs(count - mean) / mean
        assert deviation <= 0.10, (
            f"Domain {domain} deviates {deviation:.0%} from the mean count {mean:.1f}"
        )


# ---------------------------------------------------------------------------
# Customer-agnosticness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("path", "raw"), _load_scenarios())
def test_scenario_carries_no_non_zero_guid(path: Path, raw: dict[str, Any]) -> None:
    """Every UUID literal in a committed scenario MUST be the all-zero placeholder."""
    body = json.dumps(raw)
    matches = _NONZERO_GUID.findall(body)
    assert not matches, f"{path.name} contains customer-identifying GUIDs: {matches[:3]}"


@pytest.mark.parametrize(("path", "raw"), _load_scenarios())
def test_scenario_has_english_only_prose(path: Path, raw: dict[str, Any]) -> None:
    """Hangul + CJK in a scenario file is a bug."""
    body = path.read_text(encoding="utf-8")
    korean_or_cjk = re.compile(r"[\uac00-\ud7a3\u1100-\u11ff\u4e00-\u9fff]")
    hits = korean_or_cjk.findall(body)
    assert not hits, f"{path.name} contains non-ASCII natural-language text"


# ---------------------------------------------------------------------------
# Coverage - success + guard together
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("path", "raw"), _load_scenarios())
def test_every_scenario_declares_both_success_and_guard(path: Path, raw: dict[str, Any]) -> None:
    expected = raw["expected"]
    # Success side (routing decision).
    assert expected["tier"] in ("t0", "t1", "t2"), path.name
    assert expected["decision"] in ("auto", "hil", "abstain", "deny"), path.name
    # Guard side.
    guard = expected["guard"]
    for k in ("should_execute", "should_rollback", "should_trigger_policy_violation"):
        assert isinstance(guard[k], bool), f"{path.name}: guard.{k} must be bool"


@pytest.mark.parametrize(("path", "raw"), _load_scenarios())
def test_scenario_id_matches_filename(path: Path, raw: dict[str, Any]) -> None:
    """Filename MUST derive from id (dots → dashes) so grep / audit are easy."""
    expected = raw["id"].replace(".", "-") + ".json"
    assert path.name == expected, f"{path.name} does not match id-derived filename {expected}"
