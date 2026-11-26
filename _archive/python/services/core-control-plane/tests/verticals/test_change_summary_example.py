"""Reference example vertical: on-demand resource-group change summary.

Exercises the shipped `ops.change-summary` reference example end-to-end
at the catalog + policy level:

- ObjectType `ChangeSummary` + LinkType `summarizes` load from the
  vocabulary catalogs.
- ActionType `ops.publish-change-summary` loads with shadow-mode +
  rollback contract invariants intact.
- Rule `ops.change-summary` cross-references the ActionType and resolves
  its policy + remediation template.
- The Rego policy fires when the synthetic ``request_kind`` marker is
  present on a `resource-group` event and stays silent otherwise.

Full pipeline integration (ControlLoop, executor, publisher) is not
re-tested here - the shipped pipeline tests already cover the rule
dispatch machinery for every catalog entry; this file is the
example-specific contract check.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from fdai.core.tiers.t0_deterministic import OpaRegoEvaluator, RuleIndex
from fdai.core.tiers.t0_deterministic.opa_evaluator import MissingOpaBinaryError
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.link_type import load_link_type_catalog
from fdai.rule_catalog.schema.object_type import load_object_type_catalog
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.models import Mode, Operation, RollbackKind
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[4]
OBJECT_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "vocabulary" / "object-types"
LINK_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "vocabulary" / "link-types"
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
CATALOG_ROOT = REPO_ROOT / "rule-catalog" / "catalog"
POLICIES_ROOT = REPO_ROOT / "policies"
REMEDIATION_ROOT = REPO_ROOT / "rule-catalog" / "remediation"
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"

_OPA_PRESENT = shutil.which("opa") is not None
requires_opa = pytest.mark.skipif(
    not _OPA_PRESENT,
    reason="opa binary not found on PATH; skip Rego evaluation",
)


def _registry() -> PackageResourceSchemaRegistry:
    return PackageResourceSchemaRegistry()


def test_change_summary_object_type_and_link_type_load() -> None:
    """The reference ObjectType + LinkType join the built-in vocabulary."""
    objects = load_object_type_catalog(OBJECT_TYPES_ROOT, schema_registry=_registry())
    names = {o.name for o in objects}
    assert "ChangeSummary" in names, "ChangeSummary ObjectType MUST ship upstream"

    change_summary = next(o for o in objects if o.name == "ChangeSummary")
    # Every property listed in the ObjectType MUST be declared -
    # `key` referencing an absent property is a load-time hard error,
    # so this assertion doubles as a regression on the loader's own
    # cross-check.
    assert change_summary.key == "id"
    assert change_summary.key in change_summary.properties

    links = load_link_type_catalog(
        LINK_TYPES_ROOT, schema_registry=_registry(), object_types=objects
    )
    by_name = {link.name: link for link in links}
    assert "summarizes" in by_name, "summarizes LinkType MUST ship upstream"
    summarizes = by_name["summarizes"]
    assert summarizes.from_type == "ChangeSummary"
    assert summarizes.to_type == "Resource"


def test_change_summary_action_type_holds_shipped_invariants() -> None:
    """`ops.publish-change-summary` MUST honour the upstream shipping rules."""
    catalog = load_action_type_catalog(
        ACTION_TYPES_ROOT, schema_registry=_registry(), probes_root=None
    )
    by_name = {a.name: a for a in catalog}
    assert "ops.publish-change-summary" in by_name

    at = by_name["ops.publish-change-summary"]
    # Every upstream ActionType ships in shadow mode; a fork that wants
    # to enforce on Day-1 does that in its own catalog, never by editing
    # the shipped file.
    assert at.default_mode is Mode.SHADOW
    # `create` is the executor verb for producing a new document; the
    # rollback path is `pr_revert` because the delivery adapter ships
    # the report through the paired remediation PR (a fork that swaps
    # to a document publisher declares the equivalent contract in its
    # adapter - see recipe 5.13).
    assert at.operation is Operation.CREATE
    assert at.rollback_contract is RollbackKind.PR_REVERT
    # Operator-request path MUST declare an argument_schema so the
    # console coordinator can validate arguments at the boundary.
    assert at.argument_schema is not None
    assert "target_resource_ref" in at.argument_schema["required"]
    assert "window_hours" in at.argument_schema["required"]


def test_change_summary_rule_wires_action_type_and_policy() -> None:
    """The shipped rule cross-references every dependency at load time."""
    registry = _registry()
    action_types = load_action_type_catalog(
        ACTION_TYPES_ROOT, schema_registry=registry, probes_root=None
    )
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))
    rules = load_rule_catalog(
        CATALOG_ROOT,
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
        policies_root=POLICIES_ROOT,
        remediation_root=REMEDIATION_ROOT,
    )
    by_id = {r.id: r for r in rules}
    assert "ops.change-summary" in by_id, "ops.change-summary rule MUST ship upstream"

    rule = by_id["ops.change-summary"]
    assert rule.resource_type == "resource-group"
    assert rule.remediates == "ops.publish-change-summary"
    assert rule.check_logic.reference == "policies/change_summary/publish_change_summary.rego"


def test_change_summary_rule_indexed_under_resource_group() -> None:
    """The trust router MUST find the rule when a resource-group event arrives."""
    registry = _registry()
    action_types = load_action_type_catalog(
        ACTION_TYPES_ROOT, schema_registry=registry, probes_root=None
    )
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))
    rules = load_rule_catalog(
        CATALOG_ROOT,
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
        policies_root=POLICIES_ROOT,
        remediation_root=REMEDIATION_ROOT,
    )
    index = RuleIndex.build(rules)
    matching_ids = {r.id for r in index.rules_for_type(resource_type="resource-group")}
    assert "ops.change-summary" in matching_ids


@requires_opa
def test_change_summary_policy_fires_on_request_marker() -> None:
    """Rego deny with reason `change_summary_requested` MUST fire on the marker."""
    registry = _registry()
    action_types = load_action_type_catalog(
        ACTION_TYPES_ROOT, schema_registry=registry, probes_root=None
    )
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))
    rules = load_rule_catalog(
        CATALOG_ROOT,
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
        policies_root=POLICIES_ROOT,
        remediation_root=REMEDIATION_ROOT,
    )
    rule = next(r for r in rules if r.id == "ops.change-summary")
    try:
        evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT)
    except MissingOpaBinaryError:  # pragma: no cover - guarded by requires_opa
        pytest.skip("opa binary unavailable")

    verdict = evaluator.evaluate(
        rule,
        {
            "request_kind": "change-summary",
            "window_hours": 24,
        },
    )
    assert verdict is not None
    assert verdict.denied is True
    assert verdict.context.get("deny_reason") == "change_summary_requested"


@requires_opa
def test_change_summary_policy_silent_on_ordinary_resource_group_events() -> None:
    """Absent the marker, the rule MUST stay silent so ordinary RG events pass."""
    registry = _registry()
    action_types = load_action_type_catalog(
        ACTION_TYPES_ROOT, schema_registry=registry, probes_root=None
    )
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))
    rules = load_rule_catalog(
        CATALOG_ROOT,
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
        policies_root=POLICIES_ROOT,
        remediation_root=REMEDIATION_ROOT,
    )
    rule = next(r for r in rules if r.id == "ops.change-summary")
    try:
        evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT)
    except MissingOpaBinaryError:  # pragma: no cover
        pytest.skip("opa binary unavailable")

    verdict = evaluator.evaluate(
        rule,
        {
            # No request_kind marker; ordinary inventory event.
            "tags": {"owner": "team-a", "cost_center": "cc-1"},
        },
    )
    # The rule MUST NOT trip on ordinary resource-group events - the
    # marker gate is the whole point of the design.
    assert verdict is not None
    assert verdict.denied is False
