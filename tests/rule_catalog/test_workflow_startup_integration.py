"""Workflow startup-integration test.

Mirrors the entry-point ordering in ``fdai.__main__._build_control_loop``:
load the ActionType catalog, the rule catalog, then the Workflow catalog
with the real ``action_type_names`` and ``rule_ids``. This proves the
shipped workflows validate through the same cross-reference path the
process uses at boot, so a workflow that references a missing ActionType
or an unknown guard Rule id would block startup rather than surface at
first dispatch.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.rule_catalog.schema.workflow import load_workflow_catalog, workflow_names
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_ROOT = REPO_ROOT / "rule-catalog"
ACTION_TYPES_ROOT = CATALOG_ROOT / "action-types"
PROBES_ROOT = CATALOG_ROOT / "probes"
RULES_ROOT = CATALOG_ROOT / "catalog"
WORKFLOWS_ROOT = CATALOG_ROOT / "workflows"
VOCABULARY_FILE = CATALOG_ROOT / "vocabulary" / "resource-types.yaml"
REMEDIATION_ROOT = CATALOG_ROOT / "remediation"
POLICIES_ROOT = REPO_ROOT / "policies"


def _registry() -> PackageResourceSchemaRegistry:
    return PackageResourceSchemaRegistry()


def test_shipped_workflows_validate_through_startup_path() -> None:
    registry = _registry()
    action_types = load_action_type_catalog(
        ACTION_TYPES_ROOT,
        schema_registry=registry,
        probes_root=PROBES_ROOT if PROBES_ROOT.is_dir() else None,
    )
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))
    rules = load_rule_catalog(
        RULES_ROOT,
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
        policies_root=POLICIES_ROOT,
        remediation_root=REMEDIATION_ROOT,
    )

    # This is the exact call the entry point makes, with the real
    # cross-reference sets. It must not raise.
    workflows = load_workflow_catalog(
        WORKFLOWS_ROOT,
        schema_registry=registry,
        action_type_names={a.name for a in action_types},
        rule_ids={r.id for r in rules},
    )

    names = workflow_names(workflows)
    assert {"cost-aware-remediation", "predictive-scale", "dr-failover-drill"} <= names
