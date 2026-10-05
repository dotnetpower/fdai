"""Structural checks for authored synthetic data, not measured retrieval quality."""

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from fdai.core.ontology_platform import build_query_manifest
from fdai.core.ontology_platform.interfaces import compile_interfaces
from fdai.core.ontology_platform.object_sets import ObjectSetService
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.delivery.catalog_search.generation import build_ontology_semantic_generation
from fdai.delivery.catalog_search.ontology_evaluation import (
    OntologyRetrievalEvaluationCase,
    prepare_ontology_retrieval_evaluation,
)
from fdai.delivery.catalog_search.ontology_evaluation_campaign import (
    prepare_ontology_retrieval_campaign,
)
from fdai.delivery.catalog_search.ontology_evaluation_execution import (
    OntologyRetrievalExecutionAbortedError,
    OntologyRetrievalExecutionBudget,
    OntologyRetrievalExecutionReport,
    execute_ontology_retrieval_campaign,
)
from fdai.delivery.catalog_search.ranking import CatalogRankingPolicy
from fdai.rule_catalog.schema.object_type import load_object_type_from_mapping
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule_semantic_evaluation_policy import (
    load_retrieval_evaluation_policy_from_mapping,
)
from fdai.rule_catalog.schema.rule_semantic_retrieval import query_digest
from fdai.shared.contracts.models import CeilingRole, IncidentState, Severity
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyObjectRecord, validate_object_record
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_ROOT = Path(__file__).resolve().parents[5]
_ASSETS = _ROOT / "eval/ontology-retrieval"
_INSTANCE_HOLDOUT_V2_COHORT_COUNTS = {
    "en-positive": 16,
    "ko-positive": 16,
    "en-ambiguous": 8,
    "ko-ambiguous": 8,
    "en-negative": 4,
    "ko-negative": 4,
    "en-adversarial": 4,
    "ko-adversarial": 4,
}


def _load_asset(name: str) -> dict:
    return json.loads((_ASSETS / name).read_text())


def _normalized_query(text: str) -> str:
    return " ".join(text.casefold().split())


def _corpus_document_ids() -> set[str]:
    corpus = _load_asset("instance-corpus.v1.json")
    return {f"object:{item['object_type']}:{item['id']}" for item in corpus["objects"]}


def test_instance_holdout_v2_has_expected_shape_and_cohorts() -> None:
    holdout = _load_asset("instance-holdout.v2.json")
    cases = holdout["cases"]

    assert holdout["schema_version"] == "1.0.0"
    assert holdout["origin"] == "independently_authored_synthetic_holdout"
    assert holdout["independently_reviewed"] is True
    assert holdout["production_qualification"] is False
    assert holdout["supersedes"] == "instance-holdout.v1.json"
    assert len(cases) == 64
    assert Counter(item["cohort"] for item in cases) == _INSTANCE_HOLDOUT_V2_COHORT_COUNTS
    assert len({item["case_id"] for item in cases}) == 64
    assert all(item["case_id"].startswith(("hold2-en-", "hold2-ko-")) for item in cases)


def test_instance_holdout_v2_references_only_corpus_ids() -> None:
    cases = _load_asset("instance-holdout.v2.json")["cases"]
    object_ids = _corpus_document_ids()

    for case in cases:
        expected_ids = case["expected_document_ids"]
        assert set(expected_ids) <= object_ids
        if case["cohort"].endswith("-positive"):
            assert expected_ids
        if case["cohort"].endswith(("-negative", "-adversarial")):
            assert expected_ids == []


def test_instance_holdout_v2_ambiguous_cases_split_match_and_no_match() -> None:
    cases = _load_asset("instance-holdout.v2.json")["cases"]

    for language in ("en", "ko"):
        ambiguous = [item for item in cases if item["cohort"] == f"{language}-ambiguous"]
        assert sum(bool(item["expected_document_ids"]) for item in ambiguous) == 4
        assert sum(not item["expected_document_ids"] for item in ambiguous) == 4


def test_instance_holdout_v2_queries_are_exact_normalized_disjoint() -> None:
    holdout_v2_queries = {
        _normalized_query(item["query"])
        for item in _load_asset("instance-holdout.v2.json")["cases"]
    }
    prior_queries = {
        _normalized_query(item["query"])
        for asset_name in (
            "instance-calibration.v1.json",
            "instance-calibration.v2.json",
            "instance-holdout.v1.json",
        )
        for item in _load_asset(asset_name)["cases"]
    }

    assert len(holdout_v2_queries) == 64
    assert holdout_v2_queries.isdisjoint(prior_queries)


