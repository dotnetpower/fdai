"""N/N-1 compatibility tests for ontology-aware generation activation."""

from __future__ import annotations

import pytest

from fdai.shared.contracts.models import (
    OntologyDeclarationKind,
    OntologyInterfaceType,
    OntologyObjectType,
)
from fdai.shared.ontology.compatibility import (
    OntologyGenerationCompatibilityError,
    require_ontology_generation_compatibility,
)
from fdai.shared.ontology.release import build_ontology_release


def _object_type(version: str) -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name="Workload",
        version=version,
        key="id",
        properties={},
    )


def _schema(*, include_replicas: bool) -> dict[str, object]:
    properties: dict[str, object] = {"id": {"type": "string"}}
    if include_replicas:
        properties["replicas"] = {"type": "integer"}
    return {
        "type": "object",
        "properties": properties,
        "required": ["id"],
    }


def _interface(version: str = "1.0.0") -> OntologyInterfaceType:
    return OntologyInterfaceType(name="Operable", version=version)


def test_breaking_n_minus_one_schema_fails_before_activation() -> None:
    identity = (OntologyDeclarationKind.OBJECT, "Workload")
    previous = build_ontology_release(object_types=(_object_type("1.0.0"),))
    candidate = build_ontology_release(object_types=(_object_type("2.0.0"),))

    with pytest.raises(
        OntologyGenerationCompatibilityError,
        match="breaking schema change.*replicas.*field removed",
    ):
        require_ontology_generation_compatibility(
            previous_release=previous,
            candidate_release=candidate,
            previous_schemas={identity: _schema(include_replicas=True)},
            candidate_schemas={identity: _schema(include_replicas=False)},
            generation_release_digest=candidate.digest,
        )


def test_additive_n_minus_one_schema_preserves_generation_activation() -> None:
    identity = (OntologyDeclarationKind.OBJECT, "Workload")
    previous = build_ontology_release(object_types=(_object_type("1.0.0"),))
    candidate = build_ontology_release(object_types=(_object_type("1.1.0"),))

    receipt = require_ontology_generation_compatibility(
        previous_release=previous,
        candidate_release=candidate,
        previous_schemas={identity: _schema(include_replicas=False)},
        candidate_schemas={identity: _schema(include_replicas=True)},
        generation_release_digest=candidate.digest,
    )

    assert receipt.previous_release_digest == previous.digest
    assert receipt.candidate_release_digest == candidate.digest
    assert receipt.checked_declarations == ("object:Workload",)
    assert receipt.added_declarations == ()


def test_generation_release_mismatch_fails_before_schema_evaluation() -> None:
    previous = build_ontology_release(object_types=(_object_type("1.0.0"),))
    candidate = build_ontology_release(object_types=(_object_type("1.1.0"),))

    with pytest.raises(
        OntologyGenerationCompatibilityError,
        match="release digest does not match",
    ):
        require_ontology_generation_compatibility(
            previous_release=previous,
            candidate_release=candidate,
            previous_schemas={},
            candidate_schemas={},
            generation_release_digest=previous.digest,
        )


def test_removed_declaration_fails_closed() -> None:
    identity = (OntologyDeclarationKind.OBJECT, "Workload")
    previous = build_ontology_release(object_types=(_object_type("1.0.0"),))
    candidate = build_ontology_release()

    with pytest.raises(
        OntologyGenerationCompatibilityError,
        match="removes declaration object:Workload",
    ):
        require_ontology_generation_compatibility(
            previous_release=previous,
            candidate_release=candidate,
            previous_schemas={identity: _schema(include_replicas=False)},
            candidate_schemas={},
            generation_release_digest=candidate.digest,
        )


def test_missing_release_schema_evidence_fails_closed() -> None:
    previous = build_ontology_release(object_types=(_object_type("1.0.0"),))
    candidate = build_ontology_release(object_types=(_object_type("1.1.0"),))

    with pytest.raises(
        OntologyGenerationCompatibilityError,
        match="previous ontology release schema is missing object:Workload",
    ):
        require_ontology_generation_compatibility(
            previous_release=previous,
            candidate_release=candidate,
            previous_schemas={},
            candidate_schemas={},
            generation_release_digest=candidate.digest,
        )


def test_interface_addition_is_reported_as_additive() -> None:
    identity = (OntologyDeclarationKind.INTERFACE, "Operable")
    previous = build_ontology_release()
    candidate = build_ontology_release(interface_types=(_interface(),))

    receipt = require_ontology_generation_compatibility(
        previous_release=previous,
        candidate_release=candidate,
        previous_schemas={},
        candidate_schemas={identity: _schema(include_replicas=False)},
        generation_release_digest=candidate.digest,
    )

    assert receipt.checked_declarations == ()
    assert receipt.added_declarations == ("interface:Operable",)


def test_interface_removal_fails_closed() -> None:
    identity = (OntologyDeclarationKind.INTERFACE, "Operable")
    previous = build_ontology_release(interface_types=(_interface(),))
    candidate = build_ontology_release()

    with pytest.raises(
        OntologyGenerationCompatibilityError,
        match="removes declaration interface:Operable",
    ):
        require_ontology_generation_compatibility(
            previous_release=previous,
            candidate_release=candidate,
            previous_schemas={identity: _schema(include_replicas=False)},
            candidate_schemas={},
            generation_release_digest=candidate.digest,
        )
