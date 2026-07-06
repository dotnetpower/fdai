"""Parser plugin + verifier tests.

Covers:
- ``build_parser`` dispatch (rule-yaml, unknown name, not-yet-implemented).
- :class:`RuleYamlParser` structural failure + happy paths.
- :func:`verify_parsed_rules` end-to-end round-trip through the loader,
  including duplicate-id detection.

The happy path exercises the shipped ``rule-catalog/catalog/`` — closing
the "collect → parse → verify" loop on the ``aiopspilot-p1-seed``
source without touching the network.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from aiopspilot.rule_catalog.pipeline.parse import (
    ParsedRule,
    ParseError,
    ParserName,
    ParserNotImplementedError,
    RuleYamlParser,
    build_parser,
    verify_parsed_rules,
)
from aiopspilot.rule_catalog.schema.action_type import load_action_type_catalog
from aiopspilot.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from aiopspilot.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG_ROOT = REPO_ROOT / "rule-catalog" / "catalog"
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
VOCAB_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"
POLICIES_ROOT = REPO_ROOT / "policies"
REMEDIATION_ROOT = REPO_ROOT / "rule-catalog" / "remediation"


def _schema_registry() -> PackageResourceSchemaRegistry:
    return PackageResourceSchemaRegistry()


def _action_types():  # type: ignore[no-untyped-def]
    return load_action_type_catalog(ACTION_TYPES_ROOT, schema_registry=_schema_registry())


def _resource_types():  # type: ignore[no-untyped-def]
    with VOCAB_FILE.open("r", encoding="utf-8") as fh:
        return load_resource_type_registry_from_mapping(yaml.safe_load(fh))


# ---------------------------------------------------------------------------
# build_parser dispatch
# ---------------------------------------------------------------------------


def test_build_parser_rule_yaml_returns_ruleyamlparser() -> None:
    parser = build_parser(ParserName.RULE_YAML)
    assert isinstance(parser, RuleYamlParser)
    assert parser.name is ParserName.RULE_YAML


def test_build_parser_accepts_string_name() -> None:
    parser = build_parser("rule-yaml")
    assert isinstance(parser, RuleYamlParser)


def test_build_parser_unknown_name_raises_parseerror() -> None:
    with pytest.raises(ParseError, match=r"unknown parser 'no-such-parser'"):
        build_parser("no-such-parser")


@pytest.mark.parametrize(
    "declared",
    ["azure-policy-json", "checkov-yaml", "kube-bench", "gatekeeper-templates"],
)
def test_build_parser_declared_but_unimplemented_raises_notimplemented(declared: str) -> None:
    with pytest.raises(ParserNotImplementedError, match=declared):
        build_parser(declared)


# ---------------------------------------------------------------------------
# RuleYamlParser structural checks
# ---------------------------------------------------------------------------


def test_rule_yaml_parser_rejects_non_directory(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    with pytest.raises(ParseError, match="MUST be a directory"):
        RuleYamlParser().parse(missing)


def test_rule_yaml_parser_skips_non_yaml_files(tmp_path: Path) -> None:
    (tmp_path / "readme.md").write_text("noise\n", encoding="utf-8")
    (tmp_path / "one.yaml").write_text("id: sample\n", encoding="utf-8")
    report = RuleYamlParser().parse(tmp_path)
    assert report.rule_count == 1
    assert report.rules[0].origin == "one.yaml"


def test_rule_yaml_parser_reports_bad_yaml(tmp_path: Path) -> None:
    (tmp_path / "broken.yaml").write_text("::: not: valid:\n  yaml\n", encoding="utf-8")
    with pytest.raises(ParseError, match="broken.yaml"):
        RuleYamlParser().parse(tmp_path)


def test_rule_yaml_parser_reports_wrong_toplevel(tmp_path: Path) -> None:
    (tmp_path / "list.yaml").write_text("- item1\n- item2\n", encoding="utf-8")
    with pytest.raises(ParseError, match="top-level must be a mapping"):
        RuleYamlParser().parse(tmp_path)


def test_rule_yaml_parser_is_deterministic(tmp_path: Path) -> None:
    (tmp_path / "b.yaml").write_text("id: b\n", encoding="utf-8")
    (tmp_path / "a.yaml").write_text("id: a\n", encoding="utf-8")
    first = RuleYamlParser().parse(tmp_path)
    second = RuleYamlParser().parse(tmp_path)
    assert [r.origin for r in first.rules] == ["a.yaml", "b.yaml"]
    assert [r.origin for r in first.rules] == [r.origin for r in second.rules]


# ---------------------------------------------------------------------------
# Seed loop: parse + verify on the shipped catalog
# ---------------------------------------------------------------------------


def test_rule_yaml_parser_loads_shipped_catalog() -> None:
    report = RuleYamlParser().parse(CATALOG_ROOT)
    assert report.rule_count >= 5  # at least the P1-shipped rules
    # Every parsed rule mapping carries the fields the loader expects.
    for parsed in report.rules:
        assert "id" in parsed.raw
        assert "schema_version" in parsed.raw


def test_verify_parsed_rules_closes_seed_loop() -> None:
    parsed = RuleYamlParser().parse(CATALOG_ROOT)
    report = verify_parsed_rules(
        parsed.rules,
        schema_registry=_schema_registry(),
        action_types=_action_types(),
        resource_types=_resource_types(),
        policies_root=POLICIES_ROOT,
        remediation_root=REMEDIATION_ROOT,
    )
    assert report.passed, [f"{i.origin}:{i.key}: {i.message}" for i in report.issues]
    assert report.verified_count == parsed.rule_count


def test_verify_parsed_rules_reports_bad_mapping() -> None:
    bad = ParsedRule(origin="broken.yaml", raw={"id": "no-schema-version"})
    report = verify_parsed_rules(
        [bad],
        schema_registry=_schema_registry(),
        action_types=_action_types(),
        resource_types=_resource_types(),
    )
    assert not report.passed
    assert report.verified_count == 0
    # Every issue carries the origin so a CLI can point at the file.
    assert all(i.origin == "broken.yaml" for i in report.issues)


def test_verify_parsed_rules_flags_duplicate_ids() -> None:
    parsed = RuleYamlParser().parse(CATALOG_ROOT)
    if parsed.rule_count < 1:
        pytest.skip("shipped catalog is empty — skipping duplicate-id assertion")
    first = parsed.rules[0]
    # Craft a second entry with the same id (via a fresh mapping copy).
    duplicated = ParsedRule(origin="clone.yaml", raw=dict(first.raw))
    report = verify_parsed_rules(
        [first, duplicated],
        schema_registry=_schema_registry(),
        action_types=_action_types(),
        resource_types=_resource_types(),
        policies_root=POLICIES_ROOT,
        remediation_root=REMEDIATION_ROOT,
    )
    assert not report.passed
    assert report.verified_count == 1
    assert any("duplicate rule id" in i.message for i in report.issues)