def test_instance_holdout_v2_passes_real_preflight_against_calibration_v2() -> None:
    corpus = _load_asset("instance-corpus.v1.json")
    calibration = _load_asset("instance-calibration.v2.json")
    holdout = _load_asset("instance-holdout.v2.json")
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
    resource_registry = load_resource_type_registry_from_mapping(
        yaml.safe_load((_ROOT / "rule-catalog/vocabulary/resource-types.yaml").read_text())
    )
    objects = tuple(OntologyObjectRecord(**item) for item in corpus["objects"])
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
        embedding_dimension=24,
        runtime_objects=objects,
        resource_type_query_terms={item.id: item.query_terms for item in resource_registry},
    )
    cases = tuple(
        OntologyRetrievalEvaluationCase(
            case_id=item["case_id"],
            query=item["query"],
            cohort=item["cohort"],
            expected_document_ids=tuple(item["expected_document_ids"]),
        )
        for item in holdout["cases"]
    )

    plan = prepare_ontology_retrieval_evaluation(
        build=build,
        manifest=manifest,
        cases=cases,
        calibration_queries=tuple(item["query"] for item in calibration["cases"]),
        ranking_policy=CatalogRankingPolicy(**calibration["candidate_ranking_policy"]),
        evaluation_policy=load_retrieval_evaluation_policy_from_mapping(
            calibration["evaluation_policy"]
        ),
        required_object_types=names,
    )

    assert plan.query_count == 64
    assert plan.embedding_call_upper_bound == 92


