"""Offline preparation is not real-model relevance or production qualification."""

from dataclasses import replace

import pytest
from fdai.core.ontology_platform import QueryManifest, build_query_manifest
from fdai.delivery.catalog_search.generation import build_ontology_semantic_generation
from fdai.delivery.catalog_search.ontology_evaluation import (
    OntologyRetrievalEvaluationCase,
    OntologyRetrievalEvaluationPlan,
    prepare_ontology_retrieval_evaluation,
)
from fdai.delivery.catalog_search.ranking import CatalogRankingPolicy
from fdai.rule_catalog.schema.rule_semantic_evaluation import RetrievalEvaluationPolicy
from fdai.shared.contracts.models import CeilingRole, OntologyObjectType, PropertyDecl, PropertyType
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

_TYPES = ("Incident", "Resource")
_RANKING = CatalogRankingPolicy()
_COHORTS = tuple(
    sorted(
        f"{locale}-{kind}"
        for locale in ("en", "ko")
        for kind in ("positive", "negative", "ambiguous", "adversarial")
    )
)
_POLICY = RetrievalEvaluationPolicy(
    top_k=5,
    min_recall_at_k=1.0,
    min_mean_reciprocal_rank=1.0,
    min_no_match_precision=1.0,
    required_cohorts=_COHORTS,
    schema_version="1.1.0",
    min_samples_per_metric=2,
)


def _manifest() -> QueryManifest:
    declarations = tuple(
        OntologyObjectType(
            schema_version="1.0.0",
            name=object_type,
            version="1.0.0",
            key="id",
            properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
        )
        for object_type in _TYPES
    )
    return build_query_manifest(
        release=build_ontology_release(object_types=declarations),
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest="sha256:" + "a" * 64,
        object_types=declarations,
    )


def _objects() -> tuple[OntologyObjectRecord, ...]:
    return tuple(
        OntologyObjectRecord(
            id=f"{object_type.lower()}-{index}",
            object_type=object_type,
            properties={"id": f"{object_type.lower()}-{index}"},
        )
        for object_type in _TYPES
        for index in range(2)
    )


def _cases() -> tuple[OntologyRetrievalEvaluationCase, ...]:
    # Deliberately mechanical fixtures verify admission, not label or language quality.
    return tuple(
        OntologyRetrievalEvaluationCase(
            case_id=f"{cohort}-{index}",
            query=f"{cohort} independent question {index}",
            cohort=cohort,
            expected_document_ids=(
                (f"object:{_TYPES[index // 2]}:{_TYPES[index // 2].lower()}-{index % 2}",)
                if cohort.endswith("-positive")
                else ()
            ),
        )
        for cohort in _COHORTS
        for index in range(4 if cohort.endswith("-positive") else 2)
    )


def _prepare(
    *,
    cases: tuple[OntologyRetrievalEvaluationCase, ...] | None = None,
    objects: tuple[OntologyObjectRecord, ...] | None = None,
    policy: RetrievalEvaluationPolicy = _POLICY,
    ranking: CatalogRankingPolicy = _RANKING,
    calibration_queries: tuple[str, ...] = ("separate calibration query",),
    model: str = "test-model-v1",
) -> OntologyRetrievalEvaluationPlan:
    manifest = _manifest()
    build = build_ontology_semantic_generation(
        manifest=manifest,
        embedding_space_id="test-space",
        embedding_model_version=model,
        embedding_dimension=1,
        runtime_objects=_objects() if objects is None else objects,
    )
    return prepare_ontology_retrieval_evaluation(
        build=build,
        manifest=manifest,
        cases=_cases() if cases is None else cases,
        calibration_queries=calibration_queries,
        ranking_policy=ranking,
        evaluation_policy=policy,
        required_object_types=_TYPES,
    )


