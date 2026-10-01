"""Structural checks for authored synthetic data, not measured retrieval quality."""

import json
from collections import Counter
from pathlib import Path

import yaml
from fdai.core.ontology_platform import build_query_manifest
from fdai.delivery.catalog_search.generation import build_ontology_semantic_generation
from fdai.delivery.catalog_search.ontology_evaluation import (
    OntologyRetrievalEvaluationCase,
    prepare_ontology_retrieval_evaluation,
)
from fdai.delivery.catalog_search.ranking import CatalogRankingPolicy
from fdai.rule_catalog.schema.object_type import load_object_type_from_mapping
from fdai.rule_catalog.schema.rule_semantic_evaluation_policy import (
    load_retrieval_evaluation_policy_from_mapping,
)
from fdai.rule_catalog.schema.rule_semantic_retrieval import query_digest
from fdai.shared.contracts.models import CeilingRole, IncidentState, Severity
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyObjectRecord, validate_object_record

_ROOT = Path(__file__).resolve().parents[5]
_ASSETS = _ROOT / "eval/ontology-retrieval"


def test_authored_dataset_uses_real_declarations_and_separate_frozen_questions() -> None:
    corpus = json.loads((_ASSETS / "instance-corpus.v1.json").read_text())
    calibration = json.loads((_ASSETS / "instance-calibration.v1.json").read_text())
    holdout = json.loads((_ASSETS / "instance-holdout.v1.json").read_text())
    for data in (corpus, calibration, holdout):
        assert data["schema_version"] == "1.0.0"
        assert data["independently_reviewed"] is False
        assert data["production_qualification"] is False
    names = tuple(corpus["required_object_types"])
    registry = PackageResourceSchemaRegistry()
    declarations = tuple(
        load_object_type_from_mapping(
            yaml.safe_load(
                (_ROOT / f"rule-catalog/vocabulary/object-types/{name}.yaml").read_text()
            ),
            schema_registry=registry,
        )
        for name in names
    )
    by_name = {item.name: item for item in declarations}
    resource_types = {
        item["id"]
        for item in yaml.safe_load(
            (_ROOT / "rule-catalog/vocabulary/resource-types.yaml").read_text()
        )["types"]
    }
    objects = tuple(OntologyObjectRecord(**item) for item in corpus["objects"])
    assert len(objects) == 24
    assert Counter(item.object_type for item in objects) == dict.fromkeys(names, 6)
    for record in objects:
        validate_object_record(record, by_name)
        if record.object_type == "Resource":
            assert record.properties["type"] in resource_types
        if record.object_type == "Incident":
            IncidentState(record.properties["status"])
            Severity(record.properties["severity"])
    manifest = build_query_manifest(
        release=build_ontology_release(object_types=declarations),
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest="sha256:" + "a" * 64,
        object_types=declarations,
    )
    build = build_ontology_semantic_generation(
        manifest=manifest,
        embedding_space_id="qualification-space-placeholder",
        embedding_model_version="unbound-model-version",
        embedding_dimension=1,
        runtime_objects=objects,
    )
    calibration_cases, heldout_cases = (
        tuple(
            OntologyRetrievalEvaluationCase(
                case_id=item["case_id"],
                query=item["query"],
                cohort=item["cohort"],
                expected_document_ids=tuple(item["expected_document_ids"]),
            )
            for item in data["cases"]
        )
        for data in (calibration, holdout)
    )
    assert len(calibration_cases) == 24
    assert len(heldout_cases) == 64
    assert len({item.case_id for item in (*calibration_cases, *heldout_cases)}) == 88
    assert len({query_digest(item.query) for item in (*calibration_cases, *heldout_cases)}) == 88
    object_ids = {
        item.rule_id for item in build.documents if item.document_kind == "ontology_object"
    }
    for case in (*calibration_cases, *heldout_cases):
        assert set(case.expected_document_ids) <= object_ids
    plan = prepare_ontology_retrieval_evaluation(
        build=build,
        manifest=manifest,
        cases=heldout_cases,
        calibration_queries=tuple(item.query for item in calibration_cases),
        ranking_policy=CatalogRankingPolicy(**calibration["candidate_ranking_policy"]),
        evaluation_policy=load_retrieval_evaluation_policy_from_mapping(
            calibration["evaluation_policy"]
        ),
        required_object_types=names,
    )
    assert plan.document_count == 28
    assert plan.embedding_call_upper_bound + len(calibration_cases) == 116
    assert 116 <= calibration["limits"]["embedding_calls"] == 128
    assert calibration["limits"]["total_seconds"] == 600
    assert calibration["limits"]["embedding_call_seconds"] == 5
    assert plan.production_qualification is False
