"""ActionType catalog loader + shipped ActionType invariants.

Enforces at test-time what the schema guarantees at load-time, plus P1
policy rules:
- Every shipped ActionType is `default_mode: shadow`.
- `rollback_contract` never falls back to a legacy `none` value.
- Every ActionType names a registered `operation`, and irreversible
  actions carry the explicit `irreversible: true` flag.
- Duplicate ActionType names across files fail-close.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fdai.rule_catalog.schema.action_type import (
    ActionTypeCatalogError,
    load_action_type_catalog,
    load_action_type_from_mapping,
)
from fdai.shared.contracts.models import Mode, Operation, RollbackKind
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_ROOT = REPO_ROOT / "rule-catalog" / "action-types"


def _registry() -> PackageResourceSchemaRegistry:
    return PackageResourceSchemaRegistry()


def test_shipped_action_types_load() -> None:
    catalog = load_action_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    names = {a.name for a in catalog}
    # P1 initial 5 (change if the shipped set grows).
    assert names >= {
        "remediate.disable-public-access",
        "remediate.tag-add",
        "remediate.right-size",
        "remediate.rotate-secret",
        "remediate.enable-tde",
    }


def test_every_shipped_action_type_defaults_to_shadow() -> None:
    catalog = load_action_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    for action in catalog:
        assert action.default_mode is Mode.SHADOW, (
            f"{action.name}: default_mode MUST be shadow in upstream"
        )


def test_every_shipped_action_type_has_a_rollback_contract() -> None:
    catalog = load_action_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    valid = {
        RollbackKind.PR_REVERT,
        RollbackKind.SCRIPTED,
        RollbackKind.PITR,
        RollbackKind.SNAPSHOT_RESTORE,
        RollbackKind.STATE_FORWARD_ONLY,
    }
    for action in catalog:
        assert action.rollback_contract in valid, (
            f"{action.name}: rollback_contract MUST be a live enum value"
        )


def test_promotion_gate_criteria_are_measurable() -> None:
    catalog = load_action_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    for action in catalog:
        gate = action.promotion_gate
        assert gate.min_shadow_days >= 1
        assert gate.min_samples >= 1
        assert 0.0 <= gate.min_accuracy <= 1.0
        assert gate.max_policy_escapes >= 0


def test_operations_are_from_the_documented_verb_set() -> None:
    catalog = load_action_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    seen = {a.operation for a in catalog}
    # Every ActionType operation MUST come from the Operation enum. The
    # exact set expands as new ActionTypes ship; the invariant is that
    # nothing in the catalog uses a verb outside the ontology.
    assert seen.issubset(set(Operation))
    # Guard against an empty catalog going unnoticed.
    assert len(seen) >= 5


def test_default_mode_enforce_in_upstream_is_rejected() -> None:
    raw = {
        "schema_version": "1.0.0",
        "name": "remediate.example",
        "version": "1.0.0",
        "operation": "tag",
        "interfaces": ["ControlPlane"],
        "rollback_contract": "pr_revert",
        "default_mode": "enforce",  # forbidden in upstream
        "promotion_gate": {
            "min_shadow_days": 1,
            "min_samples": 1,
            "min_accuracy": 0.9,
            "max_policy_escapes": 0,
        },
    }
    with pytest.raises(ActionTypeCatalogError) as info:
        load_action_type_from_mapping(raw, schema_registry=_registry())
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "shadow" in joined


def test_rollback_none_is_rejected_by_schema(tmp_path: Path) -> None:
    file = tmp_path / "bad.yaml"
    file.write_text(
        (
            'schema_version: "1.0.0"\n'
            "name: remediate.bad-none\n"
            'version: "1.0.0"\n'
            "operation: tag\n"
            "interfaces: [ControlPlane]\n"
            "rollback_contract: none\n"  # <- disallowed
            "default_mode: shadow\n"
            "promotion_gate:\n"
            "  min_shadow_days: 1\n"
            "  min_samples: 1\n"
            "  min_accuracy: 0.9\n"
            "  max_policy_escapes: 0\n"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ActionTypeCatalogError) as info:
        load_action_type_catalog(tmp_path, schema_registry=_registry())
    joined = " ".join(i.message for i in info.value.issues).lower()
    # The schema enum error names the offending value; either way the load
    # MUST fail so `none` cannot silence the safety invariant.
    assert "'none'" in joined or "none is not" in joined
    # And the offending property path MUST surface for the reviewer.
    keys = " ".join(i.key for i in info.value.issues).lower()
    assert "rollback_contract" in keys


def test_duplicate_name_across_files_is_rejected(tmp_path: Path) -> None:
    body = (
        'schema_version: "1.0.0"\n'
        "name: remediate.dup\n"
        'version: "1.0.0"\n'
        "operation: tag\n"
        "interfaces: [ControlPlane]\n"
        "rollback_contract: pr_revert\n"
        "default_mode: shadow\n"
        "promotion_gate:\n"
        "  min_shadow_days: 1\n"
        "  min_samples: 1\n"
        "  min_accuracy: 0.9\n"
        "  max_policy_escapes: 0\n"
    )
    (tmp_path / "a.yaml").write_text(body, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(body, encoding="utf-8")
    with pytest.raises(ActionTypeCatalogError) as info:
        load_action_type_catalog(tmp_path, schema_registry=_registry())
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "duplicate" in joined


def test_invalid_yaml_reports_the_file(tmp_path: Path) -> None:
    (tmp_path / "broken.yaml").write_text(":\n  - invalid: [\n", encoding="utf-8")
    with pytest.raises(ActionTypeCatalogError) as info:
        load_action_type_catalog(tmp_path, schema_registry=_registry())
    keys = " ".join(i.key for i in info.value.issues)
    assert "broken.yaml" in keys
    assert any("invalid YAML" in i.message for i in info.value.issues)


def test_top_level_not_a_mapping_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "list.yaml").write_text("- just_a_list_item\n", encoding="utf-8")
    with pytest.raises(ActionTypeCatalogError) as info:
        load_action_type_catalog(tmp_path, schema_registry=_registry())
    assert any("top-level" in i.message for i in info.value.issues)


def test_action_type_names_helper_agrees_with_catalog() -> None:
    from fdai.rule_catalog.schema.action_type import action_type_names

    catalog = load_action_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    names = action_type_names(catalog)
    assert names == {a.name for a in catalog}
    assert "remediate.tag-add" in names


def _ops_mapping(**extra: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "schema_version": "1.0.0",
        "name": "ops.restart-service",
        "version": "1.0.0",
        "operation": "restart",
        "interfaces": ["ControlPlane", "IdempotentByKey"],
        "rollback_contract": "state_forward_only",
        "default_mode": "shadow",
        "promotion_gate": {
            "min_shadow_days": 7,
            "min_samples": 50,
            "min_accuracy": 0.99,
            "max_policy_escapes": 0,
        },
        "category": "ops",
    }
    raw.update(extra)
    return raw


def test_operator_request_without_argument_schema_is_rejected() -> None:
    raw = _ops_mapping(trigger_kind={"kind": "operator_request"})
    with pytest.raises(ActionTypeCatalogError) as info:
        load_action_type_from_mapping(raw, schema_registry=_registry())
    keys = " ".join(i.key for i in info.value.issues).lower()
    assert "argument_schema" in keys


def test_operator_request_with_argument_schema_loads() -> None:
    raw = _ops_mapping(
        trigger_kind={"kind": "both"},
        argument_schema={"type": "object", "required": ["target_resource_ref"]},
        execution_path="direct_api",
    )
    model = load_action_type_from_mapping(raw, schema_registry=_registry())
    assert model.trigger_kind is not None
    assert model.trigger_kind.kind.value == "both"


def test_rule_violation_without_argument_schema_is_fine() -> None:
    raw = _ops_mapping(trigger_kind={"kind": "rule_violation"})
    model = load_action_type_from_mapping(raw, schema_registry=_registry())
    assert model.argument_schema is None


# --- M1.3: live_probe_ref cross-check against probe catalog ---

PROBES_ROOT = REPO_ROOT / "rule-catalog" / "probes"


def test_shipped_action_types_pass_live_probe_cross_check() -> None:
    """Every shipped ``live_probe_ref`` resolves to a shipped probe id.

    Wired via ``load_action_type_catalog(..., probes_root=...)``; the
    cross-check is Wave M1.3 in the implementation plan. Regression guard
    against a misspelled reference.
    """

    catalog = load_action_type_catalog(
        CATALOG_ROOT,
        schema_registry=_registry(),
        probes_root=PROBES_ROOT,
    )
    # At least one shipped ActionType wires a live probe (ops.scale-in +
    # ops.restart-service after Wave M1.3).
    refs = [a.live_probe_ref for a in catalog if a.live_probe_ref is not None]
    assert refs, "expected at least one ActionType with a live_probe_ref"


def test_unknown_live_probe_ref_is_rejected(tmp_path: Path) -> None:
    """A live_probe_ref pointing at an unknown probe fails the load."""

    bad = tmp_path / "action-types"
    bad.mkdir()
    (bad / "ops.example.yaml").write_text(
        (
            'schema_version: "1.0.0"\n'
            "name: ops.example\n"
            'version: "1.0.0"\n'
            "operation: restart\n"
            "interfaces:\n- ControlPlane\n"
            "rollback_contract: state_forward_only\n"
            "irreversible: true\n"
            "default_mode: shadow\n"
            "promotion_gate:\n"
            "  min_shadow_days: 14\n"
            "  min_samples: 30\n"
            "  min_accuracy: 0.98\n"
            "  max_policy_escapes: 0\n"
            "category: ops\n"
            "trigger_kind:\n  kind: rule_violation\n"
            "execution_path: direct_api\n"
            "live_probe_ref: probe_that_does_not_exist\n"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ActionTypeCatalogError) as info:
        load_action_type_catalog(
            bad,
            schema_registry=_registry(),
            probes_root=PROBES_ROOT,
        )
    joined = " ".join(i.message for i in info.value.issues)
    assert "probe_that_does_not_exist" in joined
    assert "live_probe_ref" in " ".join(i.key for i in info.value.issues)


def test_live_probe_ref_check_is_skipped_when_probes_root_is_none() -> None:
    """Backward compatibility: existing callers pass no ``probes_root``.

    The load must still succeed even when a live_probe_ref points at an
    id no longer present in the probe catalog - callers that pass
    ``probes_root=None`` explicitly opt out of the cross-check.
    """

    catalog = load_action_type_catalog(CATALOG_ROOT, schema_registry=_registry(), probes_root=None)
    assert catalog  # smoke


def test_probes_root_broken_reports_probe_load_error(tmp_path: Path) -> None:
    """A broken probe catalog surfaces as an ActionTypeCatalogError.

    Fail-closed - do not silently disable the cross-check when the
    probe catalog itself is invalid.
    """

    action_types_dir = tmp_path / "action-types"
    action_types_dir.mkdir()
    (action_types_dir / "ops.example.yaml").write_text(
        (
            'schema_version: "1.0.0"\n'
            "name: ops.example\n"
            'version: "1.0.0"\n'
            "operation: restart\n"
            "interfaces:\n- ControlPlane\n"
            "rollback_contract: state_forward_only\n"
            "irreversible: true\n"
            "default_mode: shadow\n"
            "promotion_gate:\n"
            "  min_shadow_days: 14\n"
            "  min_samples: 30\n"
            "  min_accuracy: 0.98\n"
            "  max_policy_escapes: 0\n"
            "category: ops\n"
            "trigger_kind:\n  kind: rule_violation\n"
            "execution_path: direct_api\n"
            "live_probe_ref: vm_traffic_last_5m\n"
        ),
        encoding="utf-8",
    )
    broken_probes = tmp_path / "probes"
    broken_probes.mkdir()
    # Copy schema so the loader enters strict mode, then plant a bad manifest.
    schema_src = PROBES_ROOT / "probe.schema.json"
    (broken_probes / "probe.schema.json").write_text(
        schema_src.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (broken_probes / "bad.yaml").write_text("id: []\n", encoding="utf-8")  # id must be a string
    with pytest.raises(ActionTypeCatalogError) as info:
        load_action_type_catalog(
            action_types_dir,
            schema_registry=_registry(),
            probes_root=broken_probes,
        )
    joined = " ".join(i.key for i in info.value.issues)
    assert "probes" in joined


# --- W2.1/W2.2: doc-declared ops.* + governance.* completeness ---


# Sourced from docs/roadmap/action-ontology.md 3.2. Any addition to the
# doc's ops.* list MUST land a matching YAML; any addition to the YAML
# MUST update the doc.
_DOC_OPS_ACTION_TYPES: frozenset[str] = frozenset(
    {
        "ops.restart-service",
        "ops.scale-out",
        "ops.scale-in",
        "ops.flush-cache",
        "ops.drain-connection",
        "ops.rotate-cert",
        "ops.failover-primary",
        "ops.publish-change-summary",
    }
)

# Sourced from docs/roadmap/action-ontology.md 3.3. Same drift guard.
_DOC_GOVERNANCE_ACTION_TYPES: frozenset[str] = frozenset(
    {
        "governance.promote-action-type",
        "governance.retire-rule",
        "governance.grant-exemption",
        "governance.override-ceiling",
    }
)


def test_every_doc_declared_ops_action_type_ships_as_yaml() -> None:
    catalog = load_action_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    shipped_ops = {a.name for a in catalog if a.name.startswith("ops.")}
    missing = _DOC_OPS_ACTION_TYPES - shipped_ops
    assert not missing, (
        f"action-ontology.md 3.2 declares these ops.* actions but no YAML ships: {sorted(missing)}"
    )


def test_no_extra_ops_action_type_undocumented() -> None:
    catalog = load_action_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    shipped_ops = {a.name for a in catalog if a.name.startswith("ops.")}
    extra = shipped_ops - _DOC_OPS_ACTION_TYPES
    assert not extra, (
        "these ops.* YAMLs are not documented in action-ontology.md 3.2: "
        f"{sorted(extra)}. Update the doc OR the YAML."
    )


def test_every_doc_declared_governance_action_type_ships_as_yaml() -> None:
    catalog = load_action_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    shipped_gov = {a.name for a in catalog if a.name.startswith("governance.")}
    missing = _DOC_GOVERNANCE_ACTION_TYPES - shipped_gov
    assert not missing, (
        "action-ontology.md 3.3 declares these governance.* actions but no YAML ships: "
        f"{sorted(missing)}"
    )


def test_no_extra_governance_action_type_undocumented() -> None:
    catalog = load_action_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    shipped_gov = {a.name for a in catalog if a.name.startswith("governance.")}
    extra = shipped_gov - _DOC_GOVERNANCE_ACTION_TYPES
    assert not extra, (
        "these governance.* YAMLs are not documented in action-ontology.md 3.3: "
        f"{sorted(extra)}. Update the doc OR the YAML."
    )


def test_every_governance_action_type_is_pr_native() -> None:
    """action-ontology.md 3.3: 'Governance actions always use
    execution_path: pr_native - they are catalog-as-code changes and
    MUST land as a reviewed diff.'"""

    from fdai.shared.contracts.models import ExecutionPath

    catalog = load_action_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    for action in catalog:
        if not action.name.startswith("governance."):
            continue
        assert action.execution_path is ExecutionPath.PR_NATIVE, (
            f"{action.name}: governance actions MUST declare "
            f"execution_path: pr_native (got {action.execution_path!r})"
        )


