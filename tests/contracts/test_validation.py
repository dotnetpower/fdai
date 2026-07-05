"""Validation happens at boundaries only and MUST work with any :class:`SchemaRegistry`.

These tests are the DI evidence: the same validator, wired against a
test-only in-memory registry, behaves identically to when it is wired
against the package-resource default. If someone breaks the Protocol
contract, this suite breaks first.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from aiopspilot.shared.contracts.registry import (
    PackageResourceSchemaRegistry,
    SchemaRegistry,
)
from aiopspilot.shared.contracts.validation import (
    ContractValidationError,
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)

from ..conftest import InMemorySchemaRegistry

# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_event_passes_default_validator(valid_event: dict[str, Any]) -> None:
    registry: SchemaRegistry = PackageResourceSchemaRegistry()
    validator = JsonSchemaContractValidator(registry)
    validator.validate("event", valid_event)


def test_valid_action_passes_default_validator(valid_action: dict[str, Any]) -> None:
    registry: SchemaRegistry = PackageResourceSchemaRegistry()
    validator = JsonSchemaContractValidator(registry)
    validator.validate("action", valid_action)


def test_valid_rule_passes_default_validator(valid_rule: dict[str, Any]) -> None:
    registry: SchemaRegistry = PackageResourceSchemaRegistry()
    validator = JsonSchemaContractValidator(registry)
    validator.validate("rule", valid_rule)


def test_valid_ontology_action_type_passes(
    valid_ontology_action_type: dict[str, Any],
) -> None:
    registry: SchemaRegistry = PackageResourceSchemaRegistry()
    validator = JsonSchemaContractValidator(registry)
    validator.validate("ontology/action-type", valid_ontology_action_type)


# ---------------------------------------------------------------------------
# Fail-closed behaviour
# ---------------------------------------------------------------------------


def test_missing_required_field_raises_structured_error(
    valid_event: dict[str, Any],
) -> None:
    registry: SchemaRegistry = PackageResourceSchemaRegistry()
    validator = JsonSchemaContractValidator(registry)

    broken = dict(valid_event)
    del broken["mode"]  # mode is required and has no default

    with pytest.raises(ContractValidationError) as exc:
        validator.validate("event", broken)
    assert exc.value.schema == "event"
    # At least one issue mentions the missing property.
    assert any("mode" in i.message for i in exc.value.issues)


def test_additional_property_is_rejected(valid_event: dict[str, Any]) -> None:
    registry: SchemaRegistry = PackageResourceSchemaRegistry()
    validator = JsonSchemaContractValidator(registry)

    tampered = dict(valid_event)
    tampered["injected_field"] = "should_be_rejected"

    with pytest.raises(ContractValidationError):
        validator.validate("event", tampered)


def test_action_with_empty_citing_rules_is_rejected(
    valid_action: dict[str, Any],
) -> None:
    """An action MUST cite at least one rule; an empty list = ungrounded."""
    registry: SchemaRegistry = PackageResourceSchemaRegistry()
    validator = JsonSchemaContractValidator(registry)

    ungrounded = dict(valid_action)
    ungrounded["citing_rules"] = []

    with pytest.raises(ContractValidationError):
        validator.validate("action", ungrounded)


def test_action_missing_rollback_ref_is_rejected(
    valid_action: dict[str, Any],
) -> None:
    """Rollback path is a required safety invariant."""
    registry: SchemaRegistry = PackageResourceSchemaRegistry()
    validator = JsonSchemaContractValidator(registry)

    unsafe = dict(valid_action)
    del unsafe["rollback_ref"]

    with pytest.raises(ContractValidationError):
        validator.validate("action", unsafe)


# ---------------------------------------------------------------------------
# DI evidence: swap the SchemaRegistry, validator behaves identically.
# ---------------------------------------------------------------------------


def test_validator_works_with_custom_schema_registry(
    valid_event: dict[str, Any],
) -> None:
    default = PackageResourceSchemaRegistry()
    event_schema = default.get("event")
    fake: SchemaRegistry = cast(
        SchemaRegistry,
        InMemorySchemaRegistry({("event", "1.0.0"): event_schema}),
    )

    validator = JsonSchemaContractValidator(fake)
    validator.validate("event", valid_event)  # passes

    tampered = dict(valid_event)
    tampered["mode"] = "invalid_mode_value"
    with pytest.raises(ContractValidationError):
        validator.validate("event", tampered)


def test_event_validator_matches_underlying_contract_validator(
    valid_event: dict[str, Any],
) -> None:
    registry: SchemaRegistry = PackageResourceSchemaRegistry()
    contract_v = JsonSchemaContractValidator(registry)
    event_v = JsonSchemaEventValidator(contract_v)

    event_v.validate(valid_event)  # passes

    invalid = dict(valid_event)
    invalid["mode"] = "not_a_mode"
    with pytest.raises(ContractValidationError):
        event_v.validate(invalid)
