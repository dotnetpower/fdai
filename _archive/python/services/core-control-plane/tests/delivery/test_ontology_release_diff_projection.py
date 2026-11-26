"""Focused retained ontology release diff projection tests."""

from __future__ import annotations

from fdai.delivery.ontology_release_diff_projection import (
    build_ontology_release_diff_projection,
    build_release_diff_registry,
)
from fdai.shared.contracts.models import OntologyObjectType, PropertyDecl, PropertyType
from fdai.shared.ontology.release import build_ontology_release


def _object(name: str, version: str = "1.0.0") -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name=name,
        version=version,
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )


def test_release_diff_classifies_additive_changed_and_removed_declarations() -> None:
    resource_v1 = _object("Resource")
    resource_v2 = _object("Resource", "2.0.0")
    decision = _object("Decision")
    base = build_ontology_release(object_types=(resource_v1, decision))

    additive = build_ontology_release(object_types=(resource_v1, decision, _object("Finding")))
    changed = build_ontology_release(object_types=(resource_v2, decision))
    removed = build_ontology_release(object_types=(resource_v1,))

    additive_diff = build_ontology_release_diff_projection(base=base, candidate=additive)
    changed_diff = build_ontology_release_diff_projection(base=base, candidate=changed)
    removed_diff = build_ontology_release_diff_projection(base=base, candidate=removed)

    assert additive_diff["compatibility_verdict"] == "compatible"
    assert additive_diff["migration_required"] is False
    assert [item["name"] for item in additive_diff["added"]] == ["Finding"]
    assert changed_diff["compatibility_verdict"] == "migration_required"
    assert changed_diff["breaking_change"]["reason"] == (
        "declaration_changed_without_retained_field_schema"
    )
    assert removed_diff["compatibility_verdict"] == "incompatible"
    assert removed_diff["breaking_change"] == {
        "path": "declarations.object.Decision",
        "reason": "declaration_removed",
    }
    assert removed_diff["mutation_authority"] is False


def test_release_diff_registry_is_pairwise_and_deterministic() -> None:
    first = build_ontology_release(object_types=(_object("Resource"),))
    second = build_ontology_release(object_types=(_object("Resource"), _object("Decision")))

    registry = build_release_diff_registry(releases=(first, second))
    repeated = build_release_diff_registry(releases=(first, second))

    assert registry == repeated
    assert len(registry["diffs"]) == 2
    assert registry["mutation_authority"] is False
    assert registry["active_release_digest"] == second.digest
    assert registry["truncated"] is False
    assert str(registry["_revision"]).startswith("sha256:")
