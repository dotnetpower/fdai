"""Pin alert-noise declarations to the real loaders without granting runtime authority.

Provenance on shipped entries must be regenerated before these tests can load them.
Synthetic negative fixtures alone are rehashed; catalog hashes are never repaired here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fdai.core.workflow.compiler import compile_workflow
from fdai.core.workflow.workflow_runtime import resolve_params
from fdai.rule_catalog.schema.action_type import (
    ActionTypeCatalogError,
    action_type_names,
    argument_schema_redaction_paths,
    load_action_type_catalog,
    load_action_type_from_mapping,
)
from fdai.rule_catalog.schema.ontology_provenance import ontology_content_hash
from fdai.rule_catalog.schema.workflow import (
    WorkflowCatalogError,
    load_workflow_catalog,
    load_workflow_from_mapping,
    workflow_names,
)
from fdai.shared.contracts.models import (
    ActionInterface,
    Autonomy,
    BlastRadiusComputation,
    BlastRadiusScope,
    CeilingRole,
    ExecutionPath,
    Mode,
    OntologyActionType,
    Operation,
    PreconditionKind,
    RollbackKind,
    StopConditionKind,
    TriggerKind,
    Workflow,
    WorkflowStepKind,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from jsonschema import Draft202012Validator, ValidationError

REPO_ROOT = Path(__file__).resolve().parents[4]
ACTION_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
WORKFLOW_ROOT = REPO_ROOT / "rule-catalog" / "workflows"
RESTORE = "ops.restore-alert-configuration"
WORKFLOW_CASES = (
    ("alert-routing-change", "alert_noise.routing.proposed", "ops.update-alert-routing"),
    (
        "alert-notification-window-change",
        "alert_noise.suppression.proposed",
        "ops.set-alert-notification-window",
    ),
    ("alert-evaluation-change", "alert_noise.evaluation.proposed", "ops.tune-alert-evaluation"),
)
ACTION_NAMES = tuple(case[2] for case in WORKFLOW_CASES) + (RESTORE,)
PLAN_KEY = "event.payload.alert_plan.plan_digest"
PLAN_TEMPLATE = "${event.payload.alert_plan.plan_digest}"
PLAN_DIGEST = "0123456789abcdef" * 4


def _read_mapping(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def _write_action_fixture(root: Path, raw: dict[str, Any]) -> None:
    """Seal only a synthetic fixture so an unrelated hash failure cannot mask policy."""
    raw["provenance"]["content_hash"] = ontology_content_hash(
        OntologyActionType.model_validate(raw)
    )
    (root / "action.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


@pytest.fixture(scope="module")
def registry() -> PackageResourceSchemaRegistry:
    return PackageResourceSchemaRegistry()


@pytest.fixture(scope="module")
def actions(registry: PackageResourceSchemaRegistry) -> dict[str, OntologyActionType]:
    catalog = load_action_type_catalog(ACTION_ROOT, schema_registry=registry)
    assert set(ACTION_NAMES) <= action_type_names(catalog)
    return {item.name: item for item in catalog}


@pytest.fixture(scope="module")
def workflows(
    registry: PackageResourceSchemaRegistry, actions: dict[str, OntologyActionType]
) -> dict[str, Workflow]:
    catalog = load_workflow_catalog(
        WORKFLOW_ROOT,
        schema_registry=registry,
        action_type_names=action_type_names(actions.values()),
    )
    assert {case[0] for case in WORKFLOW_CASES} <= workflow_names(catalog)
    return {item.name: item for item in catalog}


@pytest.mark.parametrize("name", ACTION_NAMES)
def test_alert_actions_pin_manual_owner_hil_and_safeguard_declarations(
    name: str, actions: dict[str, OntologyActionType]
) -> None:
    action = actions[name]
    assert action.category is not None and action.category.value == "ops"
    assert action.operation is Operation.UPDATE
    assert action.execution_path is ExecutionPath.PR_MANUAL
    assert action.default_mode is Mode.SHADOW
    assert action.rollback_contract is RollbackKind.PR_REVERT
    assert action.irreversible is False
    assert action.trigger_kind is not None
    assert action.trigger_kind.kind is TriggerKind.OPERATOR_REQUEST
    assert {
        ActionInterface.CONTROL_PLANE,
        ActionInterface.IDEMPOTENT_BY_KEY,
        ActionInterface.REQUIRES_INVENTORY_FRESH,
        ActionInterface.GRAPH_TRAVERSAL_REQUIRED,
        ActionInterface.REQUIRES_MAINTENANCE_WINDOW,
    } <= set(action.interfaces)
    assert action.blast_radius is not None
    assert action.blast_radius.computation is BlastRadiusComputation.STATIC_ENUM
    assert action.blast_radius.static_bucket is BlastRadiusScope.RESOURCE_GROUP
    assert action.blast_radius.max_affected_resources == 1
    assert action.ceiling_by_tier is not None
    for ceiling in (action.ceiling_by_tier.t0, action.ceiling_by_tier.t1):
        assert ceiling is not None
        assert ceiling.max_autonomy is Autonomy.ENFORCE_HIL
        assert ceiling.min_role is CeilingRole.OWNER
    assert action.ceiling_by_tier.t2 is not None
    assert action.ceiling_by_tier.t2.max_autonomy is Autonomy.SHADOW_ONLY
    assert action.ceiling_by_tier.t2.min_role is CeilingRole.OWNER
    assert action.prod_downgrade is not None
    assert action.prod_downgrade.mode is Autonomy.ENFORCE_HIL
    assert action.prod_downgrade.detection_ref == "risk-classification/env-detector"
    assert [(item.kind, item.value) for item in action.preconditions] == [
        (PreconditionKind.GRAPH_FRESH_WITHIN_SECONDS, 300),
        (PreconditionKind.NO_CONFLICTING_OPEN_ACTION_ON_RESOURCE, None),
        (PreconditionKind.MAINTENANCE_WINDOW_ACTIVE, None),
    ]
    assert [(item.kind, item.count, item.seconds) for item in action.stop_conditions] == [
        (StopConditionKind.PROVIDER_API_ERROR_STREAK, 1, None),
        (StopConditionKind.DEPENDENT_RESOURCE_DEGRADED, None, None),
        (StopConditionKind.TIME_BOX_EXCEEDED_SECONDS, None, 3600),
    ]
    assert action.promotion_gate.min_shadow_days >= 30
    assert action.promotion_gate.min_samples >= 100
    assert action.promotion_gate.min_accuracy == 1.0
    assert action.promotion_gate.max_policy_escapes == 0
    assert action.provenance is not None
    assert action.provenance.resolved_ref == f"action-type:{name}@{action.version}"
    assert action.provenance.content_hash == ontology_content_hash(action)


@pytest.mark.parametrize("name", ACTION_NAMES)
def test_only_the_forward_plan_digest_is_an_argument(
    name: str, actions: dict[str, OntologyActionType]
) -> None:
    action = actions[name]
    schema = action.argument_schema
    assert schema is not None
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["plan_digest"]
    assert set(schema["properties"]) == {"plan_digest"}
    assert schema["properties"]["plan_digest"]["type"] == "string"
    assert schema["properties"]["plan_digest"]["pattern"] == "^[a-f0-9]{64}$"
    assert schema["properties"]["plan_digest"]["minLength"] == 64
    assert schema["properties"]["plan_digest"]["maxLength"] == 64
    assert argument_schema_redaction_paths(action) == frozenset()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate({"plan_digest": PLAN_DIGEST})


@pytest.mark.parametrize("name", ACTION_NAMES)
@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"plan_digest": ""},
        {"plan_digest": "a" * 63},
        {"plan_digest": "a" * 65},
        {"plan_digest": "A" * 64},
        {"plan_digest": "g" * 64},
        {"plan_digest": "sha256:" + PLAN_DIGEST},
        {"plan_digest": PLAN_DIGEST + "\n"},
        {"plan_digest": " " + PLAN_DIGEST},
        {"plan_digest": PLAN_TEMPLATE},
        {"plan_digest": None},
        {"plan_digest": 123},
        {"plan_digest": True},
        {"plan_digest": [PLAN_DIGEST]},
    ],
)
def test_invalid_or_unresolved_plan_arguments_are_rejected(
    name: str, arguments: dict[str, Any], actions: dict[str, OntologyActionType]
) -> None:
    schema = actions[name].argument_schema
    assert schema is not None
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(arguments)


@pytest.mark.parametrize("name", ACTION_NAMES)
@pytest.mark.parametrize(
    "extra",
    [
        "target_resource_ref",
        "provider_target",
        "action_type",
        "changes",
        "threshold",
        "window_end",
        "rollback_ref",
        "restore_plan_digest",
        "command",
        "script",
        "approval",
        "mode",
        "workflow",
    ],
)
def test_generic_mutation_or_authority_arguments_are_rejected(
    name: str, extra: str, actions: dict[str, OntologyActionType]
) -> None:
    schema = actions[name].argument_schema
    assert schema is not None
    with pytest.raises(ValidationError, match="Additional properties"):
        Draft202012Validator(schema).validate({"plan_digest": PLAN_DIGEST, extra: "example"})


@pytest.mark.parametrize(("name", "signal", "action_name"), WORKFLOW_CASES)
def test_canonical_workflow_pins_initial_quorum_and_exact_compensation(
    name: str, signal: str, action_name: str, workflows: dict[str, Workflow]
) -> None:
    workflow = workflows[name]
    assert workflow.default_mode is Mode.SHADOW
    assert workflow.trigger.kind.value == "signal"
    assert workflow.trigger.signal_type == signal
    assert workflow.trigger.schedule is None
    assert workflow.promotion_gate.max_policy_escapes == 0
    assert len(workflow.steps) == 2
    approval, forward = workflow.steps
    assert approval.kind is WorkflowStepKind.APPROVAL
    assert approval.approval_role is CeilingRole.OWNER
    assert approval.quorum == 2 and approval.no_self_approval is True
    assert approval.timeout_seconds == 3600
    assert approval.action_type_ref is None
    assert forward.kind is WorkflowStepKind.ACTION
    assert forward.action_type_ref == action_name
    assert forward.compensated_by == RESTORE
    assert forward.params == {"plan_digest": PLAN_TEMPLATE}
    assert forward.timeout_seconds == 3600
    assert all(step.on_failure is None for step in workflow.steps)
    compiled = compile_workflow(workflow)
    assert compiled.is_shadow is True
    assert compiled.compensations == {forward.id: RESTORE}
    assert compiled.runbook.steps[0].quorum == 2
    assert compiled.runbook.steps[0].no_self_approval is True
    assert compiled.runbook.steps[1].params == forward.params


@pytest.mark.parametrize(("name", "signal", "action_name"), WORKFLOW_CASES)
def test_generic_substitution_preserves_forward_digest_for_restore(
    name: str,
    signal: str,
    action_name: str,
    workflows: dict[str, Workflow],
    actions: dict[str, OntologyActionType],
) -> None:
    assert workflows[name].trigger.signal_type == signal
    forward = workflows[name].steps[1]
    resolved = resolve_params(forward.params, {PLAN_KEY: PLAN_DIGEST})
    assert resolved == {"plan_digest": PLAN_DIGEST}
    for target in (action_name, RESTORE):
        schema = actions[target].argument_schema
        assert schema is not None
        Draft202012Validator(schema).validate(resolved)
        with pytest.raises(ValidationError):
            Draft202012Validator(schema).validate(resolve_params(forward.params, {}))


@pytest.mark.parametrize("name", ACTION_NAMES)
@pytest.mark.parametrize("field", ["execution_path", "ceiling_by_tier", "blast_radius"])
def test_catalog_rejects_missing_authority_boundary_fields(
    name: str, field: str, tmp_path: Path, registry: PackageResourceSchemaRegistry
) -> None:
    raw = _read_mapping(ACTION_ROOT / f"{name}.yaml")
    raw.pop(field)
    _write_action_fixture(tmp_path, raw)
    with pytest.raises(ActionTypeCatalogError) as error:
        load_action_type_catalog(tmp_path, schema_registry=registry)
    assert any(issue.key.endswith(f":{field}") for issue in error.value.issues)


@pytest.mark.parametrize("name", ACTION_NAMES)
@pytest.mark.parametrize("autonomy", ["enforce_auto", "enforce_hil"])
def test_catalog_rejects_nonshadow_t2_ceiling(
    name: str, autonomy: str, tmp_path: Path, registry: PackageResourceSchemaRegistry
) -> None:
    raw = _read_mapping(ACTION_ROOT / f"{name}.yaml")
    raw["ceiling_by_tier"]["t2"]["max_autonomy"] = autonomy
    _write_action_fixture(tmp_path, raw)
    with pytest.raises(ActionTypeCatalogError, match="t2.max_autonomy"):
        load_action_type_catalog(tmp_path, schema_registry=registry)


def test_catalog_rejects_unpromoted_enforce_and_open_argument_schema(
    tmp_path: Path, registry: PackageResourceSchemaRegistry
) -> None:
    raw = _read_mapping(ACTION_ROOT / f"{RESTORE}.yaml")
    raw["default_mode"] = "enforce"
    with pytest.raises(ActionTypeCatalogError, match="default_mode"):
        load_action_type_from_mapping(raw, schema_registry=registry)
    raw["default_mode"] = "shadow"
    raw["argument_schema"]["additionalProperties"] = True
    _write_action_fixture(tmp_path, raw)
    with pytest.raises(ActionTypeCatalogError, match="additionalProperties: false"):
        load_action_type_catalog(tmp_path, schema_registry=registry)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("no_self_approval", False),
        ("quorum", 0),
        ("approval_role", "breakglass"),
        ("timeout_seconds", None),
        ("action_type_ref", "ops.update-alert-routing"),
    ],
)
def test_workflow_loader_rejects_unsafe_approval_controls(
    field: str, value: object, registry: PackageResourceSchemaRegistry
) -> None:
    raw = _read_mapping(WORKFLOW_ROOT / "alert-routing-change.yaml")
    raw["steps"][0][field] = value
    with pytest.raises(WorkflowCatalogError):
        load_workflow_from_mapping(
            raw, schema_registry=registry, action_type_names=set(ACTION_NAMES)
        )


@pytest.mark.parametrize("field", ["action_type_ref", "compensated_by"])
def test_workflow_loader_rejects_unregistered_generic_helpers(
    field: str, registry: PackageResourceSchemaRegistry
) -> None:
    raw = _read_mapping(WORKFLOW_ROOT / "alert-routing-change.yaml")
    raw["steps"][1][field] = "tool.unregistered-alert-helper"
    with pytest.raises(WorkflowCatalogError, match="unknown ActionType"):
        load_workflow_from_mapping(
            raw, schema_registry=registry, action_type_names=set(ACTION_NAMES)
        )


def test_workflow_loader_rejects_inline_mutation_logic(
    registry: PackageResourceSchemaRegistry,
) -> None:
    raw = _read_mapping(WORKFLOW_ROOT / "alert-routing-change.yaml")
    raw["steps"][1]["script"] = "not-an-action-type"
    with pytest.raises(WorkflowCatalogError, match="Additional properties"):
        load_workflow_from_mapping(
            raw, schema_registry=registry, action_type_names=set(ACTION_NAMES)
        )


def test_changed_stop_condition_invalidates_provenance(
    tmp_path: Path, registry: PackageResourceSchemaRegistry
) -> None:
    raw = _read_mapping(ACTION_ROOT / f"{RESTORE}.yaml")
    _write_action_fixture(tmp_path, raw)
    raw["stop_conditions"][-1]["seconds"] = 1800
    (tmp_path / "action.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(ActionTypeCatalogError, match="provenance.content_hash mismatch"):
        load_action_type_catalog(tmp_path, schema_registry=registry)
