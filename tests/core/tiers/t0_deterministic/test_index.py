"""RuleIndex - lookup + ordering invariants."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fdai.core.tiers.t0_deterministic import RuleIndex
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.models import (
    Category,
    CheckLogic,
    CheckLogicKind,
    Provenance,
    Remediation,
    Rule,
    RuleSource,
    Severity,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[4]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
RULES_ROOT = REPO_ROOT / "rule-catalog" / "catalog"
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"


def _load_shipped_rules() -> tuple[Rule, ...]:
    registry = PackageResourceSchemaRegistry()
    action_types = load_action_type_catalog(ACTION_TYPES_ROOT, schema_registry=registry)
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))
    return load_rule_catalog(
        RULES_ROOT,
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
    )


def _make_rule(
    *,
    rule_id: str,
    resource_type: str,
    severity: Severity,
    remediates: str = "remediate.tag-add",
    triggered_by: list[str] | None = None,
) -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=severity,
        category=Category.SECURITY,
        resource_type=resource_type,
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/x.rego"),
        remediation=Remediation(template_ref="remediation/x.tftpl"),
        remediates=remediates,
        applies_to=[resource_type],
        triggered_by=triggered_by or ["*"],
        provenance=Provenance(
            source_url="https://example.com/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution="embeddable",  # type: ignore[arg-type]
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


def test_index_over_shipped_catalog_returns_expected_types() -> None:
    rules = _load_shipped_rules()
    index = RuleIndex.build(rules)
    assert len(index) == len(rules)
    # Every shipped rule is retrievable by its resource_type.
    for rule in rules:
        assert rule in index.rules_for_type(rule.resource_type)
    # Unknown types return empty tuple (never None).
    assert index.rules_for_type("nowhere") == ()


def test_index_orders_findings_by_severity_desc_then_id() -> None:
    rules = [
        _make_rule(rule_id="a.low", resource_type="compute.vm", severity=Severity.LOW),
        _make_rule(rule_id="b.high", resource_type="compute.vm", severity=Severity.HIGH),
        _make_rule(rule_id="c.critical", resource_type="compute.vm", severity=Severity.CRITICAL),
        _make_rule(rule_id="d.high", resource_type="compute.vm", severity=Severity.HIGH),
    ]
    index = RuleIndex.build(rules)
    ordered = index.rules_for_type("compute.vm")
    assert [r.id for r in ordered] == ["c.critical", "b.high", "d.high", "a.low"]


def test_index_rejects_duplicate_ids() -> None:
    dup_a = _make_rule(rule_id="same.id", resource_type="compute.vm", severity=Severity.LOW)
    dup_b = _make_rule(rule_id="same.id", resource_type="compute.vm", severity=Severity.HIGH)
    with pytest.raises(ValueError) as info:
        RuleIndex.build([dup_a, dup_b])
    assert "duplicate rule id" in str(info.value)


def test_index_rule_lookup_and_unknown_id() -> None:
    r = _make_rule(rule_id="x.y", resource_type="compute.vm", severity=Severity.LOW)
    index = RuleIndex.build([r])
    assert index.rule("x.y") is r
    with pytest.raises(LookupError):
        index.rule("does.not.exist")


def test_index_ids_and_resource_types_helpers() -> None:
    rules = [
        _make_rule(rule_id="a.x", resource_type="compute.vm", severity=Severity.LOW),
        _make_rule(rule_id="b.x", resource_type="object-storage", severity=Severity.LOW),
    ]
    index = RuleIndex.build(rules)
    assert index.ids() == frozenset({"a.x", "b.x"})
    assert index.resource_types() == frozenset({"compute.vm", "object-storage"})


def test_index_intersects_resource_and_signal_types() -> None:
    exact = _make_rule(
        rule_id="a.exact",
        resource_type="compute.vm",
        severity=Severity.LOW,
        triggered_by=["config.changed"],
    )
    wildcard = _make_rule(
        rule_id="b.wildcard",
        resource_type="compute.vm",
        severity=Severity.LOW,
    )
    other = _make_rule(
        rule_id="c.other",
        resource_type="compute.vm",
        severity=Severity.LOW,
        triggered_by=["cost.changed"],
    )
    index = RuleIndex.build([exact, wildcard, other])

    assert index.rules_for_signal(resource_type="compute.vm", signal_type="config.changed") == (
        exact,
        wildcard,
    )
    assert index.rules_for_signal(resource_type="compute.vm", signal_type="unknown.changed") == (
        wildcard,
    )
