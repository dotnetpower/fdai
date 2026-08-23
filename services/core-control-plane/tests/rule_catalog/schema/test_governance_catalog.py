"""Directory loader for the governance catalog-as-code."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai.rule_catalog.schema.governance_catalog import load_governance_catalog
from fdai.rule_catalog.schema.governance_loader import GovernanceLoadError

_VALID_ASSIGNMENT = """
schema_version: "1.0.0"
id: "assign-baseline-rg-a"
target_rule_ids: ["r.encryption"]
scope:
  level: "resource-group"
  id: "rg-a"
effect: "audit"
"""

_VALID_RULE_SET = """
schema_version: "1.0.0"
id: "security-baseline"
version: "1.0.0"
members:
  - rule_id: "r.encryption"
    version: "1.0.0"
    default_effect: "deny"
"""


def _write(root: Path, kind: str, name: str, body: str) -> None:
    d = root / kind
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body, encoding="utf-8")


def test_empty_root_is_empty_catalog(tmp_path: Path) -> None:
    cat = load_governance_catalog(tmp_path)
    assert cat.assignments == ()
    assert cat.rule_sets == ()
    assert cat.exemptions == ()


def test_loads_assignments_and_rule_sets(tmp_path: Path) -> None:
    _write(tmp_path, "assignments", "a.yaml", _VALID_ASSIGNMENT)
    _write(tmp_path, "rule-sets", "s.yaml", _VALID_RULE_SET)
    cat = load_governance_catalog(tmp_path)
    assert [a.id for a in cat.assignments] == ["assign-baseline-rg-a"]
    assert [r.id for r in cat.rule_sets] == ["security-baseline"]


def test_invalid_document_is_reported_with_file_key(tmp_path: Path) -> None:
    # missing required fields (target_rule_ids, scope)
    _write(tmp_path, "assignments", "bad.yaml", 'schema_version: "1.0.0"\nid: "x"\n')
    with pytest.raises(GovernanceLoadError) as ei:
        load_governance_catalog(tmp_path)
    assert any(i.key.startswith("bad.yaml") for i in ei.value.issues)


def test_duplicate_id_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "assignments", "a1.yaml", _VALID_ASSIGNMENT)
    _write(tmp_path, "assignments", "a2.yaml", _VALID_ASSIGNMENT)  # same id
    with pytest.raises(GovernanceLoadError) as ei:
        load_governance_catalog(tmp_path)
    assert any("duplicate id" in i.message for i in ei.value.issues)


def test_non_mapping_yaml_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "rule-sets", "list.yaml", "- just\n- a\n- list\n")
    with pytest.raises(GovernanceLoadError) as ei:
        load_governance_catalog(tmp_path)
    assert any("not a YAML mapping" in i.message for i in ei.value.issues)


def test_domain_invariant_duplicate_member_caught(tmp_path: Path) -> None:
    dup_member = """
schema_version: "1.0.0"
id: "dup-set"
version: "1.0.0"
members:
  - rule_id: "r.x"
    version: "1.0.0"
  - rule_id: "r.x"
    version: "2.0.0"
"""
    _write(tmp_path, "rule-sets", "dup.yaml", dup_member)
    with pytest.raises(GovernanceLoadError) as ei:
        load_governance_catalog(tmp_path)
    assert any("duplicate member" in i.message for i in ei.value.issues)


_RULE_SET_BINDING = """
schema_version: "1.0.0"
id: "assign-baseline-set"
rule_set: "security-baseline"
scope:
  level: "resource-group"
  id: "rg-a"