def test_plan_binds_exact_inputs_without_qualifying_or_activating() -> None:
    plan = _prepare()
    assert plan.document_count == 6
    assert plan.query_count == 20
    assert plan.embedding_call_upper_bound == 26
    assert plan.production_qualification is False
    assert plan.execution_authority is False
    assert _prepare(cases=tuple(reversed(_cases()))) == plan
    assert _prepare(model="test-model-v2").binding_digest != plan.binding_digest
    assert (
        _prepare(ranking=CatalogRankingPolicy(minimum_score=0.3)).binding_digest
        != plan.binding_digest
    )
    assert _prepare(policy=replace(_POLICY, top_k=6)).binding_digest != plan.binding_digest
    assert (
        _prepare(calibration_queries=("different calibration",)).binding_digest
        != plan.binding_digest
    )
    changed = (replace(_cases()[0], query="different held-out question"), *_cases()[1:])
    assert _prepare(cases=changed).binding_digest != plan.binding_digest
    changed_objects = (
        replace(_objects()[0], properties={"id": "incident-0", "label": "changed"}),
        *_objects()[1:],
    )
    assert _prepare(objects=changed_objects).binding_digest != plan.binding_digest
    # Source revisions are independently checked by the reader, not embedded in documents.
    revisions_only = (replace(_objects()[0], revision=2), *_objects()[1:])
    assert _prepare(objects=revisions_only) == plan


@pytest.mark.parametrize("cohort", _COHORTS)
def test_missing_or_one_sample_cohort_cannot_be_hidden_by_aggregate(cohort: str) -> None:
    others = tuple(item for item in _cases() if item.cohort != cohort)
    with pytest.raises(ValueError, match="missing a required cohort"):
        _prepare(cases=others)
    one = next(item for item in _cases() if item.cohort == cohort)
    with pytest.raises(ValueError, match="per-cohort metric sample floor"):
        _prepare(cases=(*others, one))


def test_mixed_ambiguous_metric_cannot_borrow_positive_samples() -> None:
    cases = list(_cases())
    index = next(index for index, item in enumerate(cases) if item.cohort == "en-ambiguous")
    cases[index] = replace(cases[index], expected_document_ids=("object:Resource:resource-0",))
    with pytest.raises(ValueError, match="per-cohort metric sample floor"):
        _prepare(cases=tuple(cases))


@pytest.mark.parametrize("mutation", ["duplicate-id", "duplicate-query", "calibration", "oracle"])
def test_holdout_contamination_and_unresolved_oracles_are_rejected(mutation: str) -> None:
    cases = list(_cases())
    if mutation == "duplicate-id":
        cases[1] = replace(cases[1], case_id=cases[0].case_id)
    elif mutation == "duplicate-query":
        cases[1] = replace(cases[1], query=f"  {cases[0].query.upper()}  ")
    elif mutation == "calibration":
        cases[0] = replace(cases[0], query=" SEPARATE   CALIBRATION query ")
    else:
        index = next(index for index, item in enumerate(cases) if item.cohort.endswith("-positive"))
        cases[index] = replace(cases[index], expected_document_ids=("declaration:Resource",))
    with pytest.raises(ValueError, match="unique|calibration data|actual instance documents"):
        _prepare(cases=tuple(cases))


def test_repeated_paraphrases_do_not_establish_type_or_target_coverage() -> None:
    cases = tuple(
        replace(item, expected_document_ids=("object:Resource:resource-0",))
        if item.cohort.endswith("-positive")
        else item
        for item in _cases()
    )
    with pytest.raises(ValueError, match="distinct positive targets"):
        _prepare(cases=cases)
    with pytest.raises(ValueError, match="per-type sample floor"):
        _prepare(objects=_objects()[:2])


def test_undeclared_objects_cannot_enter_the_evaluation_corpus() -> None:
    with pytest.raises(ValueError, match="canonical manifest-declared instance documents"):
        _prepare(
            objects=(
                *_objects(),
                OntologyObjectRecord(id="unreadable", object_type="Private", properties={}),
            )
        )


@pytest.mark.parametrize(
    "policy",
    [
        replace(_POLICY, schema_version="1.0.0", min_samples_per_metric=None),
        replace(_POLICY, required_cohorts=("en-negative", "en-positive")),
    ],
)
def test_legacy_or_partial_policy_cannot_admit_a_new_instance_evaluation(
    policy: RetrievalEvaluationPolicy,
) -> None:
    with pytest.raises(ValueError, match="sample floor|all eight bilingual cohorts"):
        _prepare(policy=policy)
