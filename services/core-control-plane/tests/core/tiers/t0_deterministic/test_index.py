"""RuleIndex - lookup + ordering invariants."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
import yaml
from fdai.core.tiers.t0_deterministic import (
    CatalogIndexLifecycle,
    CatalogReloadReceipt,
    RuleIndex,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.rule_catalog.schema.signal_type import load_signal_type_registry_from_mapping
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

REPO_ROOT = Path(__file__).resolve().parents[6]
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


def test_index_resolves_catalog_signal_types_before_intersection() -> None:
    registry = load_signal_type_registry_from_mapping(
        yaml.safe_load(
            (REPO_ROOT / "rule-catalog/vocabulary/signal-types.yaml").read_text(encoding="utf-8")
        )
    )
    configuration = _make_rule(
        rule_id="a.configuration",
        resource_type="compute.vm",
        severity=Severity.LOW,
        triggered_by=["resource.configuration.observed"],
    )
    metric = _make_rule(
        rule_id="b.metric",
        resource_type="compute.vm",
        severity=Severity.LOW,
        triggered_by=["resource.metric.observed"],
    )
    index = RuleIndex.build((configuration, metric), signal_types=registry)

    assert index.rules_for_signal(resource_type="compute.vm", signal_type="metric.cpu.spike") == (
        metric,
    )
    assert index.rules_for_signal(
        resource_type="compute.vm", signal_type="unmapped.provider.event"
    ) == (configuration,)


def test_index_without_signal_registry_preserves_shipped_catch_all_compatibility() -> None:
    configuration = _make_rule(
        rule_id="a.configuration",
        resource_type="compute.vm",
        severity=Severity.LOW,
        triggered_by=["resource.configuration.observed"],
    )
    metric = _make_rule(
        rule_id="b.metric",
        resource_type="compute.vm",
        severity=Severity.LOW,
        triggered_by=["resource.metric.observed"],
    )
    index = RuleIndex.build((configuration, metric))

    assert index.rules_for_signal(
        resource_type="compute.vm", signal_type="legacy.synthetic.event"
    ) == (configuration, metric)


def test_catalog_reload_failure_preserves_current_and_previous_indexes() -> None:
    baseline = _make_rule(
        rule_id="baseline.rule",
        resource_type="compute.vm",
        severity=Severity.LOW,
    )
    lifecycle = CatalogIndexLifecycle(catalog_version="catalog-n", rules=(baseline,))
    accepted = lifecycle.reload(
        catalog_version="catalog-n-plus-one",
        rules=(
            _make_rule(
                rule_id="replacement.rule",
                resource_type="object-storage",
                severity=Severity.HIGH,
            ),
        ),
    )
    current_before_failure = lifecycle.current_index

    with pytest.raises(ValueError, match="duplicate rule id"):
        lifecycle.reload(
            catalog_version="catalog-n-plus-two",
            rules=(baseline, baseline.model_copy(update={"severity": Severity.HIGH})),
        )

    assert lifecycle.current_catalog_version == "catalog-n-plus-one"
    assert lifecycle.current_index is current_before_failure
    assert lifecycle.index_for("catalog-n") is not None
    assert lifecycle.last_receipt.accepted is False
    assert lifecycle.last_receipt.retained_catalog_versions == accepted.retained_catalog_versions


def test_catalog_reload_retains_n_minus_one_and_rolls_back_without_recompile() -> None:
    baseline = _make_rule(
        rule_id="baseline.rule",
        resource_type="compute.vm",
        severity=Severity.LOW,
    )
    replacement = _make_rule(
        rule_id="replacement.rule",
        resource_type="object-storage",
        severity=Severity.HIGH,
    )
    lifecycle = CatalogIndexLifecycle(catalog_version="catalog-n", rules=(baseline,))

    receipt = lifecycle.reload(catalog_version="catalog-n-plus-one", rules=(replacement,))
    assert receipt.retained_catalog_versions == ("catalog-n-plus-one", "catalog-n")
    assert lifecycle.index_for("catalog-n").rule("baseline.rule") is baseline
    assert lifecycle.current_index.rule("replacement.rule") is replacement

    rollback = lifecycle.rollback()
    assert rollback.current_catalog_version == "catalog-n"
    assert lifecycle.current_catalog_version == "catalog-n"
    assert lifecycle.index_for("catalog-n-plus-one").rule("replacement.rule") is replacement
    with pytest.raises(LookupError, match="not replayable"):
        lifecycle.index_for("catalog-n-minus-one")


def test_catalog_reload_rejects_same_version_with_different_rules() -> None:
    baseline = _make_rule(
        rule_id="baseline.rule",
        resource_type="compute.vm",
        severity=Severity.LOW,
    )
    lifecycle = CatalogIndexLifecycle(catalog_version="catalog-n", rules=(baseline,))

    with pytest.raises(ValueError, match="already accepted"):
        lifecycle.reload(
            catalog_version="catalog-n",
            rules=(
                _make_rule(
                    rule_id="different.rule",
                    resource_type="compute.vm",
                    severity=Severity.LOW,
                ),
            ),
        )
    assert lifecycle.current_index.rule("baseline.rule") is baseline


def test_catalog_reload_rejects_conflicting_retained_previous_version() -> None:
    baseline = _make_rule(
        rule_id="baseline.rule",
        resource_type="compute.vm",
        severity=Severity.LOW,
    )
    replacement = _make_rule(
        rule_id="replacement.rule",
        resource_type="object-storage",
        severity=Severity.HIGH,
    )
    lifecycle = CatalogIndexLifecycle(catalog_version="catalog-n", rules=(baseline,))
    lifecycle.reload(catalog_version="catalog-n-plus-one", rules=(replacement,))

    with pytest.raises(ValueError, match="retained; use rollback explicitly"):
        lifecycle.reload(
            catalog_version="catalog-n",
            rules=(
                _make_rule(
                    rule_id="conflicting.rule",
                    resource_type="compute.vm",
                    severity=Severity.CRITICAL,
                ),
            ),
        )

    assert lifecycle.current_catalog_version == "catalog-n-plus-one"
    assert lifecycle.index_for("catalog-n").rule("baseline.rule") is baseline
    assert lifecycle.last_receipt.accepted is False


def test_catalog_reload_and_rollback_are_serialized() -> None:
    baseline = _make_rule(
        rule_id="baseline.rule",
        resource_type="compute.vm",
        severity=Severity.LOW,
    )
    replacement = _make_rule(
        rule_id="replacement.rule",
        resource_type="object-storage",
        severity=Severity.HIGH,
    )
    lifecycle = CatalogIndexLifecycle(catalog_version="catalog-n", rules=(baseline,))
    lifecycle.reload(catalog_version="catalog-n-plus-one", rules=(replacement,))
    barrier = Barrier(2)

    def _transition(operation: str) -> CatalogReloadReceipt:
        barrier.wait()
        if operation == "reload":
            return lifecycle.reload(
                catalog_version="catalog-n-plus-two",
                rules=(baseline, replacement),
            )
        return lifecycle.rollback()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(
            executor.submit(_transition, operation) for operation in ("reload", "rollback")
        )
        receipts = tuple(future.result() for future in futures)

    assert all(receipt.accepted for receipt in receipts)
    retained = {
        lifecycle.current_catalog_version,
        lifecycle.previous_catalog_version,
    }
    assert set(receipts[0].retained_catalog_versions) >= {receipts[0].current_catalog_version}
    assert set(receipts[1].retained_catalog_versions) >= {receipts[1].current_catalog_version}
    assert retained == {
        lifecycle.current_catalog_version,
        lifecycle.previous_catalog_version,
    }
    assert lifecycle.previous_catalog_version is not None
    assert lifecycle.index_for(lifecycle.current_catalog_version)
    assert lifecycle.index_for(lifecycle.previous_catalog_version)
    assert lifecycle.last_receipt.current_catalog_version == lifecycle.current_catalog_version
