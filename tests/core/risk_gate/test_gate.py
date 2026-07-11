"""RiskGate + ActionPromotionRegistry - safety invariants + promotion contract."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from fdai.core.risk_gate import (
    ActionPromotionRegistry,
    PromotionMetrics,
    RiskDecisionOutcome,
    RiskGate,
    RiskGateConfig,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.models import (
    Action,
    BlastRadius,
    BlastRadiusScope,
    Mode,
    OntologyActionType,
    Operation,
    RollbackKind,
    RollbackRef,
    Rule,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
CATALOG_ROOT = REPO_ROOT / "rule-catalog" / "catalog"
POLICIES_ROOT = REPO_ROOT / "policies"
REMEDIATION_ROOT = REPO_ROOT / "rule-catalog" / "remediation"
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"


def _shipped_action_types() -> dict[str, OntologyActionType]:
    registry = PackageResourceSchemaRegistry()
    return {
        a.name: a for a in load_action_type_catalog(ACTION_TYPES_ROOT, schema_registry=registry)
    }


def _shipped_rules_by_id() -> dict[str, Rule]:
    registry = PackageResourceSchemaRegistry()
    action_types = load_action_type_catalog(ACTION_TYPES_ROOT, schema_registry=registry)
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
    return {r.id: r for r in rules}


def _action(
    *,
    action_type: str = "remediate.tag-add",
    count: int | None = 1,
    rate: int | None = 5,
    scope: BlastRadiusScope = BlastRadiusScope.RESOURCE,
    citing_rules: list[str] | None = None,
) -> Action:
    return Action(
        schema_version="1.0.0",
        action_id="00000000-0000-0000-0000-000000000042",  # type: ignore[arg-type]
        idempotency_key="k1",
        event_id="00000000-0000-0000-0000-000000000041",  # type: ignore[arg-type]
        action_type=action_type,
        target_resource_ref="resource:example/rg/x",
        operation=Operation.TAG,
        params={},
        stop_condition="target_state_reached",
        rollback_ref=RollbackRef(kind=RollbackKind.PR_REVERT, reference=None),
        blast_radius=BlastRadius(scope=scope, count=count, rate_per_minute=rate),
        mode=Mode.SHADOW,
        citing_rules=citing_rules or ["object-storage.owner-tag.required"],
        created_at="2026-07-05T08:00:00Z",  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Construction guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override,message",
    [
        ({"max_affected_resources": 0}, "max_affected_resources"),
        ({"max_rate_per_minute": 0}, "max_rate_per_minute"),
        ({"max_precondition_age_seconds": -1}, "max_precondition_age_seconds"),
    ],
)
def test_invalid_config_is_rejected(override: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        RiskGate(
            registry=ActionPromotionRegistry(),
            config=RiskGateConfig(**override),
        )


# ---------------------------------------------------------------------------
# Shadow-mode default behaviour
# ---------------------------------------------------------------------------


def test_action_in_shadow_mode_returns_hil() -> None:
    registry = ActionPromotionRegistry()
    gate = RiskGate(registry=registry)
    action = _action()
    action_type = _shipped_action_types()["remediate.tag-add"]
    rule = _shipped_rules_by_id()["object-storage.owner-tag.required"]
    decision = gate.evaluate(
        action=action,
        rule=rule,
        action_type=action_type,
        inventory_age_seconds=60,
    )
    assert decision.outcome is RiskDecisionOutcome.HIL
    assert decision.effective_mode is Mode.SHADOW
    assert "action_type_in_shadow_mode" in decision.reasons


# ---------------------------------------------------------------------------
# Blast-radius invariants
# ---------------------------------------------------------------------------


def _enforced_registry(action_type_name: str) -> ActionPromotionRegistry:
    """Promote ``action_type_name`` to ENFORCE so shadow-mode is not the reason."""
    registry = ActionPromotionRegistry()
    at = _shipped_action_types()[action_type_name]
    metrics = PromotionMetrics(
        action_type=at.name,
        shadow_days=at.promotion_gate.min_shadow_days,
        samples=at.promotion_gate.min_samples,
        accuracy=1.0,
        policy_escapes=0,
    )
    registry.consider_promotion(action_type=at, metrics=metrics)
    return registry


@pytest.mark.parametrize(
    ("scope", "fail_closed"),
    [
        (BlastRadiusScope.RESOURCE, False),
        (BlastRadiusScope.RESOURCE_GROUP, True),
        (BlastRadiusScope.SUBSCRIPTION, True),
    ],
)
def test_unknown_count_fails_closed_by_scope(scope: BlastRadiusScope, fail_closed: bool) -> None:
    # A partial Action with count=None MUST NOT fail open to AUTO in
    # enforce mode when the scope is broader than a single resource - the
    # blast radius is then unbounded. A single-resource scope is
    # inherently bounded and stays AUTO.
    registry = _enforced_registry("remediate.disable-public-access")
    gate = RiskGate(registry=registry)
    at = _shipped_action_types()["remediate.disable-public-access"]
    rule = _shipped_rules_by_id()["object-storage.public-access.deny"]
    action = _action(
        action_type="remediate.disable-public-access",
        citing_rules=["object-storage.public-access.deny"],
        count=None,
        scope=scope,
    )
    decision = gate.evaluate(action=action, rule=rule, action_type=at, inventory_age_seconds=60)
    if fail_closed:
        assert decision.outcome is RiskDecisionOutcome.HIL
        assert any("blast_radius_count_unknown_for_scope" in r for r in decision.reasons)
    else:
        assert decision.outcome is RiskDecisionOutcome.AUTO
        assert not any("blast_radius" in r for r in decision.reasons)


def test_blast_radius_over_count_cap_is_hil() -> None:
    gate = RiskGate(
        registry=ActionPromotionRegistry(),
        config=RiskGateConfig(max_affected_resources=5),
    )
    action_type = _shipped_action_types()["remediate.tag-add"]
    rule = _shipped_rules_by_id()["object-storage.owner-tag.required"]
    decision = gate.evaluate(
        action=_action(count=10),
        rule=rule,
        action_type=action_type,
        inventory_age_seconds=60,
    )
    assert decision.outcome is RiskDecisionOutcome.HIL
    assert any("blast_radius_count" in r for r in decision.reasons)


def test_blast_radius_over_rate_cap_is_hil() -> None:
    gate = RiskGate(
        registry=ActionPromotionRegistry(),
        config=RiskGateConfig(max_rate_per_minute=1),
    )
    action_type = _shipped_action_types()["remediate.tag-add"]
    rule = _shipped_rules_by_id()["object-storage.owner-tag.required"]
    decision = gate.evaluate(
        action=_action(rate=10),
        rule=rule,
        action_type=action_type,
        inventory_age_seconds=60,
    )
    assert decision.outcome is RiskDecisionOutcome.HIL
    assert any("blast_radius_rate" in r for r in decision.reasons)


# ---------------------------------------------------------------------------
# Precondition age
# ---------------------------------------------------------------------------


def test_stale_inventory_precondition_is_hil() -> None:
    """`remediate.disable-public-access` declares `graph_fresh_within_seconds: 300`."""
    gate = RiskGate(registry=ActionPromotionRegistry())
    action_type = _shipped_action_types()["remediate.disable-public-access"]
    rule = _shipped_rules_by_id()["object-storage.public-access.deny"]
    action = _action(
        action_type="remediate.disable-public-access",
        citing_rules=["object-storage.public-access.deny"],
    )
    decision = gate.evaluate(
        action=action,
        rule=rule,
        action_type=action_type,
        inventory_age_seconds=999,  # way over the 300s declared floor
    )
    assert decision.outcome is RiskDecisionOutcome.HIL
    assert any("graph_fresh_precondition_stale" in r for r in decision.reasons)


def test_fresh_inventory_passes_precondition_check() -> None:
    registry = ActionPromotionRegistry()
    # Promote first so mode is ENFORCE - otherwise shadow-mode default HIL wins.
    action_type = _shipped_action_types()["remediate.disable-public-access"]
    metrics = PromotionMetrics(
        action_type=action_type.name,
        shadow_days=action_type.promotion_gate.min_shadow_days,
        samples=action_type.promotion_gate.min_samples,
        accuracy=1.0,
        policy_escapes=0,
    )
    record = registry.consider_promotion(action_type=action_type, metrics=metrics)
    assert record.mode is Mode.ENFORCE

    gate = RiskGate(registry=registry)
    rule = _shipped_rules_by_id()["object-storage.public-access.deny"]
    action = _action(
        action_type="remediate.disable-public-access",
        citing_rules=["object-storage.public-access.deny"],
    )
    decision = gate.evaluate(
        action=action,
        rule=rule,
        action_type=action_type,
        inventory_age_seconds=60,
    )
    assert decision.outcome is RiskDecisionOutcome.AUTO
    assert decision.reasons == ()


# ---------------------------------------------------------------------------
# Irreversible ActionType
# ---------------------------------------------------------------------------


def test_irreversible_action_type_forces_hil() -> None:
    """An ActionType marked ``irreversible: true`` is HIL regardless of mode.

    We synthesize a modified copy of a shipped ActionType (same shape,
    irreversible flag on) so the test does not depend on the shipped
    catalog carrying an irreversible entry today.
    """
    src = _shipped_action_types()["remediate.tag-add"]
    irreversible = src.model_copy(update={"irreversible": True})

    registry = ActionPromotionRegistry()
    # Promote so shadow-mode is not the reason it's HIL.
    metrics = PromotionMetrics(
        action_type=irreversible.name,
        shadow_days=irreversible.promotion_gate.min_shadow_days,
        samples=irreversible.promotion_gate.min_samples,
        accuracy=1.0,
        policy_escapes=0,
    )
    registry.consider_promotion(action_type=irreversible, metrics=metrics)

    gate = RiskGate(registry=registry)
    rule = _shipped_rules_by_id()["object-storage.owner-tag.required"]
    decision = gate.evaluate(
        action=_action(),
        rule=rule,
        action_type=irreversible,
        inventory_age_seconds=60,
    )
    assert decision.outcome is RiskDecisionOutcome.HIL
    assert any("irreversible" in r for r in decision.reasons)


# ---------------------------------------------------------------------------
# ActionPromotionRegistry
# ---------------------------------------------------------------------------


def test_promotion_registry_defaults_to_shadow_for_unknown_action_type() -> None:
    registry = ActionPromotionRegistry()
    assert registry.mode_of("remediate.never-registered") is Mode.SHADOW


def test_promotion_registry_promotes_when_metrics_pass_gate() -> None:
    registry = ActionPromotionRegistry()
    action_type = _shipped_action_types()["remediate.tag-add"]
    gate = action_type.promotion_gate
    metrics = PromotionMetrics(
        action_type=action_type.name,
        shadow_days=gate.min_shadow_days,
        samples=gate.min_samples,
        accuracy=1.0,
        policy_escapes=0,
    )
    record = registry.consider_promotion(action_type=action_type, metrics=metrics)
    assert record.mode is Mode.ENFORCE
    assert record.promoted_at is not None
    assert registry.mode_of(action_type.name) is Mode.ENFORCE


def test_promotion_registry_demotes_when_metrics_regress() -> None:
    registry = ActionPromotionRegistry()
    action_type = _shipped_action_types()["remediate.tag-add"]
    gate = action_type.promotion_gate
    good = PromotionMetrics(
        action_type=action_type.name,
        shadow_days=gate.min_shadow_days,
        samples=gate.min_samples,
        accuracy=1.0,
        policy_escapes=0,
    )
    registry.consider_promotion(action_type=action_type, metrics=good)

    bad = PromotionMetrics(
        action_type=action_type.name,
        shadow_days=gate.min_shadow_days,
        samples=gate.min_samples,
        accuracy=gate.min_accuracy - 0.5,
        policy_escapes=gate.max_policy_escapes + 1,
    )
    record = registry.consider_promotion(action_type=action_type, metrics=bad)
    assert record.mode is Mode.SHADOW
    assert record.demoted_at is not None
    assert registry.mode_of(action_type.name) is Mode.SHADOW


def test_promotion_registry_rejects_mismatched_metrics() -> None:
    registry = ActionPromotionRegistry()
    action_type = _shipped_action_types()["remediate.tag-add"]
    metrics = PromotionMetrics(
        action_type="remediate.something-else",
        shadow_days=1,
        samples=1,
        accuracy=1.0,
        policy_escapes=0,
    )
    with pytest.raises(ValueError, match="metrics.action_type"):
        registry.consider_promotion(action_type=action_type, metrics=metrics)


def test_promotion_registry_record_returns_current_state() -> None:
    registry = ActionPromotionRegistry()
    assert registry.record("remediate.tag-add") is None
    action_type = _shipped_action_types()["remediate.tag-add"]
    gate = action_type.promotion_gate
    metrics = PromotionMetrics(
        action_type=action_type.name,
        shadow_days=gate.min_shadow_days,
        samples=gate.min_samples,
        accuracy=1.0,
        policy_escapes=0,
    )
    registry.consider_promotion(action_type=action_type, metrics=metrics)
    record = registry.record(action_type.name)
    assert record is not None
    assert record.mode is Mode.ENFORCE


# ---------------------------------------------------------------------------
# Duration helper (property test)
# ---------------------------------------------------------------------------


def test_duration_since_is_non_negative() -> None:
    from fdai.core.risk_gate import duration_since

    past = datetime.now(tz=UTC).replace(year=2024)
    delta = duration_since(past)
    assert delta.total_seconds() >= 0


# ---------------------------------------------------------------------------
# Fail-close: missing precondition age when ActionType demands freshness
# ---------------------------------------------------------------------------


def test_missing_inventory_age_forces_hil_when_precondition_required() -> None:
    """`remediate.tag-add` declares `graph_fresh_within_seconds`. If the
    caller omits ``inventory_age_seconds``, the gate MUST fail-close to HIL
    (coding-conventions § Error Handling and Boundaries)."""
    registry = ActionPromotionRegistry()
    # Even in enforce mode, missing age is still HIL.
    action_type = _shipped_action_types()["remediate.tag-add"]
    metrics = PromotionMetrics(
        action_type=action_type.name,
        shadow_days=action_type.promotion_gate.min_shadow_days,
        samples=action_type.promotion_gate.min_samples,
        accuracy=1.0,
        policy_escapes=0,
    )
    registry.consider_promotion(action_type=action_type, metrics=metrics)
    gate = RiskGate(registry=registry)
    rule = _shipped_rules_by_id()["object-storage.owner-tag.required"]
    decision = gate.evaluate(action=_action(), rule=rule, action_type=action_type)
    assert decision.outcome is RiskDecisionOutcome.HIL
    assert "graph_fresh_precondition_unknown_age" in decision.reasons


# ---------------------------------------------------------------------------
# Upstream verifier signals: DENY short-circuit, ABSTAIN pass-through
# ---------------------------------------------------------------------------


def test_upstream_deny_short_circuits_to_deny_outcome() -> None:
    """A T2 quality-gate DENY MUST propagate through the risk gate as DENY,
    dominating every other check."""
    gate = RiskGate(registry=ActionPromotionRegistry())
    action_type = _shipped_action_types()["remediate.tag-add"]
    rule = _shipped_rules_by_id()["object-storage.owner-tag.required"]
    decision = gate.evaluate(
        action=_action(),
        rule=rule,
        action_type=action_type,
        inventory_age_seconds=60,
        upstream_signal="deny",
    )
    assert decision.outcome is RiskDecisionOutcome.DENY
    assert "upstream_verifier_deny" in decision.reasons


def test_upstream_abstain_produces_abstain_when_no_other_reason() -> None:
    """`upstream_signal=abstain` on an otherwise clean action → ABSTAIN.

    Requires the ActionType to be already promoted so shadow-mode is not
    the reason we route to HIL.
    """
    registry = ActionPromotionRegistry()
    action_type = _shipped_action_types()["remediate.tag-add"]
    metrics = PromotionMetrics(
        action_type=action_type.name,
        shadow_days=action_type.promotion_gate.min_shadow_days,
        samples=action_type.promotion_gate.min_samples,
        accuracy=1.0,
        policy_escapes=0,
    )
    registry.consider_promotion(action_type=action_type, metrics=metrics)

    gate = RiskGate(registry=registry)
    rule = _shipped_rules_by_id()["object-storage.owner-tag.required"]
    decision = gate.evaluate(
        action=_action(),
        rule=rule,
        action_type=action_type,
        inventory_age_seconds=60,
        upstream_signal="abstain",
    )
    assert decision.outcome is RiskDecisionOutcome.ABSTAIN
    assert decision.reasons == ("upstream_verifier_abstain",)


def test_upstream_abstain_yields_to_hil_when_other_reason_present() -> None:
    """When the gate would already HIL (shadow mode, over-cap, ...) an
    upstream abstain must NOT downgrade that to a soft abstain."""
    gate = RiskGate(registry=ActionPromotionRegistry())  # shadow default
    action_type = _shipped_action_types()["remediate.tag-add"]
    rule = _shipped_rules_by_id()["object-storage.owner-tag.required"]
    decision = gate.evaluate(
        action=_action(),
        rule=rule,
        action_type=action_type,
        inventory_age_seconds=60,
        upstream_signal="abstain",
    )
    assert decision.outcome is RiskDecisionOutcome.HIL
    assert "action_type_in_shadow_mode" in decision.reasons


def test_declared_graph_fresh_seconds_raises_when_value_is_non_numeric() -> None:
    """A malformed ActionType (graph_fresh precondition without a numeric
    value) MUST surface at first use - never silently defaulted."""
    from fdai.core.risk_gate.gate import _declared_graph_fresh_seconds
    from fdai.shared.contracts.models import (
        ActionPrecondition,
        PreconditionKind,
    )

    src = _shipped_action_types()["remediate.tag-add"]
    # Overwrite preconditions with a single non-numeric one.
    bogus = src.model_copy(
        update={
            "preconditions": [
                ActionPrecondition(
                    kind=PreconditionKind.GRAPH_FRESH_WITHIN_SECONDS,
                    value="soon",
                )
            ]
        }
    )
    with pytest.raises(ValueError, match="graph_fresh_within_seconds"):
        _declared_graph_fresh_seconds(bogus)


# ---------------------------------------------------------------------------
# Human Override integration
# ---------------------------------------------------------------------------


def test_active_exemption_short_circuits_to_abstain() -> None:
    """A scoped human-override MUST suppress execution even when every
    other check would have returned AUTO (architecture.instructions
    § Human Override)."""
    from fdai.shared.providers.exemption import (
        InMemoryExemptionRecord,
        InMemoryExemptionRegistry,
    )

    registry = ActionPromotionRegistry()
    action_type = _shipped_action_types()["remediate.tag-add"]
    # Promote so shadow-mode is NOT the reason we return non-AUTO.
    metrics = PromotionMetrics(
        action_type=action_type.name,
        shadow_days=action_type.promotion_gate.min_shadow_days,
        samples=action_type.promotion_gate.min_samples,
        accuracy=1.0,
        policy_escapes=0,
    )
    registry.consider_promotion(action_type=action_type, metrics=metrics)

    exemption_registry = InMemoryExemptionRegistry(
        records=(
            InMemoryExemptionRecord(
                exemption_id="exempt-42",
                rule_id="object-storage.owner-tag.required",
                resource_group=None,
                resource_ref="resource:example/rg/x",  # matches _action target
                expires_at=datetime.now(tz=UTC).replace(year=2099),
                justification="vetted legacy workload",
            ),
        )
    )
    gate = RiskGate(registry=registry, exemption_registry=exemption_registry)
    rule = _shipped_rules_by_id()["object-storage.owner-tag.required"]
    decision = gate.evaluate(
        action=_action(),
        rule=rule,
        action_type=action_type,
        inventory_age_seconds=60,
    )
    assert decision.outcome is RiskDecisionOutcome.ABSTAIN
    assert any("exempt-42" in r for r in decision.reasons)


def test_no_exemption_match_yields_normal_outcome() -> None:
    """A registry with no matching exemption MUST not affect the
    outcome - proves the override path is scope-bounded."""
    from fdai.shared.providers.exemption import (
        InMemoryExemptionRecord,
        InMemoryExemptionRegistry,
    )

    registry = ActionPromotionRegistry()
    action_type = _shipped_action_types()["remediate.tag-add"]
    metrics = PromotionMetrics(
        action_type=action_type.name,
        shadow_days=action_type.promotion_gate.min_shadow_days,
        samples=action_type.promotion_gate.min_samples,
        accuracy=1.0,
        policy_escapes=0,
    )
    registry.consider_promotion(action_type=action_type, metrics=metrics)

    # Exemption exists but on a DIFFERENT rule → no match → AUTO.
    exemption_registry = InMemoryExemptionRegistry(
        records=(
            InMemoryExemptionRecord(
                exemption_id="exempt-99",
                rule_id="some.other.rule.id",
                resource_group=None,
                resource_ref="resource:example/rg/x",
                expires_at=datetime.now(tz=UTC).replace(year=2099),
                justification="unrelated",
            ),
        )
    )
    gate = RiskGate(registry=registry, exemption_registry=exemption_registry)
    rule = _shipped_rules_by_id()["object-storage.owner-tag.required"]
    decision = gate.evaluate(
        action=_action(),
        rule=rule,
        action_type=action_type,
        inventory_age_seconds=60,
    )
    assert decision.outcome is RiskDecisionOutcome.AUTO
    assert decision.reasons == ()


def test_exemption_registry_extract_resource_group_helper() -> None:
    """The ARM-id parser used at the risk-gate MUST cope with real ARM ids."""
    from fdai.core.risk_gate.gate import _extract_resource_group

    arm_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000000/"
        "resourceGroups/rg-example/providers/Microsoft.Storage/storageAccounts/foo"
    )
    assert _extract_resource_group(arm_id) == "rg-example"
    assert _extract_resource_group("bare-string") is None
    # Case-insensitive on the segment key.
    assert (
        _extract_resource_group("/subscriptions/x/resourcegroups/rg-lower/providers/y/z")
        == "rg-lower"
    )
