"""Rule catalog loader - schema + cross-reference invariants.

Complements ``test_action_type_catalog.py`` and
``test_resource_type_registry.py``: exercises rule YAML load, ActionType
and resource_type cross-references, duplicate-id and fail-close paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from aiopspilot.rule_catalog.schema.action_type import load_action_type_catalog
from aiopspilot.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from aiopspilot.rule_catalog.schema.rule import (
    RuleCatalogError,
    load_rule_catalog,
    load_rule_from_mapping,
)
from aiopspilot.shared.contracts.models import Category, RuleSource, Severity
from aiopspilot.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
RULES_ROOT = REPO_ROOT / "rule-catalog" / "catalog"
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"
POLICIES_ROOT = REPO_ROOT / "policies"
REMEDIATION_ROOT = REPO_ROOT / "rule-catalog" / "remediation"


def _registry() -> PackageResourceSchemaRegistry:
    return PackageResourceSchemaRegistry()


def _load_resource_types():  # type: ignore[no-untyped-def]
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        return load_resource_type_registry_from_mapping(yaml.safe_load(fh))


def _load_action_types():  # type: ignore[no-untyped-def]
    return load_action_type_catalog(ACTION_TYPES_ROOT, schema_registry=_registry())


def _valid_raw() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "id": "object-storage.public-access.deny",
        "version": "1.0.0",
        "source": "mcsb",
        "severity": "high",
        "category": "security",
        "resource_type": "object-storage",
        "check_logic": {
            "kind": "rego",
            "reference": "policies/object_storage/public_access.rego",
        },
        "remediation": {
            "template_ref": "remediation/object_storage/disable_public_access.tftpl",
            "cost_impact_monthly_usd": 0,
        },
        "remediates": "remediate.disable-public-access",
        "provenance": {
            "source_url": "https://example.com/rules/object-storage-public-access",
            "resolved_ref": "0000000000000000000000000000000000000000",
            "content_hash": (
                "sha256:0000000000000000000000000000000000000000000000000000000000000000"
            ),
            "license": "LicenseRef-reference-only",
            "redistribution": "reference-only",
            "retrieved_at": "2026-07-05T00:00:00Z",
        },
    }


def test_shipped_catalog_loads_and_covers_every_action_type() -> None:
    action_types = _load_action_types()
    resource_types = _load_resource_types()
    rules = load_rule_catalog(
        RULES_ROOT,
        schema_registry=_registry(),
        action_types=action_types,
        resource_types=resource_types,
    )
    assert len(rules) >= 5
    remediated = {r.remediates for r in rules}
    # P1 W-2: every shipped rule-violation-trigger ActionType MUST be referenced
    # by at least one rule. ActionTypes with trigger_kind={operator_request,both}
    # are operator-driven and are allowed to ship without a rule (see
    # action-ontology.md 8 loader cross-checks); a rule-less operator ActionType
    # is legal.
    for at in action_types:
        tk = at.trigger_kind.kind.value if at.trigger_kind else "rule_violation"
        if tk == "rule_violation":
            assert at.name in remediated, (
                f"ActionType {at.name!r} has no rule; W-2 requires >=1 for rule_violation trigger"
            )


def test_shipped_catalog_rule_ids_match_filenames() -> None:
    action_types = _load_action_types()
    resource_types = _load_resource_types()
    rules = load_rule_catalog(
        RULES_ROOT,
        schema_registry=_registry(),
        action_types=action_types,
        resource_types=resource_types,
    )
    for rule in rules:
        expected = RULES_ROOT / f"{rule.id}.yaml"
        assert expected.exists(), (
            f"rule id/file mismatch: id={rule.id} expects file {expected.name}"
        )


def test_single_valid_mapping_round_trips() -> None:
    action_types = _load_action_types()
    resource_types = _load_resource_types()
    rule = load_rule_from_mapping(
        _valid_raw(),
        schema_registry=_registry(),
        action_type_names={a.name for a in action_types},
        resource_type_ids=resource_types.ids(),
    )
    assert rule.id == "object-storage.public-access.deny"
    assert rule.remediates == "remediate.disable-public-access"
    assert rule.source is RuleSource.MCSB
    assert rule.severity is Severity.HIGH
    assert rule.category is Category.SECURITY
    assert rule.alternatives == []


def test_missing_remediates_is_rejected_by_schema() -> None:
    raw = _valid_raw()
    del raw["remediates"]
    with pytest.raises(RuleCatalogError) as info:
        load_rule_from_mapping(
            raw,
            schema_registry=_registry(),
            action_type_names={"remediate.disable-public-access"},
            resource_type_ids={"object-storage"},
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "remediates" in joined and "required" in joined


def test_unknown_remediates_is_rejected_by_cross_reference() -> None:
    raw = _valid_raw()
    raw["remediates"] = "remediate.nonexistent"
    with pytest.raises(RuleCatalogError) as info:
        load_rule_from_mapping(
            raw,
            schema_registry=_registry(),
            action_type_names={"remediate.disable-public-access"},
            resource_type_ids={"object-storage"},
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "unknown actiontype" in joined
    assert "remediate.nonexistent" in joined


def test_unknown_alternative_is_rejected_by_cross_reference() -> None:
    raw = _valid_raw()
    raw["alternatives"] = ["remediate.disable-public-access", "remediate.made-up"]
    with pytest.raises(RuleCatalogError) as info:
        load_rule_from_mapping(
            raw,
            schema_registry=_registry(),
            action_type_names={"remediate.disable-public-access"},
            resource_type_ids={"object-storage"},
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "made-up" in joined
    keys = " ".join(i.key for i in info.value.issues)
    assert "alternatives[1]" in keys


def test_unknown_resource_type_is_rejected_by_cross_reference() -> None:
    raw = _valid_raw()
    raw["resource_type"] = "not-in-vocabulary"
    with pytest.raises(RuleCatalogError) as info:
        load_rule_from_mapping(
            raw,
            schema_registry=_registry(),
            action_type_names={"remediate.disable-public-access"},
            resource_type_ids={"object-storage"},
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "unknown resource_type" in joined
    assert "not-in-vocabulary" in joined


def test_duplicate_id_across_files_is_rejected(tmp_path: Path) -> None:
    import yaml as _yaml

    body = _yaml.safe_dump(_valid_raw(), sort_keys=False)
    (tmp_path / "a.yaml").write_text(body, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(body, encoding="utf-8")

    action_types = _load_action_types()
    resource_types = _load_resource_types()
    with pytest.raises(RuleCatalogError) as info:
        load_rule_catalog(
            tmp_path,
            schema_registry=_registry(),
            action_types=action_types,
            resource_types=resource_types,
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "duplicate rule id" in joined


def test_invalid_yaml_reports_the_file(tmp_path: Path) -> None:
    (tmp_path / "broken.yaml").write_text(":\n  - invalid: [\n", encoding="utf-8")
    action_types = _load_action_types()
    resource_types = _load_resource_types()
    with pytest.raises(RuleCatalogError) as info:
        load_rule_catalog(
            tmp_path,
            schema_registry=_registry(),
            action_types=action_types,
            resource_types=resource_types,
        )
    keys = " ".join(i.key for i in info.value.issues)
    assert "broken.yaml" in keys


def test_top_level_not_a_mapping_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "list.yaml").write_text("- just_a_list_item\n", encoding="utf-8")
    action_types = _load_action_types()
    resource_types = _load_resource_types()
    with pytest.raises(RuleCatalogError) as info:
        load_rule_catalog(
            tmp_path,
            schema_registry=_registry(),
            action_types=action_types,
            resource_types=resource_types,
        )
    assert any("top-level" in i.message for i in info.value.issues)


def test_empty_catalog_directory_returns_empty_tuple(tmp_path: Path) -> None:
    action_types = _load_action_types()
    resource_types = _load_resource_types()
    rules = load_rule_catalog(
        tmp_path,
        schema_registry=_registry(),
        action_types=action_types,
        resource_types=resource_types,
    )
    assert rules == ()


def test_multi_issue_error_aggregates_across_files(tmp_path: Path) -> None:
    """Fail-closed: one bad rule MUST NOT hide other bad rules."""
    import yaml as _yaml

    good = _valid_raw()
    bad1 = _valid_raw()
    bad1["remediates"] = "remediate.made-up"
    bad2 = _valid_raw()
    bad2["id"] = "another-bad-id"
    bad2["resource_type"] = "nowhere"

    (tmp_path / "a.yaml").write_text(_yaml.safe_dump(good, sort_keys=False), encoding="utf-8")
    (tmp_path / "b.yaml").write_text(_yaml.safe_dump(bad1, sort_keys=False), encoding="utf-8")
    (tmp_path / "c.yaml").write_text(_yaml.safe_dump(bad2, sort_keys=False), encoding="utf-8")

    action_types = _load_action_types()
    resource_types = _load_resource_types()
    with pytest.raises(RuleCatalogError) as info:
        load_rule_catalog(
            tmp_path,
            schema_registry=_registry(),
            action_types=action_types,
            resource_types=resource_types,
        )
    keys = " ".join(i.key for i in info.value.issues)
    assert "b.yaml" in keys
    assert "c.yaml" in keys


# ---------------------------------------------------------------------------
# check_logic.reference file cross-check (P1 W-3 policies_root gate)
# ---------------------------------------------------------------------------


def test_shipped_catalog_resolves_check_logic_reference_against_policies_root() -> None:
    """Every shipped rule's Rego reference MUST exist under `policies/`."""
    action_types = _load_action_types()
    resource_types = _load_resource_types()
    rules = load_rule_catalog(
        RULES_ROOT,
        schema_registry=_registry(),
        action_types=action_types,
        resource_types=resource_types,
        policies_root=POLICIES_ROOT,
    )
    assert len(rules) >= 5