def test_no_shipped_action_type_uses_pr_manual() -> None:
    """R7 collapsed pr_manual into pr_native + require_manual_merge; no
    upstream ActionType should still use the legacy pr_manual value."""

    from fdai.shared.contracts.models import ExecutionPath

    catalog = load_action_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    offenders = [a.name for a in catalog if a.execution_path is ExecutionPath.PR_MANUAL]
    assert not offenders, (
        "R7 (implementation-plan.md 2.6) collapsed pr_manual into pr_native + "
        f"require_manual_merge; these YAMLs still use pr_manual: {sorted(offenders)}"
    )


def test_every_ops_and_governance_declares_execution_path() -> None:
    """Post-F1 backfill invariant: every shipped ops.* and governance.*
    ActionType declares an explicit execution_path (loader accepts None
    for pre-F1 remediate.* rows during migration)."""

    catalog = load_action_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    missing = [
        a.name
        for a in catalog
        if a.name.startswith(("ops.", "governance.")) and a.execution_path is None
    ]
    assert not missing, (
        "these ops./governance ActionTypes lack execution_path: "
        f"{sorted(missing)}. Add 'execution_path: pr_native' or 'direct_api'."
    )


# --- Catalog policy: safety-critical fields the JSON Schema leaves
#     optional MUST be present on a real catalog entry (_check_catalog_policy).


