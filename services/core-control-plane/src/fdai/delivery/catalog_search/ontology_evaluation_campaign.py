"""Frozen calibration followed by strict holdout, without live-call or activation authority."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Literal

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.ontology_platform import QueryManifest
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.rule_catalog.schema.rule_semantic_evaluation import RetrievalEvaluationPolicy

from .generation import SemanticGenerationBuild
from .ontology_candidate_reader import OntologyInstanceCandidateReader
from .ontology_evaluation import (
    OntologyRetrievalEvaluationCase,
    _instance_types,
    _validate_evaluation_cases,
    prepare_ontology_retrieval_evaluation,
)
from .ontology_evaluation_runner import (
    OntologyRetrievalEvaluationAbortedError,
    OntologyRetrievalEvaluationReport,
    _measure_ontology_retrieval_cases,
    _validate_deadlines,
)
from .ontology_snapshot_store import OntologyGenerationSnapshotStore, OntologyStagedProjection
from .ranking import CatalogRankingPolicy


@dataclass(frozen=True, slots=True)
class OntologyRetrievalCampaignPlan:
    binding_digest: str
    holdout_binding_digest: str | None
    calibration_binding_digest: str
    embedding_call_upper_bound: int
    production_qualification: Literal[False] = field(default=False, init=False)
    execution_authority: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class OntologyRetrievalCampaignReport:
    binding_digest: str
    calibration: OntologyRetrievalEvaluationReport
    holdout: OntologyRetrievalEvaluationReport | None
    production_qualification: Literal[False] = field(default=False, init=False)
    execution_authority: Literal[False] = field(default=False, init=False)

    @property
    def passed(self) -> bool:
        return self.calibration.passed and self.holdout is not None and self.holdout.passed

    @property
    def digest(self) -> str:
        return content_digest(
            {
                "binding_digest": self.binding_digest,
                "calibration_digest": self.calibration.digest,
                "holdout_digest": self.holdout.digest if self.holdout else None,
                "production_qualification": False,
                "execution_authority": False,
            }
        )


class OntologyRetrievalCampaignAbortedError(RuntimeError):
    """Retain a completed calibration and partial failed stage, without provider details."""

    def __init__(
        self,
        binding_digest: str,
        stage: Literal["calibration", "holdout"],
        calibration: OntologyRetrievalEvaluationReport | None,
        failure: OntologyRetrievalEvaluationAbortedError,
    ) -> None:
        self.binding_digest = binding_digest
        self.stage = stage
        self.calibration = calibration
        self.completed = failure.completed
        super().__init__(
            f"ontology retrieval campaign aborted during {stage} after {len(self.completed)} cases"
        )


def prepare_ontology_retrieval_campaign(
    *,
    build: SemanticGenerationBuild,
    manifest: QueryManifest,
    calibration_cases: Sequence[OntologyRetrievalEvaluationCase],
    holdout_cases: Sequence[OntologyRetrievalEvaluationCase],
    ranking_policy: CatalogRankingPolicy,
    evaluation_policy: RetrievalEvaluationPolicy,
    required_object_types: tuple[str, ...],
    calibration_only: bool = False,
) -> OntologyRetrievalCampaignPlan:
    """Bind both ordered stages before measurement; calibration cannot qualify holdout.

    Calibration requires positives for each type and explicit no-match in both languages,
    but does not borrow or satisfy holdout sample floors. It uses the same frozen metric
    thresholds. Policy tuning requires a new plan, not an in-run change.
    Standalone calibration requires all policy cohorts and sample floors and no holdout.
    """
    calibration_cases, holdout_cases = tuple(calibration_cases), tuple(holdout_cases)
    if calibration_only:
        if holdout_cases:
            raise ValueError("calibration-only execution must not supply holdout cases")
        calibration = prepare_ontology_retrieval_evaluation(
            build=build,
            manifest=manifest,
            cases=calibration_cases,
            calibration_queries=(),
            ranking_policy=ranking_policy,
            evaluation_policy=evaluation_policy,
            required_object_types=required_object_types,
        )
        calibration_digest = content_digest(
            {
                "stage": "calibration",
                "evaluation_binding_digest": calibration.binding_digest,
                "case_order": [item.case_id for item in calibration_cases],
            }
        )
        return OntologyRetrievalCampaignPlan(
            binding_digest=content_digest(
                {"calibration_binding_digest": calibration_digest, "holdout_binding_digest": None}
            ),
            holdout_binding_digest=None,
            calibration_binding_digest=calibration_digest,
            embedding_call_upper_bound=calibration.embedding_call_upper_bound,
        )
    holdout = prepare_ontology_retrieval_evaluation(
        build=build,
        manifest=manifest,
        cases=holdout_cases,
        calibration_queries=tuple(item.query for item in calibration_cases),
        ranking_policy=ranking_policy,
        evaluation_policy=evaluation_policy,
        required_object_types=required_object_types,
    )
    objects = _instance_types(build, manifest)
    _validate_evaluation_cases(calibration_cases, objects, evaluation_policy.top_k)
    if {item.case_id for item in calibration_cases}.intersection(
        item.case_id for item in holdout_cases
    ):
        raise ValueError("ontology campaign stage case ids must be disjoint")
    for locale in ("en", "ko"):
        targets = {
            objects[document_id]
            for case in calibration_cases
            if case.cohort == f"{locale}-positive"
            for document_id in case.expected_document_ids
        }
        if not set(required_object_types).issubset(targets) or not any(
            case.cohort == f"{locale}-negative" for case in calibration_cases
        ):
            raise ValueError("ontology calibration requires bilingual type and no-match coverage")
    calibration_digest = content_digest(
        {
            "stage": "calibration",
            "holdout_binding_digest": holdout.binding_digest,
            "cases": [asdict(item) for item in calibration_cases],
        }
    )
    binding_digest = content_digest(
        {
            "schema_version": "1.0.0",
            "calibration_binding_digest": calibration_digest,
            "holdout_binding_digest": holdout.binding_digest,
            "holdout_case_order": [item.case_id for item in holdout_cases],
        }
    )
    return OntologyRetrievalCampaignPlan(
        binding_digest=binding_digest,
        calibration_binding_digest=calibration_digest,
        holdout_binding_digest=holdout.binding_digest,
        embedding_call_upper_bound=holdout.embedding_call_upper_bound + len(calibration_cases),
    )


async def run_ontology_retrieval_campaign(
    *,
    expected_binding_digest: str,
    build: SemanticGenerationBuild,
    manifest: QueryManifest,
    calibration_cases: Sequence[OntologyRetrievalEvaluationCase],
    holdout_cases: Sequence[OntologyRetrievalEvaluationCase],
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
    deadline: float | None = None,
    record_stage: Callable[[OntologyRetrievalEvaluationReport], None] | None = None,
    calibration_only: bool = False,
) -> OntologyRetrievalCampaignReport:
    """Measure one prepared generation, stopping before holdout on any calibration failure.

    Both stages share one monotonic deadline, policy and current-source checks. Preparation
    and document embedding are outside this deadline and need separately bounded authority.
    An enclosing absolute deadline can only shorten the local timeout.
    If supplied, stage recording must succeed before the next stage can begin.
    Callers must obtain live authorization before supplying a real embedder. Nothing here
    performs a retry, policy adjustment, production qualification or runtime activation.
    Calibration-only reports always lack a holdout and therefore never pass the full campaign.
    """
    _validate_deadlines(total_timeout_seconds, query_timeout_seconds)
    local_deadline = asyncio.get_running_loop().time() + total_timeout_seconds
    if deadline is not None and not math.isfinite(deadline):
        raise ValueError("ontology campaign requires a finite enclosing deadline")
    deadline = local_deadline if deadline is None else min(deadline, local_deadline)
    calibration_cases, holdout_cases = tuple(calibration_cases), tuple(holdout_cases)
    plan = prepare_ontology_retrieval_campaign(
        build=build,
        manifest=manifest,
        calibration_cases=calibration_cases,
        holdout_cases=holdout_cases,
        ranking_policy=ranking_policy,
        evaluation_policy=evaluation_policy,
        required_object_types=required_object_types,
        calibration_only=calibration_only,
    )
    if plan.binding_digest != expected_binding_digest:
        raise ValueError("ontology campaign frozen input binding changed")

    async def measure(
        cases: tuple[OntologyRetrievalEvaluationCase, ...],
        binding_digest: str,
        stage: Literal["calibration", "holdout"],
    ) -> OntologyRetrievalEvaluationReport:
        return await _measure_ontology_retrieval_cases(
            binding_digest=binding_digest,
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
            deadline=deadline,
            query_timeout_seconds=query_timeout_seconds,
            stage=stage,
        )

    calibration: OntologyRetrievalEvaluationReport | None = None
    stage: Literal["calibration", "holdout"] = "calibration"
    try:
        calibration = await measure(
            calibration_cases, plan.calibration_binding_digest, "calibration"
        )
        if record_stage is not None:
            record_stage(calibration)
        if not calibration.passed or plan.holdout_binding_digest is None:
            return OntologyRetrievalCampaignReport(plan.binding_digest, calibration, None)
        stage = "holdout"
        holdout = await measure(holdout_cases, plan.holdout_binding_digest, "holdout")
        if record_stage is not None:
            record_stage(holdout)
    except OntologyRetrievalEvaluationAbortedError as failure:
        raise OntologyRetrievalCampaignAbortedError(
            plan.binding_digest, stage, calibration, failure
        ) from None
    return OntologyRetrievalCampaignReport(plan.binding_digest, calibration, holdout)
