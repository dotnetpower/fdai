"""The pydantic models are the typed view of the JSON schemas.

If they drift from the JSON Schema source of truth, a boundary-validated
event may pass the model but fail at ingress (or vice versa). These tests
pin the two views together by round-tripping through the JSON Schema
validator.
"""

from __future__ import annotations

from typing import Any

import pytest

from aiopspilot.shared.contracts.models import (
    Action,
    ActionCategory,
    ActionInterface,
    Autonomy,
    BlastRadius,
    BlastRadiusScope,
    Category,
    CeilingByTier,
    CeilingRole,
    CheckLogic,
    CheckLogicKind,
    EnvScope,
    Event,
    ExecutionPath,
    Mode,
    OntologyActionType,
    Operation,
    ProdDowngrade,
    PromotionGate,
    Provenance,
    Remediation,
    RollbackKind,
    RollbackRef,
    Rule,
    RuleSource,
    Severity,
    TierCeiling,
    TriggerKind,
    TriggerKindDecl,
)
from aiopspilot.shared.contracts.registry import PackageResourceSchemaRegistry
from aiopspilot.shared.contracts.validation import JsonSchemaContractValidator


def _validator() -> JsonSchemaContractValidator:
    return JsonSchemaContractValidator(PackageResourceSchemaRegistry())


def _dump(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=True)


def test_event_model_round_trip(valid_event: dict[str, Any]) -> None:
    event = Event.model_validate(valid_event)
    dumped = _dump(event)
    _validator().validate("event", dumped)


def test_action_model_round_trip(valid_action: dict[str, Any]) -> None:
    action = Action.model_validate(valid_action)
    dumped = _dump(action)
    _validator().validate("action", dumped)


def test_rule_model_round_trip(valid_rule: dict[str, Any]) -> None:
    rule = Rule.model_validate(valid_rule)
    dumped = _dump(rule)
    _validator().validate("rule", dumped)


def test_ontology_action_type_round_trip(
    valid_ontology_action_type: dict[str, Any],
) -> None:
    obj = OntologyActionType.model_validate(valid_ontology_action_type)
    dumped = _dump(obj)
    _validator().validate("ontology/action-type", dumped)


def test_action_model_defaults_shadow_when_constructed_from_code() -> None:
    """Constructed-in-code actions must still carry every safety-invariant field.

    We rely on pydantic to *require* the fields; there is no forgiving default
    that would let a partially-built action leak into the executor.
    """
    action = Action(
        schema_version="1.0.0",
        action_id="00000000-0000-0000-0000-000000000010",  # type: ignore[arg-type]
        idempotency_key="example-idem",
        event_id="00000000-0000-0000-0000-000000000011",  # type: ignore[arg-type]
        action_type="tag_missing_owner",
        target_resource_ref="resource:example/rg/example",
        operation=Operation.TAG,
        stop_condition="target_already_tagged",
        rollback_ref=RollbackRef(kind=RollbackKind.PR_REVERT, reference="example-pr-99"),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1, rate_per_minute=5),
        mode=Mode.SHADOW,
        citing_rules=["example.tag.owner-required"],
        created_at="2026-07-05T08:00:00Z",  # type: ignore[arg-type]
    )
    _validator().validate("action", _dump(action))


def test_rule_model_construction_covers_provenance() -> None:
    rule = Rule(
        schema_version="1.0.0",
        id="example.tag.owner-required",
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.CONFIG_DRIFT,
        resource_type="compute.vm",
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/example.rego"),
        remediation=Remediation(template_ref="remediations/example", cost_impact_monthly_usd=0),
        remediates="remediate.tag-add",
        provenance=Provenance(
            source_url="https://example.com/rules/tag-owner",
            resolved_ref="0000000000000000000000000000000000000000",
            content_hash="sha256:example",
            license="MIT",
            redistribution="embeddable",  # type: ignore[arg-type]
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )
    _validator().validate("rule", _dump(rule))


def test_ontology_action_type_carries_interface_set() -> None:
    obj = OntologyActionType(
        schema_version="1.0.0",
        name="remediate.tag-missing-owner",
        version="1.0.0",
        operation=Operation.TAG,
        interfaces=[ActionInterface.CONTROL_PLANE, ActionInterface.IDEMPOTENT_BY_KEY],
        rollback_contract=RollbackKind.PR_REVERT,
        promotion_gate=PromotionGate(
            min_shadow_days=14,
            min_samples=100,
            min_accuracy=0.95,
            max_policy_escapes=0,
        ),
        description="Attach an owner tag when missing.",
    )
    _validator().validate("ontology/action-type", _dump(obj))


def test_ontology_action_type_execution_authority_fields_round_trip() -> None:
    """Every Day-1 execution-authority extension field survives the JSON Schema round-trip."""
    obj = OntologyActionType(
        schema_version="1.0.0",
        name="ops.restart-service",
        version="1.0.0",
        operation=Operation.RESTART,
        interfaces=[ActionInterface.CONTROL_PLANE, ActionInterface.IDEMPOTENT_BY_KEY],
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        promotion_gate=PromotionGate(
            min_shadow_days=7,
            min_samples=50,
            min_accuracy=0.99,
            max_policy_escapes=0,
        ),
        description="Restart a service in place.",
        category=ActionCategory.OPS,
        trigger_kind=TriggerKindDecl(kind=TriggerKind.BOTH),
        execution_path=ExecutionPath.DIRECT_API,
        ceiling_by_tier=CeilingByTier(
            t0=TierCeiling(max_autonomy=Autonomy.ENFORCE_HIL, min_role=CeilingRole.CONTRIBUTOR),
            t2=TierCeiling(max_autonomy=Autonomy.SHADOW_ONLY, min_role=CeilingRole.APPROVER),
        ),
        env_scope=EnvScope.ANY,
        prod_downgrade=ProdDowngrade(
            mode=Autonomy.ENFORCE_HIL, detection_ref="env_detectors/tag_env_eq_prod"
        ),
        argument_schema={"type": "object", "required": ["target_resource_ref"]},
        live_probe_ref="probes/vm_traffic_last_5m",
    )
    _validator().validate("ontology/action-type", _dump(obj))


def test_prod_downgrade_rejects_enforce_auto() -> None:
    """A prod downgrade can only lower autonomy, never raise it to enforce_auto."""
    with pytest.raises(ValueError, match="never raises autonomy"):
        ProdDowngrade(mode=Autonomy.ENFORCE_AUTO, detection_ref="env_detectors/x")