def _complete_ops_yaml(*, omit: str | None = None, argument_schema: str | None = None) -> str:
    """A fully-populated ops ActionType YAML. ``omit`` drops one top-level
    field so a test can prove the catalog loader rejects the gap."""

    blocks: dict[str, str] = {
        "head": (
            'schema_version: "1.0.0"\n'
            "name: ops.example\n"
            'version: "1.0.0"\n'
            "operation: restart\n"
            "interfaces:\n- ControlPlane\n"
            "rollback_contract: state_forward_only\n"
            "irreversible: true\n"
            "default_mode: shadow\n"
            "promotion_gate:\n"
            "  min_shadow_days: 14\n"
            "  min_samples: 30\n"
            "  min_accuracy: 0.98\n"
            "  max_policy_escapes: 0\n"
        ),
        "category": "category: ops\n",
        "trigger_kind": "trigger_kind:\n  kind: rule_violation\n",
        "execution_path": "execution_path: direct_api\n",
        "blast_radius": ("blast_radius:\n  computation: static_enum\n  static_bucket: resource\n"),
        "ceiling_by_tier": (
            "ceiling_by_tier:\n"
            "  t0:\n    max_autonomy: enforce_hil\n    min_role: contributor\n"
            "  t1:\n    max_autonomy: shadow_only\n    min_role: contributor\n"
            "  t2:\n    max_autonomy: shadow_only\n    min_role: approver\n"
        ),
    }
    text = "".join(v for k, v in blocks.items() if k != omit)
    if argument_schema is not None:
        text += argument_schema
    return text


