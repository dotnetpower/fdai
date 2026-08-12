from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.control_objective import (
    ControlObjectiveState,
    load_control_objective_catalog,
)
from fdai.rule_catalog.schema.rego_semantics import load_rego_semantics
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import load_rule_catalog, rule_content_hash
from fdai.rule_catalog.schema.rule_objective_binding import (
    BindingState,
    RuleObjectiveBindingCatalogError,
    build_rule_objective_binding_migration_report,
    load_rule_objective_binding_catalog,
    load_rule_objective_binding_from_mapping,
)
from fdai.shared.contracts.models import CheckLogicKind, Rule
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[4]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
OBJECTIVES_ROOT = REPO_ROOT / "rule-catalog" / "control-objectives"
BINDINGS_ROOT = REPO_ROOT / "rule-catalog" / "rule-objective-bindings"
RULES_ROOT = REPO_ROOT / "rule-catalog" / "catalog"
RESOURCE_TYPES_PATH = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"
RULE_PATH = REPO_ROOT / "rule-catalog" / "catalog" / "kubernetes-node-pool.multi-zone.yaml"
BINDING_PATH = BINDINGS_ROOT / "binding.node-pool-zone-resilience.yaml"


def test_shipped_control_objectives_load_as_inert_candidates() -> None:
    objectives = load_control_objective_catalog(
        OBJECTIVES_ROOT,
        operating_domains=frozenset({"reliability"}),
        object_type_names=frozenset({"Resource"}),
        resource_type_ids=frozenset({"kubernetes-node-pool"}),
        property_refs=frozenset({"property.kubernetes-node-pool.availability_zones"}),
    )

    assert len(objectives) == 1
    assert objectives[0].state is ControlObjectiveState.CANDIDATE
    assert objectives[0].ref == ("reliability.node-pool.zone-failure-tolerance@1.0.0")


def _catalog_registries() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    objectives = load_control_objective_catalog(
        OBJECTIVES_ROOT,
        operating_domains=frozenset({"reliability"}),
        object_type_names=frozenset({"Resource"}),
        resource_type_ids=frozenset({"kubernetes-node-pool"}),
        property_refs=frozenset({"property.kubernetes-node-pool.availability_zones"}),
    )
    rule = Rule.model_validate(yaml.safe_load(RULE_PATH.read_text(encoding="utf-8")))
    semantics = load_rego_semantics(REPO_ROOT / rule.check_logic.reference)
    objective_digests = {objective.ref: objective.content_digest for objective in objectives}
    rule_digests = {f"{rule.id}@{rule.version}": rule_content_hash(rule)}
    implementation_digests = {f"{rule.id}@{rule.version}": semantics.normalized_semantic_digest}
    return objective_digests, rule_digests, implementation_digests


def _authored_rule_registries() -> tuple[dict[str, str], dict[str, str]]:
    schema_registry = PackageResourceSchemaRegistry()
    action_types = load_action_type_catalog(
        ACTION_TYPES_ROOT,
        schema_registry=schema_registry,
    )
    resource_types = load_resource_type_registry_from_mapping(
        yaml.safe_load(RESOURCE_TYPES_PATH.read_text(encoding="utf-8"))
    )
    rules = load_rule_catalog(
        RULES_ROOT,
        schema_registry=schema_registry,
        action_types=action_types,
        resource_types=resource_types,
        policies_root=REPO_ROOT / "policies",
        remediation_root=REPO_ROOT / "rule-catalog" / "remediation",
    )
    authored_rules = tuple(rule for rule in rules if rule.check_logic.kind is CheckLogicKind.REGO)
    assert len(authored_rules) == 62

    rule_digests = {f"{rule.id}@{rule.version}": rule_content_hash(rule) for rule in authored_rules}
    implementation_digests = {
        f"{rule.id}@{rule.version}": load_rego_semantics(
            REPO_ROOT / rule.check_logic.reference
        ).normalized_semantic_digest
        for rule in authored_rules
    }
    return rule_digests, implementation_digests


def test_shipped_binding_pins_real_objective_rule_and_rego_semantics() -> None:
    objective_digests, rule_digests, implementation_digests = _catalog_registries()
    bindings = load_rule_objective_binding_catalog(
        BINDINGS_ROOT,
        objective_digests=objective_digests,
        rule_digests=rule_digests,
        rule_implementation_digests=implementation_digests,
        evidence_refs=frozenset({"property.kubernetes-node-pool.availability_zones"}),
    )

    assert len(bindings) == 1
    assert bindings[0].state is BindingState.CANDIDATE
    assert bindings[0].equivalence_receipt is None


def test_shipped_catalog_accounts_for_every_authored_rule_without_reviewed_binding() -> None:
    objective_digests, _, _ = _catalog_registries()
    rule_digests, implementation_digests = _authored_rule_registries()

    with pytest.raises(RuleObjectiveBindingCatalogError) as raised:
        load_rule_objective_binding_catalog(
            BINDINGS_ROOT,
            objective_digests=objective_digests,
            rule_digests=rule_digests,
            rule_implementation_digests=implementation_digests,
            evidence_refs=frozenset({"property.kubernetes-node-pool.availability_zones"}),
            required_reviewed_rule_refs=frozenset(rule_digests),
        )

    missing_rule_refs = {
        issue.key.removeprefix("reviewed_coverage:")
        for issue in raised.value.issues
        if issue.key.startswith("reviewed_coverage:")
    }
    assert missing_rule_refs == set(rule_digests)
    assert len(raised.value.issues) == len(rule_digests) == 62

    candidate_bindings = load_rule_objective_binding_catalog(
        BINDINGS_ROOT,
        objective_digests=objective_digests,
        rule_digests=rule_digests,
        rule_implementation_digests=implementation_digests,
        evidence_refs=frozenset({"property.kubernetes-node-pool.availability_zones"}),
    )
    report = build_rule_objective_binding_migration_report(
        authored_rule_refs=frozenset(rule_digests),
        bindings=candidate_bindings,
        ambiguous_rule_refs=frozenset(rule_digests),
    )

    assert len(report.authored_rule_refs) == 62
    assert report.bound_rule_refs == ()
    assert len(report.ambiguous_rule_refs) == 62


def test_shipped_binding_rejects_stale_rule_pin() -> None:
    objective_digests, rule_digests, implementation_digests = _catalog_registries()
    raw = yaml.safe_load(BINDING_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    stale = deepcopy(raw)
    stale["rule"]["content_digest"] = f"sha256:{'f' * 64}"

    with pytest.raises(RuleObjectiveBindingCatalogError, match="rule digest mismatch"):
        load_rule_objective_binding_from_mapping(
            stale,
            objective_digests=objective_digests,
            rule_digests=rule_digests,
            rule_implementation_digests=implementation_digests,
            evidence_refs=frozenset({"property.kubernetes-node-pool.availability_zones"}),
            origin=BINDING_PATH.name,
        )