@pytest.mark.parametrize("term_binding", ["matching", "missing", "changed"])
async def test_authored_dataset_uses_real_declarations_and_separate_frozen_questions(
    term_binding: str,
) -> None:
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
    resource_registry = load_resource_type_registry_from_mapping(
        yaml.safe_load((_ROOT / "rule-catalog/vocabulary/resource-types.yaml").read_text())
    )
    resource_types = resource_registry.ids()
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
        embedding_dimension=24,
        runtime_objects=objects,
        resource_type_query_terms={item.id: item.query_terms for item in resource_registry},
    )
    resource_f = next(
        item for item in build.documents if item.rule_id == "object:Resource:example-resource-f"
    )
    assert "가상 머신" in resource_f.text
    assert "애플리케이션 릴리스 빌드 가상 머신" in resource_f.text
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
    plan = prepare_ontology_retrieval_campaign(
        build=build,
        manifest=manifest,
        holdout_cases=heldout_cases,
        calibration_cases=calibration_cases,
        ranking_policy=CatalogRankingPolicy(**calibration["candidate_ranking_policy"]),
        evaluation_policy=load_retrieval_evaluation_policy_from_mapping(
            calibration["evaluation_policy"]
        ),
        required_object_types=names,
    )
    assert len(build.documents) == 28
    assert plan.embedding_call_upper_bound == 116
    assert 116 <= calibration["limits"]["embedding_calls"] == 128
    assert calibration["limits"]["total_seconds"] == 600
    assert calibration["limits"]["embedding_call_seconds"] == 5
    assert plan.production_qualification is False

    expanded = json.loads((_ASSETS / "instance-calibration.v2.json").read_text())
    assert expanded["independently_reviewed"] is False
    assert expanded["production_qualification"] is False
    assert expanded["candidate_ranking_policy"] == calibration["candidate_ranking_policy"]
    assert expanded["evaluation_policy"] == calibration["evaluation_policy"]
    expanded_cases = tuple(
        OntologyRetrievalEvaluationCase(
            case_id=item["case_id"],
            query=item["query"],
            cohort=item["cohort"],
            expected_document_ids=tuple(item["expected_document_ids"]),
        )
        for item in expanded["cases"]
    )
    assert len(expanded_cases) == 64
    assert set(calibration_cases) <= set(expanded_cases)
    assert not {query_digest(item.query) for item in expanded_cases}.intersection(
        query_digest(item.query) for item in heldout_cases
    )
    expanded_plan = prepare_ontology_retrieval_evaluation(
        build=build,
        manifest=manifest,
        cases=expanded_cases,
        calibration_queries=(),
        ranking_policy=CatalogRankingPolicy(**expanded["candidate_ranking_policy"]),
        evaluation_policy=load_retrieval_evaluation_policy_from_mapping(
            expanded["evaluation_policy"]
        ),
        required_object_types=names,
    )
    assert expanded_plan.query_count == 64
    assert expanded_plan.embedding_call_upper_bound == 92
    assert expanded_plan.production_qualification is False

    release = build_ontology_release(object_types=declarations)
    store = InMemoryOntologyInstanceStore(
        object_types=declarations, link_types=(), source_generation="asset-execution"
    )
    for record in objects:
        await store.upsert_object(record)
    gateway = SecuredObjectSetQueryGateway(
        service=ObjectSetService(
            store=store,
            interfaces=compile_interfaces(
                interfaces=(), implementations=(), object_types=declarations, release=release
            ),
            object_type_names=frozenset(names),
        ),
        object_types=by_name,
        ontology_release=release,
        evaluation_cutoff=lambda: datetime.now(UTC),
        max_as_of_skew=timedelta(seconds=5),
    )
    document_ids = sorted(object_ids)
    case_by_query = {
        case.query: case for case in (*calibration_cases, *heldout_cases, *expanded_cases)
    }

    class Embedder:
        embedding_space_id = build.metadata.embedding_space_id
        embedding_model_version = build.metadata.embedding_model_version
        dim = 24
        calls = 0

        async def embed(self, text: str) -> tuple[float, ...]:
            self.calls += 1
            if text.startswith("{"):
                expected = next(item for item in build.documents if item.text == text)
                if expected.rule_id not in object_ids:
                    return (1.0,) * 24
                selected = (expected.rule_id,)
            else:
                selected = case_by_query[text].expected_document_ids
            return tuple(
                1.0 if identifier in selected else 0.0 if selected else -1.0
                for identifier in document_ids
            )

    embedder = Embedder()
    terms = {item.id: item.query_terms for item in resource_registry}
    if term_binding == "missing":
        terms = {}
    elif term_binding == "changed":
        terms["compute.vm"] = ("changed resource vocabulary",)

    async def execute(*, calibration_only: bool = False) -> OntologyRetrievalExecutionReport:
        selected_calibration = expanded_cases if calibration_only else calibration_cases
        selected_holdout = () if calibration_only else heldout_cases
        selected_plan = prepare_ontology_retrieval_campaign(
            build=build,
            manifest=manifest,
            calibration_cases=selected_calibration,
            holdout_cases=selected_holdout,
            ranking_policy=CatalogRankingPolicy(**calibration["candidate_ranking_policy"]),
            evaluation_policy=load_retrieval_evaluation_policy_from_mapping(
                calibration["evaluation_policy"]
            ),
            required_object_types=names,
            calibration_only=calibration_only,
        )
        return await execute_ontology_retrieval_campaign(
            build=build,
            manifest=manifest,
            expected_binding_digest=selected_plan.binding_digest,
            calibration_cases=selected_calibration,
            holdout_cases=selected_holdout,
            ranking_policy=CatalogRankingPolicy(**calibration["candidate_ranking_policy"]),
            evaluation_policy=load_retrieval_evaluation_policy_from_mapping(
                calibration["evaluation_policy"]
            ),
            required_object_types=names,
            state=InMemoryStateStore(),
            gateway=gateway,
            source_generation="asset-execution",
            embedder=embedder,
            clock=lambda: datetime.now(UTC),
            budget=OntologyRetrievalExecutionBudget(128, 600, 5),
            resource_type_query_terms=terms,
            calibration_only=calibration_only,
        )

    if term_binding != "matching":
        with pytest.raises(OntologyRetrievalExecutionAbortedError) as failure:
            await execute()
        assert failure.value.stage == "preparation"
        assert failure.value.embedding_calls == embedder.calls == 0
    else:
        result = await execute()
        assert result.campaign.passed
        assert result.embedding_calls == embedder.calls == 116
        assert result.production_qualification is False
        embedder.calls = 0
        calibration_result = await execute(calibration_only=True)
        assert calibration_result.calibration_only is True
        # Two adversarial cases cite canonical ids of missing objects; the exact-identity
        # path answers them with no match before any query embedding (28 + 62).
        assert calibration_result.embedding_calls == embedder.calls == 90
        assert calibration_result.campaign.calibration.passed
        assert len(calibration_result.campaign.calibration.measurements) == 64
        assert calibration_result.campaign.holdout is None
        assert calibration_result.campaign.passed is False
        assert calibration_result.production_qualification is False
