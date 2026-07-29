"""Canonical ontology declaration provenance tests."""

from __future__ import annotations

from fdai.rule_catalog.schema.ontology_provenance import (
    ontology_content_hash,
    ontology_provenance_error,
)
from fdai.shared.contracts.models import OntologyObjectType


def _declaration() -> OntologyObjectType:
    raw = {
        "schema_version": "1.0.0",
        "name": "ExampleType",
        "version": "1.0.0",
        "key": "id",
        "properties": {"id": {"type": "string", "required": True}},
        "description": "Example declaration.",
    }
    baseline = OntologyObjectType.model_validate(raw)
    raw["provenance"] = {
        "source_url": "https://example.com/fdai/ontology",
        "resolved_ref": "object-type:ExampleType@1.0.0",
        "content_hash": ontology_content_hash(baseline),
        "license": "MIT",
        "retrieved_at": "2026-07-29T00:00:00Z",
    }
    return OntologyObjectType.model_validate(raw)


def test_matching_provenance_hash_passes() -> None:
    declaration = _declaration()
    assert ontology_provenance_error(declaration) is None


def test_missing_provenance_fails() -> None:
    declaration = _declaration().model_copy(update={"provenance": None})
    assert ontology_provenance_error(declaration) == "catalog declaration MUST include provenance"


def test_stale_provenance_hash_fails_after_declaration_change() -> None:
    declaration = _declaration().model_copy(update={"description": "Changed declaration."})
    error = ontology_provenance_error(declaration)
    assert error is not None
    assert "content_hash mismatch" in error
    assert declaration.provenance is not None
    assert declaration.provenance.content_hash != ontology_content_hash(declaration)
