"""Offline admission of frozen instance-retrieval evaluation inputs, not qualification."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Literal

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.ontology_platform import QueryManifest
from fdai.rule_catalog.schema.rule_semantic_evaluation import RetrievalEvaluationPolicy
from fdai.rule_catalog.schema.rule_semantic_retrieval import query_digest
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

from .generation import (
    SemanticGenerationBuild,
    _runtime_object_documents,
    validate_ontology_semantic_generation,
)
from .ranking import CatalogRankingPolicy

_COHORTS = frozenset(
    f"{locale}-{kind}"
    for locale in ("en", "ko")
    for kind in ("positive", "negative", "ambiguous", "adversarial")
)


@dataclass(frozen=True, slots=True)
class OntologyRetrievalEvaluationCase:
    """Independently labelled document candidates; an empty oracle expects no candidates."""

    case_id: str
    query: str
    cohort: str
    expected_document_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.case_id.strip() or len(self.case_id) > 256:
            raise ValueError("ontology evaluation case id must be bounded and nonempty")
        if not self.query.strip() or len(self.query.encode("utf-8")) > 16_384:
            raise ValueError("ontology evaluation query must fit the actual reader byte limit")
        if self.cohort not in _COHORTS:
            raise ValueError("ontology evaluation requires an explicit language and cohort")
        if (
            len(self.expected_document_ids) > 100
            or self.expected_document_ids != tuple(sorted(set(self.expected_document_ids)))
            or any(not item.strip() or len(item) > 1024 for item in self.expected_document_ids)
        ):
            raise ValueError("ontology evaluation oracle must contain bounded ordered unique ids")
        if self.cohort.endswith("-positive") and not self.expected_document_ids:
            raise ValueError("ontology evaluation positive case requires an oracle")
        if self.cohort.endswith(("-negative", "-adversarial")) and self.expected_document_ids:
            raise ValueError("ontology evaluation no-match case must have an empty oracle")


@dataclass(frozen=True, slots=True)
class OntologyRetrievalEvaluationPlan:
    """Content-bound preparation only; no provider call, quality pass, or activation grant."""

    binding_digest: str
    dataset_digest: str
    generation_digest: str
    ranking_policy_digest: str
    evaluation_policy_digest: str
    document_count: int
    query_count: int
    embedding_call_upper_bound: int
    production_qualification: Literal[False] = field(default=False, init=False)
    execution_authority: Literal[False] = field(default=False, init=False)


def prepare_ontology_retrieval_evaluation(
    *,
    build: SemanticGenerationBuild,
    manifest: QueryManifest,
    cases: Sequence[OntologyRetrievalEvaluationCase],
    calibration_queries: Sequence[str],
    ranking_policy: CatalogRankingPolicy,
    evaluation_policy: RetrievalEvaluationPolicy,
    required_object_types: tuple[str, ...],
) -> OntologyRetrievalEvaluationPlan:
    """Freeze a multi-type bilingual holdout before requesting any live-model authority.

    Sample floors apply independently to positive and no-match metrics in each cohort.
    Every required type must also have distinct positive targets in each language.
    This rejects undersized pilots, but cannot certify label independence, production
    representativeness, current ACLs, model relevance, or human approval.
    """
    floor = evaluation_policy.min_samples_per_metric
    if evaluation_policy.schema_version != "1.1.0" or floor is None:
        raise ValueError("ontology evaluation requires the versioned metric sample floor")
    if not _COHORTS.issubset(evaluation_policy.required_cohorts):
        raise ValueError("ontology evaluation policy must require all eight bilingual cohorts")
    if len(required_object_types) < 2 or required_object_types != tuple(
        sorted(set(required_object_types))
    ):
        raise ValueError("ontology evaluation requires multiple ordered unique object types")
    if not 1 <= len(cases) <= 10_000 or len(calibration_queries) > 10_000:
        raise ValueError("ontology evaluation dataset must be bounded")
    validate_ontology_semantic_generation(
        build=build, manifest=manifest, validator_id="offline-evaluation-preflight"
    )
    if any(item.embedding or item.generation_id is not None for item in build.documents):
        raise ValueError("ontology evaluation requires canonical unembedded documents")
    objects = _instance_types(build, manifest)
    type_counts = Counter(objects.values())
    if any(type_counts[item] < floor for item in required_object_types):
        raise ValueError("ontology evaluation corpus is below the per-type sample floor")

    identities = tuple(item.case_id for item in cases)
    digests = tuple(query_digest(item.query) for item in cases)
    if len(set(identities)) != len(identities) or len(set(digests)) != len(digests):
        raise ValueError("ontology evaluation case ids and canonical queries must be unique")
    if set(digests).intersection(query_digest(item) for item in calibration_queries):
        raise ValueError("ontology held-out queries must not occur in calibration data")
    counts: Counter[tuple[str, bool]] = Counter()
    targets: dict[tuple[str, str], set[str]] = {}
    for case in cases:
        if any(item not in objects for item in case.expected_document_ids):
            raise ValueError("ontology evaluation oracle must resolve to actual instance documents")
        if len(case.expected_document_ids) > evaluation_policy.top_k:
            raise ValueError("ontology evaluation oracle exceeds the frozen retrieval limit")
        counts[case.cohort, bool(case.expected_document_ids)] += 1
        if case.cohort.endswith("-positive"):
            locale = case.cohort.split("-", 1)[0]
            for document_id in case.expected_document_ids:
                targets.setdefault((locale, objects[document_id]), set()).add(document_id)
    covered_cohorts = {key[0] for key in counts}
    if any(cohort not in covered_cohorts for cohort in evaluation_policy.required_cohorts):
        raise ValueError("ontology evaluation is missing a required cohort")
    if any(count < floor for count in counts.values()):
        raise ValueError("ontology evaluation is below a per-cohort metric sample floor")
    if any(
        len(targets.get((locale, object_type), set())) < floor
        for locale in ("en", "ko")
        for object_type in required_object_types
    ):
        raise ValueError(
            "ontology evaluation needs distinct positive targets per type and language"
        )
    dataset_digest = content_digest(
        {
            "cases": [asdict(item) for item in sorted(cases, key=lambda item: item.case_id)],
            "calibration_query_digests": sorted(query_digest(item) for item in calibration_queries),
            "required_object_types": required_object_types,
        }
    )
    ranking_digest = content_digest(asdict(ranking_policy))
    binding_digest = content_digest(
        {
            "schema_version": "1.0.0",
            "dataset_digest": dataset_digest,
            "generation_digest": build.metadata.generation_digest,
            "ranking_policy_digest": ranking_digest,
            "evaluation_policy_digest": evaluation_policy.digest,
        }
    )
    return OntologyRetrievalEvaluationPlan(
        binding_digest=binding_digest,
        dataset_digest=dataset_digest,
        generation_digest=build.metadata.generation_digest,
        ranking_policy_digest=ranking_digest,
        evaluation_policy_digest=evaluation_policy.digest,
        document_count=len(build.documents),
        query_count=len(cases),
        embedding_call_upper_bound=len(build.documents) + len(cases),
    )


def _instance_types(build: SemanticGenerationBuild, manifest: QueryManifest) -> dict[str, str]:
    readable_types = {
        str(item["name"]) for item in manifest.descriptors if item["kind"] == "object"
    }
    objects: dict[str, str] = {}
    for document in build.documents:
        if document.document_kind != "ontology_object":
            continue
        try:
            payload = json.loads(document.text)
            if (
                not isinstance(payload, dict)
                or set(payload) != {"id", "object_type", "properties"}
                or not isinstance(payload["id"], str)
                or not isinstance(payload["object_type"], str)
                or not isinstance(payload["properties"], dict)
                or payload["object_type"] not in readable_types
            ):
                raise ValueError("invalid document")
            record = OntologyObjectRecord(
                id=payload["id"],
                object_type=payload["object_type"],
                properties=payload["properties"],
            )
            if document != _runtime_object_documents((record,))[0] or document.rule_id in objects:
                raise ValueError("noncanonical document")
        except (ValueError, KeyError, TypeError):
            raise ValueError(
                "ontology evaluation requires canonical manifest-declared instance documents"
            ) from None
        objects[document.rule_id] = record.object_type
    return objects
