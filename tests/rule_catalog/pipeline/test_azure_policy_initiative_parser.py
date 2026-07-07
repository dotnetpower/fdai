"""Unit tests for the Azure Policy initiative parser.

The parser is exercised end-to-end against the real
``/tmp/azure-policy-clone`` snapshot in
``tests/rule_catalog/pipeline/test_collect.py``. These focused tests
lock down the *shape* of each :class:`ParsedRule.raw` so a future
refactor cannot silently drop a field the collector CLI depends on
when it joins initiatives with the imported ``azure-builtin`` GUID
map.

The unit tests are intentionally decoupled from any on-disk snapshot:
each test synthesises a minimal ``policySetDefinition`` JSON tree in
``tmp_path`` and asserts against the parser's structured output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fdai.rule_catalog.pipeline.parse.azure_policy_initiative import (
    AzurePolicyInitiativeParser,
)
from fdai.rule_catalog.pipeline.parse.parser import ParseError, ParserName


def _write(path: Path, doc: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _def_ref(guid: str) -> dict[str, object]:
    return {
        "policyDefinitionId": (f"/providers/Microsoft.Authorization/policyDefinitions/{guid}"),
    }


def test_parse_reports_name_and_empty_root_raises(tmp_path: Path) -> None:
    parser = AzurePolicyInitiativeParser()
    assert parser.name is ParserName.AZURE_POLICY_JSON

    missing = tmp_path / "does-not-exist"
    with pytest.raises(ParseError, match="snapshot root does not exist"):
        parser.parse(missing)


def test_parse_extracts_full_profile_intent(tmp_path: Path) -> None:
    doc = {
        "properties": {
            "displayName": "CIS Microsoft Azure Foundations Benchmark 1.4",
            "description": "Curated CIS baseline.",
            "policyType": "BuiltIn",
            "version": "1.2.3",
            "metadata": {"category": "Regulatory Compliance"},
            "policyDefinitions": [
                _def_ref("00000000-0000-0000-0000-000000000001"),
                _def_ref("00000000-0000-0000-0000-000000000002"),
            ],
        }
    }
    _write(tmp_path / "cis14" / "policySetDefinition.json", doc)

    report = AzurePolicyInitiativeParser().parse(tmp_path)
    assert report.parser is ParserName.AZURE_POLICY_JSON
    assert len(report.rules) == 1
    raw = dict(report.rules[0].raw)
    assert raw["kind"] == "azure-policy-initiative"
    assert raw["profile_title"] == "CIS Microsoft Azure Foundations Benchmark 1.4"
    assert raw["category"] == "Regulatory Compliance"
    assert raw["version"] == "1.2.3"
    assert list(raw["policy_definition_guids"]) == [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    ]
    # profile_id is a stable slug (category + display name).
    assert raw["profile_id"].startswith("compliance.regulatory-compliance.")


def test_parse_skips_non_initiative_documents(tmp_path: Path) -> None:
    # Looks like a policy definition, not an initiative.
    _write(
        tmp_path / "not-initiative.json",
        {"properties": {"displayName": "just a rule", "policyRule": {}}},
    )
    report = AzurePolicyInitiativeParser().parse(tmp_path)
    assert report.rules == ()


def test_parse_drops_initiatives_with_missing_display_name(tmp_path: Path) -> None:
    _write(
        tmp_path / "no-name.json",
        {"properties": {"policyDefinitions": [_def_ref("00000000-0000-0000-0000-0000000000aa")]}},
    )
    report = AzurePolicyInitiativeParser().parse(tmp_path)
    assert report.rules == ()


def test_parse_normalises_bad_version_to_default(tmp_path: Path) -> None:
    _write(
        tmp_path / "v.json",
        {
            "properties": {
                "displayName": "Weird Version",
                "policyType": "BuiltIn",
                "version": "not-a-semver",
                "policyDefinitions": [_def_ref("00000000-0000-0000-0000-0000000000bb")],
            }
        },
    )
    report = AzurePolicyInitiativeParser().parse(tmp_path)
    assert len(report.rules) == 1
    assert report.rules[0].raw["version"] == "1.0.0"


def test_parse_tolerates_malformed_definition_refs(tmp_path: Path) -> None:
    _write(
        tmp_path / "mixed.json",
        {
            "properties": {
                "displayName": "Mixed",
                "policyType": "BuiltIn",
                "policyDefinitions": [
                    _def_ref("00000000-0000-0000-0000-0000000000cc"),
                    {"policyDefinitionId": "garbage"},  # dropped
                    "not-even-a-dict",  # dropped
                ],
            }
        },
    )
    report = AzurePolicyInitiativeParser().parse(tmp_path)
    guids = list(report.rules[0].raw["policy_definition_guids"])
    assert guids == ["00000000-0000-0000-0000-0000000000cc"]


def test_parse_rejects_invalid_json(tmp_path: Path) -> None:
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ParseError, match="not valid JSON"):
        AzurePolicyInitiativeParser().parse(tmp_path)


def test_parse_ignores_non_json_files(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# ignore me", encoding="utf-8")
    report = AzurePolicyInitiativeParser().parse(tmp_path)
    assert report.rules == ()