def _write_catalog(tmp_path: Path, body: str) -> Path:
    root = tmp_path / "action-types"
    root.mkdir()
    (root / "ops.example.yaml").write_text(body, encoding="utf-8")
    return root


def test_complete_ops_yaml_baseline_loads(tmp_path: Path) -> None:
    """Sanity: the fully-populated baseline used by the negative tests
    loads cleanly, so a failure below is the omission, not the fixture."""

    root = _write_catalog(tmp_path, _complete_ops_yaml())
    catalog = load_action_type_catalog(root, schema_registry=_registry())
    assert {a.name for a in catalog} == {"ops.example"}


@pytest.mark.parametrize(
    "field",
    ["category", "trigger_kind", "execution_path", "blast_radius", "ceiling_by_tier"],
)
def test_catalog_entry_missing_safety_field_is_rejected(tmp_path: Path, field: str) -> None:
    """A catalog entry that omits any safety-critical field fails closed."""

    root = _write_catalog(tmp_path, _complete_ops_yaml(omit=field))
    with pytest.raises(ActionTypeCatalogError) as info:
        load_action_type_catalog(root, schema_registry=_registry())
    keys = " ".join(i.key for i in info.value.issues)
    assert field in keys, f"expected {field} to surface in issues; got {keys}"


def test_catalog_entry_partial_ceiling_by_tier_is_rejected(tmp_path: Path) -> None:
    """ceiling_by_tier MUST declare all three tiers (t0/t1/t2)."""

    body = _complete_ops_yaml(omit="ceiling_by_tier") + (
        "ceiling_by_tier:\n  t0:\n    max_autonomy: enforce_hil\n    min_role: contributor\n"
    )
    root = _write_catalog(tmp_path, body)
    with pytest.raises(ActionTypeCatalogError) as info:
        load_action_type_catalog(root, schema_registry=_registry())
    assert "ceiling_by_tier" in " ".join(i.key for i in info.value.issues)