"""


def test_assignment_binds_rule_set_across_files(tmp_path: Path) -> None:
    _write(tmp_path, "rule-sets", "s.yaml", _VALID_RULE_SET)
    _write(tmp_path, "assignments", "bind.yaml", _RULE_SET_BINDING)
    cat = load_governance_catalog(tmp_path)
    (assignment,) = cat.assignments
    # the rule-set's members + per-rule default effects flow into the assignment
    assert assignment.target_rule_ids == frozenset({"r.encryption"})
    from fdai.rule_catalog.schema.effect import Effect

    assert assignment.effect_for("r.encryption") is Effect.DENY


def test_assignment_binding_unknown_rule_set_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "assignments", "bind.yaml", _RULE_SET_BINDING)  # no rule-set file
    with pytest.raises(GovernanceLoadError) as ei:
        load_governance_catalog(tmp_path)
    assert any("unknown rule-set" in i.message for i in ei.value.issues)


def test_malformed_yaml_is_reported_not_raised(tmp_path: Path) -> None:
    # a YAML syntax error must aggregate into a file-keyed issue, not crash the
    # whole catalog load with a raw YAMLError
    _write(tmp_path, "assignments", "bad.yaml", "foo: [unclosed\n")
    with pytest.raises(GovernanceLoadError) as ei:
        load_governance_catalog(tmp_path)
    assert any(
        "invalid YAML" in i.message and i.key.startswith("bad.yaml") for i in ei.value.issues
    )


def test_non_utf8_file_is_reported(tmp_path: Path) -> None:
    d = tmp_path / "rule-sets"
    d.mkdir(parents=True, exist_ok=True)
    (d / "bad.yaml").write_bytes(b"\xff\xfe\x00not utf-8")
    with pytest.raises(GovernanceLoadError) as ei:
        load_governance_catalog(tmp_path)
    assert any("UTF-8" in i.message for i in ei.value.issues)


def test_one_bad_file_does_not_hide_the_rest(tmp_path: Path) -> None:
    # a valid rule-set still loads even when a sibling file is malformed
    _write(tmp_path, "rule-sets", "good.yaml", _VALID_RULE_SET)
    _write(tmp_path, "rule-sets", "bad.yaml", "key: : value\n")
    with pytest.raises(GovernanceLoadError) as ei:
        load_governance_catalog(tmp_path)
    # the malformed file is reported (the load fails as a whole), keyed by name
    assert any(i.key.startswith("bad.yaml") for i in ei.value.issues)


def test_yml_extension_is_loaded(tmp_path: Path) -> None:
    # a `.yml` artifact must be loaded, not silently ignored
    _write(tmp_path, "rule-sets", "s.yml", _VALID_RULE_SET)
    _write(tmp_path, "assignments", "a.yml", _VALID_ASSIGNMENT)
    cat = load_governance_catalog(tmp_path)
    assert [r.id for r in cat.rule_sets] == ["security-baseline"]
    assert [a.id for a in cat.assignments] == ["assign-baseline-rg-a"]


def _valid_exemption(*, exemption_id: str = "exemption.rule-a.rg-a") -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "id": exemption_id,
        "rule_id": "rule-a",
        "scope": {
            "subscription_id": "00000000-0000-0000-0000-000000000000",
            "resource_group": "rg-a",
        },
        "justification": "A bounded migration exception is approved for this resource group.",
        "requested_by": "00000000-0000-0000-0000-000000000001",
        "approved_by": "00000000-0000-0000-0000-000000000002",
        "state": "active",
        "created_at": "2026-08-01T00:00:00Z",
        "expires_at": "2026-09-01T00:00:00Z",
    }


def _write_exemption(root: Path, name: str, payload: object) -> None:
    directory = root / "exemptions"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(payload), encoding="utf-8")


def test_loads_exemptions_and_validates_rule_reference(tmp_path: Path) -> None:
    _write_exemption(tmp_path, "rule-a.json", _valid_exemption())

    catalog = load_governance_catalog(tmp_path, known_rule_versions={"rule-a": "1.0.0"})

    assert [exemption.id for exemption in catalog.exemptions] == ["exemption.rule-a.rg-a"]


def test_invalid_and_duplicate_exemptions_are_aggregated(tmp_path: Path) -> None:
    _write_exemption(tmp_path, "a.json", _valid_exemption())
    _write_exemption(tmp_path, "b.json", _valid_exemption())
    (tmp_path / "exemptions" / "broken.json").write_text("{", encoding="utf-8")

    with pytest.raises(GovernanceLoadError) as exc_info:
        load_governance_catalog(tmp_path)

    messages = [issue.message for issue in exc_info.value.issues]
    assert any("duplicate id" in message for message in messages)
    assert any("invalid JSON" in message for message in messages)


def test_unknown_exemption_rule_is_rejected(tmp_path: Path) -> None:
    _write_exemption(tmp_path, "rule-a.json", _valid_exemption())

    with pytest.raises(GovernanceLoadError) as exc_info:
        load_governance_catalog(tmp_path, known_rule_versions={})

    assert any("references unknown rule id" in issue.message for issue in exc_info.value.issues)


def test_unknown_explicit_assignment_rule_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "assignments", "a.yaml", _VALID_ASSIGNMENT)

    with pytest.raises(GovernanceLoadError) as exc_info:
        load_governance_catalog(tmp_path, known_rule_versions={})

    assert any(
        issue.key == "assign-baseline-rg-a:r.encryption"
        and issue.message == "references unknown rule id"
        for issue in exc_info.value.issues
    )


def test_duplicate_json_key_in_exemption_is_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "exemptions"
    directory.mkdir()
    (directory / "duplicate.json").write_text(
        '{"schema_version":"1.0.0","state":"active","state":"revoked"}',
        encoding="utf-8",
    )

    with pytest.raises(GovernanceLoadError) as exc_info:
        load_governance_catalog(tmp_path)

    assert any("duplicate JSON key 'state'" in issue.message for issue in exc_info.value.issues)


def test_duplicate_active_exemption_scope_is_rejected(tmp_path: Path) -> None:
    _write_exemption(tmp_path, "a.json", _valid_exemption(exemption_id="exemption.rule-a.a"))
    _write_exemption(tmp_path, "b.json", _valid_exemption(exemption_id="exemption.rule-a.b"))

    with pytest.raises(GovernanceLoadError) as exc_info:
        load_governance_catalog(tmp_path)

    assert any(
        "duplicate active exemption scope" in issue.message for issue in exc_info.value.issues
    )
