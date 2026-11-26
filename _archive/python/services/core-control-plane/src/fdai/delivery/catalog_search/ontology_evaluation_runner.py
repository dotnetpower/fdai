"""Bounded off-path measurements through the real, currently authorized candidate reader."""

from __future__ import annotations

import asyncio
import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Literal

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.ontology_platform import QueryManifest
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.rule_catalog.schema.rule_semantic_evaluation import RetrievalEvaluationPolicy
from fdai.rule_catalog.schema.rule_semantic_retrieval import CohortMetric, query_digest

from .generation import SemanticGenerationBuild
from .ontology_candidate_reader import OntologyInstanceCandidateReader
from .ontology_evaluation import (
    OntologyRetrievalEvaluationCase,
    prepare_ontology_retrieval_evaluation,
)
from .ontology_snapshot_store import OntologyGenerationSnapshotStore, OntologyStagedProjection
from .ontology_snapshot_validation import (
    OntologySnapshotValidation,
    validate_snapshot_against_current_graph,
)
from .ranking import CatalogRankingPolicy


@dataclass(frozen=True, slots=True)
class OntologyRetrievalMeasurement:
    case_id: str
    query_digest: str
    retrieved_document_ids: tuple[str, ...]
    result_digest: str


@dataclass(frozen=True, slots=True)
class OntologyRetrievalEvaluationReport:
    """Measured candidate quality only, never independently reviewed qualification."""

    binding_digest: str
    measurements: tuple[OntologyRetrievalMeasurement, ...]
    source_validations: tuple[OntologySnapshotValidation, OntologySnapshotValidation]
    cohort_metrics: tuple[CohortMetric, ...]
    failure_codes: tuple[str, ...]
    stage: Literal["calibration", "holdout"] = "holdout"
    production_qualification: Literal[False] = field(default=False, init=False)
    execution_authority: Literal[False] = field(default=False, init=False)

    @property
    def passed(self) -> bool:
        return not self.failure_codes

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["source_validations"] = [item.receipt_digest for item in self.source_validations]
        return content_digest(payload)


class OntologyRetrievalEvaluationAbortedError(RuntimeError):
    """Preserve completed measurements without treating an unavailable call as no-match."""

    def __init__(
        self, binding_digest: str, completed: tuple[OntologyRetrievalMeasurement, ...]
    ) -> None:
        self.binding_digest = binding_digest
        self.completed = completed
        super().__init__(f"ontology retrieval evaluation aborted after {len(completed)} cases")


async def run_ontology_retrieval_evaluation(
    *,
    expected_binding_digest: str,
    build: SemanticGenerationBuild,
    manifest: QueryManifest,
    cases: Sequence[OntologyRetrievalEvaluationCase],
    calibration_queries: Sequence[str],
    ranking_policy: CatalogRankingPolicy,
    evaluation_policy: RetrievalEvaluationPolicy,
    required_object_types: tuple[str, ...],
    reader: OntologyInstanceCandidateReader,
    snapshots: OntologyGenerationSnapshotStore,
    staged: OntologyStagedProjection,
    gateway: SecuredObjectSetQueryGateway,
    clock: Callable[[], datetime],
    total_timeout_seconds: float,
    query_timeout_seconds: float,
) -> OntologyRetrievalEvaluationReport:
    """Measure frozen queries serially with no retries and no activation side effects.

    Callers must obtain live authorization before invoking this with a real embedder.
    This function neither stages vectors nor enables semantic search. Each returned
    candidate still traverses the reader's current graph authorization. Provider
    unavailability, drift or timeout aborts the attempt; parent cancellation propagates.
    """
    _validate_deadlines(total_timeout_seconds, query_timeout_seconds)
    cases = tuple(cases)
    plan = prepare_ontology_retrieval_evaluation(
        build=build,
        manifest=manifest,
        cases=cases,
        calibration_queries=calibration_queries,
        ranking_policy=ranking_policy,
        evaluation_policy=evaluation_policy,
        required_object_types=required_object_types,
    )
    if plan.binding_digest != expected_binding_digest:
        raise ValueError("ontology evaluation frozen input binding changed")
    return await _measure_ontology_retrieval_cases(
        binding_digest=plan.binding_digest,
        build=build,
        manifest=manifest,
        cases=cases,
        ranking_policy=ranking_policy,
        evaluation_policy=evaluation_policy,
        reader=reader,
        snapshots=snapshots,
        staged=staged,
        gateway=gateway,
        clock=clock,
        deadline=asyncio.get_running_loop().time() + total_timeout_seconds,
        query_timeout_seconds=query_timeout_seconds,
        stage="holdout",
    )


def _validate_deadlines(total_timeout_seconds: float, query_timeout_seconds: float) -> None:
    if (
        any(
            isinstance(value, bool) or not math.isfinite(value)
            for value in (total_timeout_seconds, query_timeout_seconds)
        )
        or not 0 < query_timeout_seconds <= min(total_timeout_seconds, 5)
        or total_timeout_seconds > 7200
    ):
        raise ValueError("ontology evaluation requires bounded total and per-query deadlines")


