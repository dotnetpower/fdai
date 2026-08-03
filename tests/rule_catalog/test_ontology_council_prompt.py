"""Ontology council prompt and response schema catalog tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from fdai.core.prompts import FileSystemPromptRegistry, PromptMode
from fdai.delivery.azure.llm.ontology_council_serialization import (
    ontology_council_vote_schema,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CATALOG_ROOT = _REPO_ROOT / "rule-catalog"
_SCHEMA_PATH = _CATALOG_ROOT / "prompts" / "schema" / "ontology-council-vote.schema.json"
_CAPABILITIES = (
    "t2.ontology.council.alpha",
    "t2.ontology.council.beta",
    "t2.ontology.council.gamma",
)


def _object_vote() -> dict[str, object]:
    return {
        "claim_id": "claim-one",
        "citation_digest": "a" * 64,
        "disposition": "propose",
        "operation": "update",
        "target_kind": "object",
        "target_type": "BusinessService",
        "target_identity": "service:one",
        "authority": "documented_intent",
        "properties": [{"name": "owner_ref", "value": "team:one"}],
        "from_identity": None,
        "to_identity": None,
        "semantics": {
            "numbers": [],
            "units": [],
            "comparators": [],
            "negated": False,
            "effective_from": None,
            "effective_to": None,
        },
    }


def _nonproposal_vote(disposition: str) -> dict[str, object]:
    vote = _object_vote()
    vote.update(
        {
            "disposition": disposition,
            "operation": None,
            "target_kind": None,
            "target_type": None,
            "target_identity": None,
            "authority": None,
            "properties": [],
            "from_identity": None,
            "to_identity": None,
            "semantics": None,
        }
    )
    return vote


def _validator() -> Draft7Validator:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def test_catalog_vote_schema_equals_fresh_python_schema() -> None:
    catalog_schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    first = ontology_council_vote_schema()
    second = ontology_council_vote_schema()

    assert catalog_schema == first
    assert first is not second
    assert first["properties"] is not second["properties"]
    first["required"] = []
    assert second["required"]


def test_prompt_catalog_binds_one_enforced_required_layer_to_all_roles() -> None:
    registry = FileSystemPromptRegistry(_CATALOG_ROOT)

    prompts = tuple(registry.get_base(capability) for capability in _CAPABILITIES)

    assert len(set(prompts)) == 1
    assert prompts[0].id == "t2-ontology-council"
    assert prompts[0].default_mode is PromptMode.ENFORCE
    assert set(prompts[0].applies_to) == set(_CAPABILITIES)
    assert "target_identity must equal from_identity" in prompts[0].body
    assert "Do not echo packet authority" in prompts[0].body
    assert "Use unsupported only when no supplied declaration" in prompts[0].body
    assert "exact source_assertion" in prompts[0].body
    assert "use update, never add" in prompts[0].body
    assert "numbers are sorted unique digit or decimal substrings" in prompts[0].body
    assert "Sort and deduplicate" in prompts[0].body
    assert "digest-verified alternatives" in prompts[0].body
    assert "copy every dispute.agreed_fields value exactly" in prompts[0].body


@pytest.mark.parametrize("kind", ["object", "link", "unsupported", "abstain"])
def test_vote_schema_accepts_supported_shapes(kind: str) -> None:
    vote = _object_vote()
    if kind == "link":
        vote.update(
            {
                "operation": "add",
                "target_kind": "link",
                "target_type": "service_depends_on",
                "target_identity": "link:one-two",
                "properties": [],
                "from_identity": "service:one",
                "to_identity": "service:two",
            }
        )
    elif kind in {"unsupported", "abstain"}:
        vote = _nonproposal_vote(kind)

    _validator().validate(vote)


@pytest.mark.parametrize(
    "defect",
    ["extra", "bad_scalar", "missing", "invalid_target", "invalid_endpoint"],
)
def test_vote_schema_rejects_invalid_shapes(defect: str) -> None:
    vote = copy.deepcopy(_object_vote())
    if defect == "extra":
        vote["explanation"] = "not allowed"
    elif defect == "bad_scalar":
        properties = vote["properties"]
        assert isinstance(properties, list)
        property_entry = properties[0]
        assert isinstance(property_entry, dict)
        property_entry["value"] = {"nested": "not scalar"}
    elif defect == "missing":
        del vote["authority"]
    elif defect == "invalid_target":
        vote["target_kind"] = "relationship"
    else:
        vote["from_identity"] = []

    assert not _validator().is_valid(vote)
