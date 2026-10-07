"""The candidate-selection prompt states the evaluator's exact predicate semantics."""

import json
from pathlib import Path

import pytest
import yaml
from fdai.core.ontology_platform import build_query_manifest
from fdai.core.ontology_platform.models import ObjectPredicate
from fdai.core.ontology_platform.object_sets import object_matches_predicates
from fdai.core.prompts import PromptAssembler
from fdai.core.prompts.registry import FileSystemPromptRegistry
from fdai.delivery.catalog_search.ontology_candidate_proposal import (
    candidate_predicate_property_catalog,
)
from fdai.rule_catalog.schema.object_type import load_object_type_from_mapping
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release

_ROOT = Path(__file__).resolve().parents[5]
_ASSETS = _ROOT / "eval/ontology-retrieval"
_PROPERTIES = {
    "name": "Example order database",
    "tags": ["primary", "orders"],
    "properties": {"aliases": ["구매 주문 MySQL 서버"], "tier": "gold"},
}


@pytest.mark.parametrize(
    ("predicate", "expected"),
    [
        ({"property": "name", "operator": "contains", "equals": "order"}, True),
        ({"property": "tags", "operator": "contains", "equals": "orders"}, True),
        ({"property": "tags", "operator": "contains", "equals": "order"}, False),
        ({"property": "properties", "operator": "contains", "equals": "aliases"}, True),
        ({"property": "properties", "operator": "contains", "equals": "gold"}, False),
        ({"property": "properties", "operator": "exists"}, True),
        ({"property": "aliases", "operator": "exists"}, False),
        ({"property": "aliases", "operator": "absent"}, True),
    ],
)
def test_predicate_semantics_match_the_prompt_contract(
    predicate: dict[str, object], expected: bool
) -> None:
    assert (
        object_matches_predicates(_PROPERTIES, (ObjectPredicate.model_validate(predicate),))
        is expected
    )


def test_diagnostic_prompt_states_each_contains_and_presence_meaning() -> None:
    registry = FileSystemPromptRegistry(_ROOT / "rule-catalog")
    selection = registry.resolve(
        "semantic.query.plan", profile_id="diagnostic.ontology-candidate-selection"
    )
    text = " ".join(PromptAssembler(selection).complete.system_text.split())

    for statement in (
        "exists and absent test whether that property is present.",
        "contains matches a substring of a text value, an element equal to the operand in "
        "an array value, or a key equal to the operand in an object value.",
        "A requested entry inside an object-valued property is expressed with contains",
    ):
        assert statement in text


def test_nested_entry_calibration_label_is_expressible_by_one_declared_predicate() -> None:
    corpus = json.loads((_ASSETS / "instance-corpus.v1.json").read_text())
    calibration = json.loads((_ASSETS / "instance-calibration.v3.json").read_text())
    case = next(item for item in calibration["cases"] if item["case_id"] == "cal-v3-ko-a04")
    declarations = tuple(
        load_object_type_from_mapping(
            yaml.safe_load(
                (_ROOT / f"rule-catalog/vocabulary/object-types/{name}.yaml").read_text()
            ),
            schema_registry=PackageResourceSchemaRegistry(),
        )
        for name in corpus["required_object_types"]
    )
    manifest = build_query_manifest(
        release=build_ontology_release(object_types=declarations),
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest="sha256:" + "a" * 64,
        object_types=declarations,
    )
    allowed = {
        str(item["object_type"]): item["properties"]
        for item in candidate_predicate_property_catalog(manifest)
    }
    predicate = ObjectPredicate(property="properties", operator="contains", equals="aliases")

    selected = sorted(
        f"object:{item['object_type']}:{item['id']}"
        for item in corpus["objects"]
        if item["object_type"] == "Resource"
        and object_matches_predicates(item["properties"], (predicate,))
    )

    assert "properties" in allowed["Resource"]
    assert selected == sorted(case["expected_document_ids"])