async def _measure_ontology_retrieval_cases(
    *,
    binding_digest: str,
    build: SemanticGenerationBuild,
    manifest: QueryManifest,
    cases: tuple[OntologyRetrievalEvaluationCase, ...],
    ranking_policy: CatalogRankingPolicy,
    evaluation_policy: RetrievalEvaluationPolicy,
    reader: OntologyInstanceCandidateReader,
    snapshots: OntologyGenerationSnapshotStore,
    staged: OntologyStagedProjection,
    gateway: SecuredObjectSetQueryGateway,
    clock: Callable[[], datetime],
    deadline: float,
    query_timeout_seconds: float,
    stage: Literal["calibration", "holdout"],
) -> OntologyRetrievalEvaluationReport:
    """Measure already admitted inputs, sharing the caller's absolute campaign deadline."""
    measurements: list[OntologyRetrievalMeasurement] = []

    def check_deadline(bound: float = deadline) -> None:
        if asyncio.get_running_loop().time() >= bound:
            raise TimeoutError("ontology evaluation deadline expired")

    async def validate_source() -> OntologySnapshotValidation:
        check_deadline()
        source_deadline = min(deadline, asyncio.get_running_loop().time() + 120)
        async with asyncio.timeout(120):
            validation = await validate_snapshot_against_current_graph(
                snapshots=snapshots,
                staged=staged,
                gateway=gateway,
                manifest=manifest,
                as_of=clock(),
                embedding_space_id=build.metadata.embedding_space_id,
                embedding_model_version=build.metadata.embedding_model_version,
                embedding_dimension=build.metadata.embedding_dimension,
                validator_id="offline-evaluation-source-check",
            )
        check_deadline(source_deadline)
        return validation

    try:
        async with asyncio.timeout_at(deadline):
            source_before = await validate_source()
            for case in cases:
                check_deadline()
                reader.validate_evaluation_binding(
                    staged=staged,
                    manifest=manifest,
                    generation_digest=build.metadata.generation_digest,
                    ranking_policy=ranking_policy,
                )
                query_deadline = min(
                    deadline, asyncio.get_running_loop().time() + query_timeout_seconds
                )
                async with asyncio.timeout(query_timeout_seconds):
                    result = await reader.search(
                        case.query,
                        staged=staged,
                        manifest=manifest,
                        gateway=gateway,
                        as_of=clock(),
                        limit=evaluation_policy.top_k,
                    )
                check_deadline(query_deadline)
                retrieved = tuple(item[0] for item in result.scores)
                result_digest = content_digest(
                    {
                        "manifest_digest": result.manifest_digest,
                        "ontology_release_digest": result.ontology_release_digest,
                        "authorized_result_digest": (
                            result.authorized.result_digest if result.authorized else None
                        ),
                        "scores": result.scores,
                        "matched_candidate_count": result.matched_candidate_count,
                        "returned_candidate_count": result.returned_candidate_count,
                        "truncated": result.truncated,
                        "authority": result.authority,
                        "execution_authority": result.execution_authority,
                    }
                )
                measurements.append(
                    OntologyRetrievalMeasurement(
                        case.case_id, query_digest(case.query), retrieved, result_digest
                    )
                )
            source_after = await validate_source()
    except (ValueError, PermissionError, TimeoutError):
        raise OntologyRetrievalEvaluationAbortedError(binding_digest, tuple(measurements)) from None
    metrics, failures = summarize_retrieval_measurements(cases, measurements, evaluation_policy)
    return OntologyRetrievalEvaluationReport(
        binding_digest=binding_digest,
        measurements=tuple(measurements),
        source_validations=(source_before, source_after),
        cohort_metrics=metrics,
        failure_codes=failures,
        stage=stage,
    )


def summarize_retrieval_measurements(
    cases: Sequence[OntologyRetrievalEvaluationCase],
    measurements: Sequence[OntologyRetrievalMeasurement],
    evaluation_policy: RetrievalEvaluationPolicy,
) -> tuple[tuple[CohortMetric, ...], tuple[str, ...]]:
    if not cases or len(cases) != len(measurements):
        raise ValueError("ontology metrics require complete case measurements")
    observed: dict[tuple[str, str], list[float]] = defaultdict(list)
    for case, measurement in zip(cases, measurements, strict=True):
        if (
            case.case_id != measurement.case_id
            or query_digest(case.query) != measurement.query_digest
        ):
            raise ValueError("ontology metric case binding changed")
        retrieved = measurement.retrieved_document_ids
        if case.expected_document_ids:
            expected = set(case.expected_document_ids)
            observed[case.cohort, f"recall-at-{evaluation_policy.top_k}"].append(
                len(expected.intersection(retrieved)) / len(expected)
            )
            observed[case.cohort, "mean-reciprocal-rank"].append(
                next(
                    (1 / rank for rank, item in enumerate(retrieved, 1) if item in expected),
                    0.0,
                )
            )
        else:
            observed[case.cohort, "no-match-precision"].append(float(not retrieved))
    metrics = tuple(
        CohortMetric(cohort, metric, sum(values) / len(values), len(values))
        for (cohort, metric), values in sorted(observed.items())
    )
    thresholds = {
        f"recall-at-{evaluation_policy.top_k}": evaluation_policy.min_recall_at_k,
        "mean-reciprocal-rank": evaluation_policy.min_mean_reciprocal_rank,
        "no-match-precision": evaluation_policy.min_no_match_precision,
    }
    return metrics, tuple(
        sorted(
            f"{item.cohort}-{item.metric}-below-threshold"
            for item in metrics
            if item.value < thresholds[item.metric]
        )
    )