def test_argument_schema_without_additional_properties_false_is_rejected(
    tmp_path: Path,
) -> None:
    """An argument_schema that omits additionalProperties: false is rejected
    so the console can never pass unspecified arguments (action-ontology.md 5)."""

    arg = (
        "trigger_kind:\n  kind: operator_request\n"
        "argument_schema:\n"
        "  type: object\n"
        "  required:\n  - target_resource_ref\n"
        "  properties:\n"
        "    target_resource_ref:\n      type: string\n      minLength: 1\n"
    )
    # Baseline omits its own trigger_kind so the arg block supplies it.
    body = _complete_ops_yaml(omit="trigger_kind") + arg
    root = _write_catalog(tmp_path, body)
    with pytest.raises(ActionTypeCatalogError) as info:
        load_action_type_catalog(root, schema_registry=_registry())
    assert "argument_schema" in " ".join(i.key for i in info.value.issues)


def test_argument_schema_hardened_loads(tmp_path: Path) -> None:
    """The hardened form (type: object + additionalProperties: false) loads."""

    arg = (
        "trigger_kind:\n  kind: operator_request\n"
        "argument_schema:\n"
        "  type: object\n"
        "  additionalProperties: false\n"
        "  required:\n  - target_resource_ref\n"
        "  properties:\n"
        "    target_resource_ref:\n      type: string\n      minLength: 1\n"
    )
    body = _complete_ops_yaml(omit="trigger_kind") + arg
    root = _write_catalog(tmp_path, body)
    catalog = load_action_type_catalog(root, schema_registry=_registry())
    assert {a.name for a in catalog} == {"ops.example"}
