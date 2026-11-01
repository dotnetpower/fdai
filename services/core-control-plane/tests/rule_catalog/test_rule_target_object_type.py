"""Tests for generic ObjectType rule targeting via Rule.target_object_type."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.object_type import load_object_type_catalog
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import (
    RuleCatalogError,
    load_rule_catalog,
    load_rule_from_mapping,
    rule_content_hash,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[4]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
OBJECT_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "vocabulary" / "object-types"
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"


def _registry() -> PackageResourceSchemaRegistry:
    return PackageResourceSchemaRegistry()


def _base_rule_mapping() -> dict[str, object]:
    return {
        "schema_version": "2.0.0",
        "id": "fork-x.governance.assign-reviewers",
        "version": "1.0.0",
        "source": "custom",
        "severity": "medium",
        "category": "compliance",
        "resource_type": "governance.proposal",
        "target_object_type": "ChangeSummary",
        "applies_to": ["governance.proposal"],
        "triggered_by": ["*"],
        "evaluates": ["*"],
        "required_interfaces": ["Evaluable", "Remediable"],
        "submission_criteria": [
            {"kind": "object_type_registered", "value": "ChangeSummary"},
        ],
        "check_logic": {
            "kind": "rego",
            "reference": "policies/change_summary/publish_change_summary.rego",
        },
        "remediation": {
            "template_ref": "remediation/change_summary/publish_change_summary.yaml",
            "cost_impact_monthly_usd": 0,
        },
        "remediates": "ops.publish-change-summary",
        "provenance": {
            "source_url": "https://example.com/governance-baseline",
            "resolved_ref": "0000000000000000000000000000000000000000",
            "content_hash": (
                "sha256:0000000000000000000000000000000000000000000000000000000000000000"
            ),
            "license": "LicenseRef-reference-only",
            "redistribution": "reference-only",
            "retrieved_at": "2026-07-08T00:00:00Z",
        },
    }


def test_rule_targeting_registered_custom_object_type_loads_cleanly(tmp_path: Path) -> None:
    registry = _registry()
    action_types = load_action_type_catalog(ACTION_TYPES_ROOT, schema_registry=registry)
    object_types = load_object_type_catalog(OBJECT_TYPES_ROOT, schema_registry=registry)
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))

    raw = _base_rule_mapping()
    (tmp_path / "fork-x.governance.assign-reviewers.yaml").write_text(
        yaml.safe_dump(raw, sort_keys=False), encoding="utf-8"
    )

    loaded = load_rule_catalog(
        tmp_path,
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
        object_types=object_types,
    )
    assert len(loaded) == 1
    rule = loaded[0]
    assert rule.target_object_type == "ChangeSummary"
    assert rule.resource_type == "governance.proposal"
    assert rule_content_hash(rule).startswith("sha256:")


def test_rule_targeting_unknown_object_type_fails_closed() -> None:
    registry = _registry()
    raw = _base_rule_mapping()
    raw["target_object_type"] = "NonExistentObjectType"

    with pytest.raises(RuleCatalogError) as exc_info:
        load_rule_from_mapping(
            raw,
            schema_registry=registry,
            action_type_names={"ops.publish-change-summary"},
            resource_type_ids={"resource-group"},
            object_type_names={"Resource", "ChangeSummary"},
            origin="bad-target.yaml",
        )
    keys = {issue.key for issue in exc_info.value.issues}
    assert "bad-target.yaml:target_object_type" in keys


def test_rule_targeting_object_type_without_object_registry_fails_closed() -> None:
    registry = _registry()
    raw = _base_rule_mapping()

    with pytest.raises(RuleCatalogError) as exc_info:
        load_rule_from_mapping(
            raw,
            schema_registry=registry,
            action_type_names={"ops.publish-change-summary"},
            resource_type_ids={"resource-group"},
            object_type_names=None,
            origin="missing-registry.yaml",
        )
    keys = {issue.key for issue in exc_info.value.issues}
    assert "missing-registry.yaml:target_object_type" in keys


def test_rule_targeting_resource_object_type_still_enforces_resource_type_vocabulary() -> None:
    registry = _registry()
    raw = _base_rule_mapping()
    raw["target_object_type"] = "Resource"
    raw["submission_criteria"] = [{"kind": "object_type_registered", "value": "Resource"}]

    with pytest.raises(RuleCatalogError) as exc_info:
        load_rule_from_mapping(
            raw,
            schema_registry=registry,
            action_type_names={"ops.publish-change-summary"},
            resource_type_ids={"resource-group"},
            object_type_names={"Resource", "ChangeSummary"},
            origin="resource-target.yaml",
        )
    keys = {issue.key for issue in exc_info.value.issues}
    assert "resource-target.yaml:resource_type" in keys


def test_invalid_target_object_type_pattern_rejected_by_schema() -> None:
    registry = _registry()
    raw = _base_rule_mapping()
    raw["target_object_type"] = "lowercase-not-pascal"

    with pytest.raises(RuleCatalogError) as exc_info:
        load_rule_from_mapping(
            raw,
            schema_registry=registry,
            action_type_names={"ops.publish-change-summary"},
            resource_type_ids={"resource-group"},
            object_type_names={"ChangeSummary"},
            origin="bad-pattern.yaml",
        )
    keys = {issue.key for issue in exc_info.value.issues}
    assert "bad-pattern.yaml:target_object_type" in keys


def test_mismatched_object_type_registered_submission_criterion_rejected() -> None:
    registry = _registry()
    raw = _base_rule_mapping()
    raw["target_object_type"] = "ChangeSummary"
    raw["submission_criteria"] = [{"kind": "object_type_registered", "value": "Resource"}]

    with pytest.raises(RuleCatalogError) as exc_info:
        load_rule_from_mapping(
            raw,
            schema_registry=registry,
            action_type_names={"ops.publish-change-summary"},
            resource_type_ids={"resource-group"},
            object_type_names={"Resource", "ChangeSummary"},
            origin="mismatched-criterion.yaml",
        )
    keys = {issue.key for issue in exc_info.value.issues}
    assert "mismatched-criterion.yaml:submission_criteria[0]" in keys
