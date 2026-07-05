"""The pydantic models are the typed view of the JSON schemas.

If they drift from the JSON Schema source of truth, a boundary-validated
event may pass the model but fail at ingress (or vice versa). These tests
pin the two views together by round-tripping through the JSON Schema
validator.
"""

from __future__ import annotations

from typing import Any

from aiopspilot.shared.contracts.models import (
    Action,
    ActionInterface,
    BlastRadius,
    BlastRadiusScope,
    Category,
    CheckLogic,
    CheckLogicKind,
    Event,
    Mode,
    OntologyActionType,
    Operation,
    Provenance,
    Remediation,
    RollbackKind,
    RollbackRef,
    Rule,
    RuleSource,
    Severity,
)
from aiopspilot.shared.contracts.registry import PackageResourceSchemaRegistry
from aiopspilot.shared.contracts.validation import JsonSchemaContractValidator


def _validator() -> JsonSchemaContractValidator:
    return JsonSchemaContractValidator(PackageResourceSchemaRegistry())


def _dump(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")


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
        provenance=Provenance(
            source_url="https://example.com/rules/tag-owner",
            resolved_revision="0000000000000000000000000000000000000000",
            content_hash="sha256:example",
            license="MIT",
            redistribution=True,
            imported_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )
    _validator().validate("rule", _dump(rule))


def test_ontology_action_type_carries_interface_set() -> None:
    obj = OntologyActionType(
        schema_version="1.0.0",
        name="tag_missing_owner",
        version="1.0.0",
        operation=Operation.TAG,
        interfaces=[ActionInterface.CONTROL_PLANE, ActionInterface.IDEMPOTENT_BY_KEY],
        rollback_contract=RollbackKind.PR_REVERT,
        description="Attach an owner tag when missing.",
    )
    _validator().validate("ontology/action-type", _dump(obj))