def test_missing_policy_file_is_rejected(tmp_path: Path) -> None:
    raw = _valid_raw()
    raw["check_logic"] = {
        "kind": "rego",
        "reference": "policies/object_storage/does_not_exist.rego",
    }
    with pytest.raises(RuleCatalogError) as info:
        load_rule_from_mapping(
            raw,
            schema_registry=_registry(),
            action_type_names={"remediate.disable-public-access"},
            resource_type_ids={"object-storage"},
            policies_root=POLICIES_ROOT,
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "policy file not found" in joined
    assert "does_not_exist.rego" in joined
    keys = " ".join(i.key for i in info.value.issues)
    assert "check_logic.reference" in keys


def test_policies_root_none_skips_file_existence_check() -> None:
    """Backward compatibility: no `policies_root` = no filesystem gate."""
    raw = _valid_raw()
    raw["check_logic"] = {
        "kind": "rego",
        "reference": "policies/object_storage/does_not_exist.rego",
    }
    rule = load_rule_from_mapping(
        raw,
        schema_registry=_registry(),
        action_type_names={"remediate.disable-public-access"},
        resource_type_ids={"object-storage"},
        # policies_root omitted -> default None
    )
    assert rule.id == "object-storage.public-access.deny"


def test_absolute_policy_reference_is_rejected() -> None:
    raw = _valid_raw()
    raw["check_logic"] = {
        "kind": "rego",
        "reference": "policies//etc/passwd",
    }
    with pytest.raises(RuleCatalogError) as info:
        load_rule_from_mapping(
            raw,
            schema_registry=_registry(),
            action_type_names={"remediate.disable-public-access"},
            resource_type_ids={"object-storage"},
            policies_root=POLICIES_ROOT,
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "repo-relative" in joined


def test_policy_reference_with_parent_traversal_is_rejected() -> None:
    raw = _valid_raw()
    raw["check_logic"] = {
        "kind": "rego",
        "reference": "policies/../etc/passwd",
    }
    with pytest.raises(RuleCatalogError) as info:
        load_rule_from_mapping(
            raw,
            schema_registry=_registry(),
            action_type_names={"remediate.disable-public-access"},
            resource_type_ids={"object-storage"},
            policies_root=POLICIES_ROOT,
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "repo-relative" in joined


def test_non_policies_prefix_reference_is_ignored_by_gate(tmp_path: Path) -> None:
    """Only `policies/`-prefixed refs are gated; other conventions pass through."""
    raw = _valid_raw()
    raw["check_logic"] = {
        "kind": "rego",
        "reference": "external-package://foo/bar",
    }
    rule = load_rule_from_mapping(
        raw,
        schema_registry=_registry(),
        action_type_names={"remediate.disable-public-access"},
        resource_type_ids={"object-storage"},
        policies_root=POLICIES_ROOT,
    )
    assert rule.check_logic.reference == "external-package://foo/bar"


def test_expression_check_logic_bypasses_file_check() -> None:
    raw = _valid_raw()
    raw["check_logic"] = {
        "kind": "expression",
        "reference": "policies/should-not-be-checked.rego",
    }
    rule = load_rule_from_mapping(
        raw,
        schema_registry=_registry(),
        action_type_names={"remediate.disable-public-access"},
        resource_type_ids={"object-storage"},
        policies_root=POLICIES_ROOT,
    )
    assert rule.check_logic.reference == "policies/should-not-be-checked.rego"


def test_load_rule_catalog_threads_policies_root(tmp_path: Path) -> None:
    """load_rule_catalog forwards policies_root to per-file validation."""
    import yaml as _yaml

    raw = _valid_raw()
    raw["check_logic"] = {
        "kind": "rego",
        "reference": "policies/object_storage/absent.rego",
    }
    (tmp_path / "one.yaml").write_text(_yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    action_types = _load_action_types()
    resource_types = _load_resource_types()
    with pytest.raises(RuleCatalogError) as info:
        load_rule_catalog(
            tmp_path,
            schema_registry=_registry(),
            action_types=action_types,
            resource_types=resource_types,
            policies_root=POLICIES_ROOT,
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "policy file not found" in joined


# ---------------------------------------------------------------------------
# remediation.template_ref file cross-check (P1 W-3 Step 3e remediation_root gate)
# ---------------------------------------------------------------------------


def test_shipped_catalog_resolves_template_ref_against_remediation_root() -> None:
    """Every shipped rule's `remediation.template_ref` MUST exist under
    `rule-catalog/remediation/`."""
    action_types = _load_action_types()
    resource_types = _load_resource_types()
    rules = load_rule_catalog(
        RULES_ROOT,
        schema_registry=_registry(),
        action_types=action_types,
        resource_types=resource_types,
        remediation_root=REMEDIATION_ROOT,
    )
    assert len(rules) >= 5


def test_missing_remediation_template_is_rejected() -> None:
    raw = _valid_raw()
    raw["remediation"] = {
        "template_ref": "remediation/object_storage/does_not_exist.tftpl",
        "cost_impact_monthly_usd": 0,
    }
    with pytest.raises(RuleCatalogError) as info:
        load_rule_from_mapping(
            raw,
            schema_registry=_registry(),
            action_type_names={"remediate.disable-public-access"},
            resource_type_ids={"object-storage"},
            remediation_root=REMEDIATION_ROOT,
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "remediation template file not found" in joined
    keys = " ".join(i.key for i in info.value.issues)
    assert "remediation.template_ref" in keys


def test_remediation_root_none_skips_template_check() -> None:
    raw = _valid_raw()
    raw["remediation"] = {
        "template_ref": "remediation/object_storage/does_not_exist.tftpl",
        "cost_impact_monthly_usd": 0,
    }
    rule = load_rule_from_mapping(
        raw,
        schema_registry=_registry(),
        action_type_names={"remediate.disable-public-access"},
        resource_type_ids={"object-storage"},
        # remediation_root omitted -> default None
    )
    assert rule.remediation.template_ref.startswith("remediation/")


def test_absolute_template_ref_is_rejected() -> None:
    raw = _valid_raw()
    raw["remediation"] = {
        "template_ref": "remediation//etc/passwd",
        "cost_impact_monthly_usd": 0,
    }
    with pytest.raises(RuleCatalogError) as info:
        load_rule_from_mapping(
            raw,
            schema_registry=_registry(),
            action_type_names={"remediate.disable-public-access"},
            resource_type_ids={"object-storage"},
            remediation_root=REMEDIATION_ROOT,
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "repo-relative" in joined


def test_template_ref_with_parent_traversal_is_rejected() -> None:
    raw = _valid_raw()
    raw["remediation"] = {
        "template_ref": "remediation/../etc/passwd",
        "cost_impact_monthly_usd": 0,
    }
    with pytest.raises(RuleCatalogError) as info:
        load_rule_from_mapping(
            raw,
            schema_registry=_registry(),
            action_type_names={"remediate.disable-public-access"},
            resource_type_ids={"object-storage"},
            remediation_root=REMEDIATION_ROOT,
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "repo-relative" in joined


def test_non_remediation_prefix_template_ref_is_ignored_by_gate() -> None:
    raw = _valid_raw()
    raw["remediation"] = {
        "template_ref": "artifact://foo/bar",
        "cost_impact_monthly_usd": 0,
    }
    rule = load_rule_from_mapping(
        raw,
        schema_registry=_registry(),
        action_type_names={"remediate.disable-public-access"},
        resource_type_ids={"object-storage"},
        remediation_root=REMEDIATION_ROOT,
    )
    assert rule.remediation.template_ref == "artifact://foo/bar"


def test_load_rule_catalog_threads_remediation_root(tmp_path: Path) -> None:
    import yaml as _yaml

    raw = _valid_raw()
    raw["remediation"] = {
        "template_ref": "remediation/object_storage/absent.tftpl",
        "cost_impact_monthly_usd": 0,
    }
    (tmp_path / "one.yaml").write_text(_yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    action_types = _load_action_types()
    resource_types = _load_resource_types()
    with pytest.raises(RuleCatalogError) as info:
        load_rule_catalog(
            tmp_path,
            schema_registry=_registry(),
            action_types=action_types,
            resource_types=resource_types,
            remediation_root=REMEDIATION_ROOT,
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "remediation template file not found" in joined
