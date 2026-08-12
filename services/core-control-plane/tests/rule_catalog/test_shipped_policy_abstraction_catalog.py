from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from fdai.rule_catalog.schema.control_objective import (
    ControlObjectiveState,
    load_control_objective_catalog,
)
from fdai.rule_catalog.schema.rego_semantics import load_rego_semantics
from fdai.rule_catalog.schema.rule import rule_content_hash
from fdai.rule_catalog.schema.rule_objective_binding import (
    BindingState,
    RuleObjectiveBindingCatalogError,
    load_rule_objective_binding_catalog,
    load_rule_objective_binding_from_mapping,
)
from fdai.shared.contracts.models import Rule

REPO_ROOT = Path(__file__).resolve().parents[4]
OBJECTIVES_ROOT = REPO_ROOT / "rule-catalog" / "control-objectives"
BINDINGS_ROOT = REPO_ROOT / "rule-catalog" / "rule-objective-bindings"
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
