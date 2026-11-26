"""Nested-value typed conditions through the real secured ObjectSet gateway."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from fdai.core.ontology_platform import build_query_manifest
from fdai.core.ontology_platform.interfaces import compile_interfaces
from fdai.core.ontology_platform.object_sets import ObjectSetService
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.delivery.azure.llm import semantic_planning_config as planning_config
from fdai.delivery.azure.llm.semantic_planning_config import strict_candidate_proposal_schema
from fdai.delivery.azure.llm.semantic_planning_response import (
    normalize_candidate_proposal_payload,
)
from fdai.delivery.catalog_search.ontology_candidate_proposal import (
    OntologyCandidateProposal,
    candidate_nested_property_catalog,
)
from fdai.delivery.catalog_search.ontology_candidate_selection import (
    OntologyCandidateClause,
    OntologyCandidateSelection,
    OntologyNestedPredicate,
    resolve_candidate_selection,
)
from fdai.delivery.catalog_search.ontology_snapshot_store import OntologyGenerationSnapshotStore
from fdai.rule_catalog.schema.object_type import load_object_type_from_mapping
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from pydantic import ValidationError

_ROOT = Path(__file__).resolve().parents[5]
_ASSETS = _ROOT / "eval/ontology-retrieval"
_NOW = datetime(2026, 10, 8, tzinfo=UTC)
_PROPERTIES = {"properties": {"purpose": "Persist purchase order transactions", "tier": 3}}


@pytest.mark.parametrize(
    ("predicate", "expected"),
    [
        ({"key": "purpose", "operator": "contains", "equals": "purchase order"}, True),
        ({"key": "purpose", "operator": "contains", "equals": "payroll"}, False),
        ({"key": "tier", "operator": "at_least", "equals": 3}, True),
        ({"key": "tier", "operator": "equals", "equals": "3"}, False),
        ({"key": "purpose", "operator": "exists"}, True),
        ({"key": "aliases", "operator": "exists"}, False),
        ({"key": "aliases", "operator": "absent"}, True),
    ],
)
def test_nested_predicate_applies_object_set_operator_semantics(
    predicate: dict[str, object], expected: bool
) -> None:
    nested = OntologyNestedPredicate.model_validate({"property": "properties", **predicate})
    assert nested.matches(_PROPERTIES) is expected


def test_nested_predicate_requires_an_object_valued_parent() -> None:
    for properties in ({}, {"properties": "not-an-object"}):
        for operator in ("absent", "exists"):
            assert not OntologyNestedPredicate(
                property="properties", key="purpose", operator=operator
            ).matches(properties)


@pytest.mark.parametrize(
    "invalid",
    [
        {"key": "purpose", "operator": "contains"},
        {"key": "purpose", "operator": "in", "equals": "x"},
        {"key": "purpose", "operator": "exists", "equals": "x"},
        {"key": "", "operator": "exists"},
    ],
)
def test_nested_predicate_rejects_invalid_operands(invalid: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        OntologyNestedPredicate.model_validate({"property": "properties", **invalid})


def test_clause_without_nested_conditions_keeps_its_canonical_form() -> None:
    plain = OntologyCandidateClause(object_type="Resource", object_ids=("example-resource-a",))
    nested = OntologyCandidateClause(
        object_type="Resource",
        nested_predicates=(
            OntologyNestedPredicate(property="properties", key="purpose", operator="exists"),
        ),
    )

    assert "nested_predicates" not in plain.model_dump(mode="json")
    assert nested.model_dump(mode="json")["nested_predicates"] == [
        {"property": "properties", "key": "purpose", "operator": "exists"}
    ]
    assert OntologyCandidateClause.model_validate(nested.model_dump(mode="json")) == nested
    for predicate in (
        OntologyNestedPredicate(property="p", key="k", operator="contains", equals="x"),
        OntologyNestedPredicate(property="p", key="k", operator="in", values=("x", "y")),
    ):
        dumped = predicate.model_dump(mode="json")
        assert OntologyNestedPredicate.model_validate(dumped).model_dump(mode="json") == dumped


def test_clause_bounds_match_the_strict_schema() -> None:
    nested = OntologyNestedPredicate(property="properties", key="purpose", operator="exists")
    top = {"property": "id", "operator": "exists"}
    assert OntologyCandidateClause(
        object_type="Resource", predicates=(top,) * 16, nested_predicates=(nested,) * 16
    )
    with pytest.raises(ValidationError):
        OntologyCandidateClause(object_type="Resource", nested_predicates=(nested,) * 17)


def test_provider_null_operands_normalize_to_the_typed_contract() -> None:
    payload = normalize_candidate_proposal_payload(
        {
            "status": "select",
            "reason": "conditions_proposed",
            "clauses": [
                {
                    "object_type": "Resource",
                    "predicates": [],
                    "nested_predicates": [
                        {
                            "property": "properties",
                            "key": "purpose",
                            "operator": "exists",
                            "equals": None,
                            "values": None,
                        },
                        {
                            "property": "properties",
                            "key": "purpose",
                            "operator": "contains",
                            "equals": "order",
                            "values": None,
                        },
                    ],
                    "object_ids": None,
                    "quote": "q",
                }
            ],
        }
    )
    proposal = OntologyCandidateProposal.model_validate(payload)
    assert [item.operator.value for item in proposal.clauses[0].nested_predicates] == [
        "exists",
        "contains",
    ]


async def test_schema_above_the_structured_enum_bound_holds_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, _gateway, _staged, build, _terms = await _prepared()
    keys = tuple(f"key-{index:03d}" for index in range(600))
    monkeypatch.setattr(
        planning_config,
        "candidate_nested_property_catalog",
        lambda _manifest, _build: (
            {"object_type": "Resource", "property": "properties", "keys": keys},
        ),
    )
    with pytest.raises(ValueError, match="enum bound"):
        strict_candidate_proposal_schema(manifest=manifest, build=build)


async def _prepared() -> tuple[object, ...]:
    corpus = json.loads((_ASSETS / "instance-corpus.v1.json").read_text())
    names = tuple(corpus["required_object_types"])
    declarations = tuple(
        load_object_type_from_mapping(
            yaml.safe_load(
                (_ROOT / f"rule-catalog/vocabulary/object-types/{name}.yaml").read_text()
            ),
            schema_registry=PackageResourceSchemaRegistry(),
        )
        for name in names
    )
    terms = {
        item.id: item.query_terms
        for item in load_resource_type_registry_from_mapping(
            yaml.safe_load((_ROOT / "rule-catalog/vocabulary/resource-types.yaml").read_text())
        )
    }
    release = build_ontology_release(object_types=declarations)
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest="sha256:" + "a" * 64,
        object_types=declarations,
    )
    store = InMemoryOntologyInstanceStore(
        object_types=declarations, link_types=(), source_generation="nested-source"
    )
    for item in corpus["objects"]:
        await store.upsert_object(OntologyObjectRecord(**item))
    gateway = SecuredObjectSetQueryGateway(
        service=ObjectSetService(
            store=store,
            interfaces=compile_interfaces(
                interfaces=(), implementations=(), object_types=declarations, release=release
            ),
            object_type_names=frozenset(names),
        ),
        object_types={item.name: item for item in declarations},
        ontology_release=release,
        evaluation_cutoff=lambda: _NOW,
        max_as_of_skew=timedelta(seconds=5),
    )
    snapshots = OntologyGenerationSnapshotStore(
        InMemoryStateStore(), resource_type_query_terms=terms
    )
    staged = await snapshots.stage_manifest_from_gateway(
        gateway=gateway,
        manifest=manifest,
        as_of=_NOW,
        expected_source_generation="nested-source",
        embedding_space_id="nested-space",
        embedding_model_version="none",
        embedding_dimension=8,
    )
    build = await snapshots.read(
        staged.snapshot_digest,
        manifest=manifest,
        source_generation=staged.source_generation,
        source_projection_digest=staged.source_projection_digest,
    )
    assert build is not None
    return manifest, gateway, staged, build, terms


async def _select(clauses: tuple[OntologyCandidateClause, ...]) -> list[str]:
    manifest, gateway, staged, build, terms = await _prepared()
    query = "nested-condition fixture"
    selected = await resolve_candidate_selection(
        selection=OntologyCandidateSelection.bind(
            query=query, manifest=manifest, staged=staged, clauses=clauses
        ),
        query=query,
        staged=staged,
        manifest=manifest,
        documents=build.documents,
        gateway=gateway,
        as_of=_NOW,
        deadline=float("inf"),
        resource_type_query_terms=terms,
    )
    return [document.rule_id for document in selected.documents]


def _nested(key: str, operator: str, equals: object) -> OntologyNestedPredicate:
    return OntologyNestedPredicate(property="properties", key=key, operator=operator, equals=equals)


@pytest.mark.parametrize(
    ("case_id", "asset", "clause"),
    [
        (
            "cal-v3-en-p09",
            "instance-calibration.v3.json",
            OntologyCandidateClause(
                object_type="Resource",
                nested_predicates=(
                    _nested("public_access", "equals", "enabled"),
                    _nested("purpose", "contains", "product images"),
                ),
            ),
        ),
        (
            "cal-v3-ko-p11",
            "instance-calibration.v3.json",
            OntologyCandidateClause(
                object_type="Resource",
                predicates=(
                    {"property": "type", "operator": "equals", "equals": "kubernetes-cluster"},
                ),
                nested_predicates=(_nested("node_pool_role", "equals", "batch"),),
            ),
        ),
        (
            "cal-v2-en-n01",
            "instance-calibration.v2.json",
            OntologyCandidateClause(
                object_type="Resource",
                predicates=({"property": "type", "operator": "equals", "equals": "mysql-server"},),
                nested_predicates=(_nested("purpose", "contains", "payroll"),),
            ),
        ),
    ],
)
async def test_nested_conditions_reproduce_calibration_labels_through_the_gateway(
    case_id: str, asset: str, clause: OntologyCandidateClause
) -> None:
    calibration = json.loads((_ASSETS / asset).read_text())
    case = next(item for item in calibration["cases"] if item["case_id"] == case_id)

    assert await _select((clause,)) == sorted(case["expected_document_ids"])


async def test_unreadable_or_undeclared_parent_property_is_refused_by_the_gateway() -> None:
    clause = OntologyCandidateClause(
        object_type="Resource",
        nested_predicates=(
            OntologyNestedPredicate(property="undeclared", key="purpose", operator="exists"),
        ),
    )
    with pytest.raises((PermissionError, ValueError)):
        await _select((clause,))


async def test_strict_schema_enumerates_observed_nested_keys_per_type() -> None:
    manifest, _gateway, _staged, build, _terms = await _prepared()
    catalog = candidate_nested_property_catalog(manifest, build)
    schema = strict_candidate_proposal_schema(manifest=manifest, build=build)
    clauses = {
        variant["properties"]["object_type"]["enum"][0]: variant
        for variant in schema["properties"]["clauses"]["items"]["anyOf"]
    }

    assert [(item["object_type"], item["property"]) for item in catalog] == [
        ("Resource", "properties")
    ]
    resource_nested = clauses["Resource"]["properties"]["nested_predicates"]["items"]["anyOf"]
    assert len(resource_nested) == 1
    assert set(resource_nested[0]["properties"]["key"]["enum"]) == set(catalog[0]["keys"])
    assert {"purpose", "aliases", "node_pool_role"} <= set(catalog[0]["keys"])
    assert clauses["Incident"]["properties"]["nested_predicates"]["maxItems"] == 0
