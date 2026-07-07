"""Azure Policy JSON parser + imported rule schema validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from fdai.rule_catalog.pipeline.parse.azure_policy_json import (
    AzurePolicyJsonParser,
    _extract_resource_type,
    _rule_id_from_name,
)
from fdai.rule_catalog.pipeline.parse.parser import (
    ParseError,
    ParserName,
    build_parser,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]
COLLECTED_ROOT = REPO_ROOT / "rule-catalog" / "collected" / "azure-builtin"


# ---------------------------------------------------------------------------
# Dispatcher wiring
# ---------------------------------------------------------------------------


def test_build_parser_returns_azure_policy_json_impl() -> None:
    p = build_parser("azure-policy-json")
    assert isinstance(p, AzurePolicyJsonParser)
    assert p.name is ParserName.AZURE_POLICY_JSON


# ---------------------------------------------------------------------------
# Parser behavior on synthesized inputs
# ---------------------------------------------------------------------------


def _write_policy(root: Path, name: str, body: dict) -> None:
    (root / f"{name}.json").write_text(json.dumps(body), encoding="utf-8")


def _minimal_deny_policy() -> dict:
    return {
        "properties": {
            "displayName": "Storage account should require secure transfer",
            "description": "Enforce HTTPS-only.",
            "policyType": "BuiltIn",
            "mode": "Indexed",
            "metadata": {"category": "Storage", "version": "2.0.0"},
            "version": "2.0.0",
            "parameters": {
                "effect": {
                    "type": "string",
                    "defaultValue": "Deny",
                    "allowedValues": ["Audit", "Deny", "Disabled"],
                    "metadata": {"displayName": "Effect"},
                }
            },
            "policyRule": {
                "if": {
                    "allOf": [
                        {"field": "type", "equals": "Microsoft.Storage/storageAccounts"},
                        {
                            "field": "Microsoft.Storage/storageAccounts/supportsHttpsTrafficOnly",
                            "equals": "false",
                        },
                    ]
                },
                "then": {"effect": "[parameters('effect')]"},
            },
        },
        "id": "/providers/Microsoft.Authorization/policyDefinitions/foo-guid",
        "name": "foo-guid-secure-transfer",
    }


def test_parse_maps_azure_storage_to_object_storage_and_assigns_severity(tmp_path: Path) -> None:
    _write_policy(tmp_path, "secure_transfer", _minimal_deny_policy())
    parser = AzurePolicyJsonParser()
    report = parser.parse(tmp_path)
    assert report.rule_count == 1
    raw = report.rules[0].raw
    assert raw["resource_type"] == "object-storage"
    assert raw["source"] == "azure_policy"
    assert raw["severity"] == "high"  # Deny default -> high per heuristic
    assert raw["remediates"] == "remediate.azure-policy-managed"
    assert raw["check_logic"] == {
        "kind": "expression",
        "reference": "azure-policy://foo-guid-secure-transfer",
    }
    assert raw["parameters"]["azure_policy_name"] == "foo-guid-secure-transfer"


def test_parse_falls_through_to_azure_prefix_for_unknown_resource_type(tmp_path: Path) -> None:
    body = _minimal_deny_policy()
    for step in body["properties"]["policyRule"]["if"]["allOf"]:
        if step.get("field") == "type":
            step["equals"] = "Microsoft.Fabricated/somethingNew"
    _write_policy(tmp_path, "fabricated", body)
    report = AzurePolicyJsonParser().parse(tmp_path)
    assert report.rule_count == 1
    assert report.rules[0].raw["resource_type"] == "azure.fabricated.somethingnew"


def test_parse_skips_non_policy_json(tmp_path: Path) -> None:
    # tsconfig.json shape - no `properties` -> silently skipped, not an error.
    (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {}}', encoding="utf-8")
    _write_policy(tmp_path, "real", _minimal_deny_policy())
    report = AzurePolicyJsonParser().parse(tmp_path)
    assert report.rule_count == 1


def test_parse_raises_on_invalid_json(tmp_path: Path) -> None:
    (tmp_path / "broken.json").write_text("{ not valid", encoding="utf-8")
    with pytest.raises(ParseError, match="not valid JSON"):
        AzurePolicyJsonParser().parse(tmp_path)


def test_parse_raises_on_missing_snapshot(tmp_path: Path) -> None:
    with pytest.raises(ParseError, match="not a directory"):
        AzurePolicyJsonParser().parse(tmp_path / "nope")


def test_parse_is_deterministic_across_reruns(tmp_path: Path) -> None:
    _write_policy(tmp_path, "a", _minimal_deny_policy())
    _write_policy(tmp_path, "b", _minimal_deny_policy())
    p = AzurePolicyJsonParser()
    a = p.parse(tmp_path)
    b = p.parse(tmp_path)
    assert [r.origin for r in a.rules] == [r.origin for r in b.rules]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_rule_id_from_name_uses_display_slug() -> None:
    assert _rule_id_from_name("guid", "Secure Transfer Storage") == "secure-transfer-storage"


def test_rule_id_falls_back_to_uuid_when_display_empty() -> None:
    # Placeholder GUID (all-zero pattern per generic-scope.instructions.md).
    slug = _rule_id_from_name("00000000-0000-0000-0000-000000000042", "")
    assert "0000" in slug


def test_extract_resource_type_returns_azure_prefix_when_no_field() -> None:
    assert _extract_resource_type({}) == "azure.resource"


# ---------------------------------------------------------------------------
# End-to-end: sample of the actually landed collected/azure-builtin rules
# still validate against the FDAI rule schema.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rule_schema_validator() -> Draft202012Validator:
    return Draft202012Validator(dict(PackageResourceSchemaRegistry().get("rule")))


@pytest.mark.skipif(
    not COLLECTED_ROOT.is_dir(),
    reason="rule-catalog/collected/azure-builtin/ has not been generated",
)
def test_random_sample_of_collected_azure_builtin_rules_validates(
    rule_schema_validator: Draft202012Validator,
) -> None:
    """The collector wrote the rules; every one MUST validate against the
    upstream rule schema. We spot-check 20 random files across categories
    (checking all 4700+ every run would slow the whole suite)."""
    files = sorted(COLLECTED_ROOT.rglob("*.yaml"))
    assert len(files) > 100, "expected the azure-builtin tree to be populated"
    sample = files[:: max(1, len(files) // 20)][:20]
    failures: list[str] = []
    for f in sample:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        errors = list(rule_schema_validator.iter_errors(data))
        if errors:
            failures.append(f"{f.name}: {errors[0].message}")
    assert not failures, f"schema violations in collected sample: {failures}"


@pytest.mark.skipif(
    not COLLECTED_ROOT.is_dir(),
    reason="rule-catalog/collected/azure-builtin/ has not been generated",
)
def test_collected_tree_uses_the_expected_source_id() -> None:
    """Every imported rule MUST declare `source: azure_policy` so a
    consumer can distinguish auto-imported rules from hand-authored
    ones without opening the file."""
    files = sorted(COLLECTED_ROOT.rglob("*.yaml"))[:100]
    for f in files:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert data["source"] == "azure_policy", f"{f} has wrong source"
        assert data["remediates"] == "remediate.azure-policy-managed"
