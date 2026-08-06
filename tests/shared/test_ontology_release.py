"""Exact ontology release identity tests."""

from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from fdai.shared.contracts.models import (
    OntologyActionType,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyReleaseRef,
    Operation,
    PromotionGate,
    RollbackKind,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release


def _action(name: str, version: str = "1.0.0") -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name=name,
        version=version,
        operation=Operation.UPDATE,
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        promotion_gate=PromotionGate(
            min_shadow_days=1,
            min_samples=1,
            min_accuracy=1.0,
            max_policy_escapes=0,
        ),
    )


def test_release_digest_is_order_independent_and_version_sensitive() -> None:
    first = _action("ops.alpha")
    second = _action("ops.beta")

    release = build_ontology_release(action_types=(first, second))
    reordered = build_ontology_release(action_types=(second, first))
    revised = build_ontology_release(action_types=(first, _action("ops.beta", "2.0.0")))

    assert release.digest == reordered.digest
    assert release.digest != revised.digest


def test_release_returns_exact_type_reference() -> None:
    release = build_ontology_release(action_types=(_action("ops.alpha"),))

    reference = release.type_ref(OntologyDeclarationKind.ACTION, "ops.alpha")

    assert reference.version == "1.0.0"
    assert reference.catalog_digest == release.digest


def test_release_reference_round_trips_through_wire_schema() -> None:
    reference = build_ontology_release(action_types=(_action("ops.alpha"),)).ref()
    payload = reference.model_dump(mode="json")
    schema = PackageResourceSchemaRegistry().get("ontology/release-ref")

    Draft202012Validator(schema).validate(payload)
    decoded = OntologyReleaseRef.model_validate_json(reference.model_dump_json())

    assert decoded == reference
    assert payload == {"schema_version": "1.0.0", "digest": reference.digest}


def test_release_reference_rejects_missing_or_invalid_digest() -> None:
    schema = PackageResourceSchemaRegistry().get("ontology/release-ref")
    validator = Draft202012Validator(schema)

    with pytest.raises(ValidationError):
        validator.validate({"schema_version": "1.0.0"})
    with pytest.raises(ValueError, match="digest"):
        OntologyReleaseRef(digest="sha256:not-a-digest")


def test_release_rejects_duplicate_declaration_identity() -> None:
    with pytest.raises(ValueError, match="identities MUST be unique"):
        build_ontology_release(action_types=(_action("ops.alpha"), _action("ops.alpha")))


def test_release_pins_function_identity_and_artifact_changes() -> None:
    function = OntologyFunctionType(
        name="predict.capacity",
        version="1.0.0",
        kind=OntologyFunctionKind.DERIVE,
        artifact_digest="sha256:" + "a" * 64,
        publisher="fdai",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )
    release = build_ontology_release(function_types=(function,))
    changed = build_ontology_release(
        function_types=(function.model_copy(update={"artifact_digest": "sha256:" + "b" * 64}),)
    )

    reference = release.type_ref(OntologyDeclarationKind.FUNCTION, function.name)

    assert reference.version == function.version
    assert reference.catalog_digest == release.digest
    assert changed.digest != release.digest
