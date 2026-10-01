"""Diagnostic execution budgets include preparation, never production activation or authority."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Literal

from fdai.core.ontology_platform import QueryManifest
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.rule_catalog.schema.rule_semantic_evaluation import RetrievalEvaluationPolicy
from fdai.shared.providers.knowledge import Embedder
from fdai.shared.providers.state_store import StateStore

from .generation import SemanticGenerationBuild
from .ontology_candidate_reader import OntologyInstanceCandidateReader
from .ontology_evaluation import OntologyRetrievalEvaluationCase
from .ontology_evaluation_campaign import (
    OntologyRetrievalCampaignAbortedError,
    OntologyRetrievalCampaignReport,
    prepare_ontology_retrieval_campaign,
    run_ontology_retrieval_campaign,
)
from .ontology_evaluation_evidence import (
    OntologyEvaluationEvidence,
    OntologyEvaluationEvidenceError,
)
from .ontology_evaluation_runner import OntologyRetrievalEvaluationReport
from .ontology_snapshot_store import OntologyGenerationSnapshotStore
from .ontology_snapshot_validation import validate_snapshot_against_current_graph
from .ontology_vector_store import OntologyVectorSnapshotStore
from .ranking import CatalogRankingPolicy

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OntologyRetrievalExecutionBudget:
    """An execution ceiling, not permission to use a provider or transfer source data."""

    max_embedding_calls: int
    total_timeout_seconds: float
    call_timeout_seconds: float

    def __post_init__(self) -> None:
        if (
            type(self.max_embedding_calls) is not int
            or not 1 <= self.max_embedding_calls <= 128
            or not math.isfinite(self.total_timeout_seconds)
            or not math.isfinite(self.call_timeout_seconds)
            or not 0 < self.call_timeout_seconds <= min(5, self.total_timeout_seconds)
            or not self.total_timeout_seconds <= 600
        ):
            raise ValueError("ontology diagnostic execution requires bounded calls and deadlines")


@dataclass(frozen=True, slots=True)
class OntologyRetrievalExecutionReport:
    campaign: OntologyRetrievalCampaignReport
    budget: OntologyRetrievalExecutionBudget
    embedding_calls: int
    elapsed_seconds: float
    production_qualification: Literal[False] = field(default=False, init=False)
    execution_authority: Literal[False] = field(default=False, init=False)


class OntologyRetrievalExecutionAbortedError(RuntimeError):
    """Bounded progress and nested measurement evidence, without provider error text."""

    def __init__(
        self,
        *,
        binding_digest: str,
        stage: Literal["preparation", "measurement"],
        embedding_calls: int,
        campaign_failure: OntologyRetrievalCampaignAbortedError | None = None,
        completed_campaign: OntologyRetrievalCampaignReport | None = None,
    ) -> None:
        self.binding_digest = binding_digest
        self.stage = stage
        self.embedding_calls = embedding_calls
        self.campaign_failure = campaign_failure
        self.completed_campaign = completed_campaign
        super().__init__(
            f"ontology diagnostic execution aborted during {stage} after {embedding_calls} calls"
        )


class _BudgetedEmbedder:
    def __init__(
        self,
        embedder: Embedder,
        *,
        build: SemanticGenerationBuild,
        budget: OntologyRetrievalExecutionBudget,
        deadline: float,
        evidence: OntologyEvaluationEvidence | None = None,
    ) -> None:
        self._embedder, self._budget = embedder, budget
        self._evidence = evidence
        self.deadline = deadline
        self._identity = (
            build.metadata.embedding_space_id,
            build.metadata.embedding_model_version,
            build.metadata.embedding_dimension,
        )
        self.calls = 0
        self.validate_identity()

    def validate_identity(self) -> None:
        if (
            getattr(self._embedder, "embedding_space_id", None),
            getattr(self._embedder, "embedding_model_version", None),
            getattr(self._embedder, "dim", None),
        ) != self._identity:
            raise ValueError("ontology diagnostic embedding identity changed or is unavailable")

    async def embed(self, text: str) -> Sequence[float]:
        self.validate_identity()
        _check_deadline(self.deadline)
        if self.calls >= self._budget.max_embedding_calls:
            raise ValueError("ontology diagnostic embedding call budget exhausted")
        deadline = min(
            self.deadline,
            asyncio.get_running_loop().time() + self._budget.call_timeout_seconds,
        )
        if self._evidence is not None:
            self._evidence.record("embedding_call_intent", {"call_index": self.calls + 1})
        _check_deadline(deadline)
        self.calls += 1
        _LOGGER.info("ontology_evaluation_embedding_started", extra={"call_index": self.calls})
        async with asyncio.timeout_at(deadline):
            vector = await self._embedder.embed(text)
        _check_deadline(deadline)
        self.validate_identity()
        return vector


def _check_deadline(deadline: float) -> None:
    if asyncio.get_running_loop().time() >= deadline:
        raise TimeoutError("ontology diagnostic execution deadline exceeded")


async def execute_ontology_retrieval_campaign(
    *,
    expected_binding_digest: str,
    build: SemanticGenerationBuild,
    manifest: QueryManifest,
    calibration_cases: Sequence[OntologyRetrievalEvaluationCase],
    holdout_cases: Sequence[OntologyRetrievalEvaluationCase],
    ranking_policy: CatalogRankingPolicy,
    evaluation_policy: RetrievalEvaluationPolicy,
    required_object_types: tuple[str, ...],
    state: StateStore,
    gateway: SecuredObjectSetQueryGateway,
    source_generation: str,
    embedder: Embedder,
    clock: Callable[[], datetime],
    budget: OntologyRetrievalExecutionBudget,
    evidence: OntologyEvaluationEvidence | None = None,
) -> OntologyRetrievalExecutionReport:
    """Prepare and measure one frozen corpus through isolated, caller-owned storage.

    A real embedder requires prior bounded live authorization and target attestation.
    The caller owns storage isolation and cleanup; this function never uses a runtime
    pointer, publishes an owner event, or retries. Preparation has a 120-second ceiling
    inside the same total deadline used by calibration and holdout. Provider calls are
    counted before dispatch, including failures. Parent cancellation propagates.
    Supply an open evidence writer for live diagnostics; it records call intent before
    dispatch and persists stage/terminal reports here, not in a later session-only writer.
    """
    started = asyncio.get_running_loop().time()
    deadline = started + budget.total_timeout_seconds
    calibration_cases, holdout_cases = tuple(calibration_cases), tuple(holdout_cases)
    plan = prepare_ontology_retrieval_campaign(
        build=build,
        manifest=manifest,
        calibration_cases=calibration_cases,
        holdout_cases=holdout_cases,
        ranking_policy=ranking_policy,
        evaluation_policy=evaluation_policy,
        required_object_types=required_object_types,
    )
    if plan.binding_digest != expected_binding_digest:
        raise ValueError("ontology campaign frozen input binding changed")
    if plan.embedding_call_upper_bound > budget.max_embedding_calls:
        raise ValueError("ontology campaign exceeds the embedding call budget")
    preparation_deadline = min(deadline, started + 120)
    bounded = _BudgetedEmbedder(
        embedder, build=build, budget=budget, deadline=preparation_deadline, evidence=evidence
    )
    if evidence is not None:
        evidence.record("started", {"plan": asdict(plan), "budget": asdict(budget)})

    def record_stage(report: OntologyRetrievalEvaluationReport) -> None:
        if evidence is not None:
            evidence.record("stage", {"report": asdict(report), "report_digest": report.digest})

    stage: Literal["preparation", "measurement"] = "preparation"
    completed_campaign: OntologyRetrievalCampaignReport | None = None
    try:
        _check_deadline(preparation_deadline)
        async with asyncio.timeout_at(preparation_deadline):
            snapshots = OntologyGenerationSnapshotStore(state)
            staged = await snapshots.stage_manifest_from_gateway(
                gateway=gateway,
                manifest=manifest,
                as_of=clock(),
                expected_source_generation=source_generation,
                embedding_space_id=build.metadata.embedding_space_id,
                embedding_model_version=build.metadata.embedding_model_version,
                embedding_dimension=build.metadata.embedding_dimension,
            )
            stored = await snapshots.read(
                staged.snapshot_digest,
                manifest=manifest,
                source_generation=source_generation,
                source_projection_digest=staged.source_projection_digest,
            )
            if stored is None or stored.metadata != build.metadata:
                raise ValueError("ontology diagnostic source changed before embedding")
            _check_deadline(preparation_deadline)
            vectors = OntologyVectorSnapshotStore(
                state,
                embedder=bounded,
                embedding_space_id=build.metadata.embedding_space_id,
                embedding_model_version=build.metadata.embedding_model_version,
                embedding_dimension=build.metadata.embedding_dimension,
                call_timeout_seconds=budget.call_timeout_seconds,
            )
            vector_digest = await vectors.stage(
                snapshots=snapshots,
                snapshot_digest=staged.snapshot_digest,
                manifest=manifest,
                source_generation=source_generation,
                source_projection_digest=staged.source_projection_digest,
            )
            validation = await validate_snapshot_against_current_graph(
                snapshots=snapshots,
                staged=staged,
                gateway=gateway,
                manifest=manifest,
                as_of=clock(),
                embedding_space_id=build.metadata.embedding_space_id,
                embedding_model_version=build.metadata.embedding_model_version,
                embedding_dimension=build.metadata.embedding_dimension,
                validator_id="Heimdall",
            )
            reader = OntologyInstanceCandidateReader(
                snapshots=snapshots, vectors=vectors, ranking_policy=ranking_policy
            )
            await reader.prepare(
                staged=staged, vector_digest=vector_digest, manifest=manifest, validation=validation
            )
        _check_deadline(preparation_deadline)
        bounded.validate_identity()
        stage = "measurement"
        bounded.deadline = deadline
        remaining = deadline - asyncio.get_running_loop().time()
        _check_deadline(deadline)
        report = await run_ontology_retrieval_campaign(
            expected_binding_digest=expected_binding_digest,
            build=build,
            manifest=manifest,
            calibration_cases=calibration_cases,
            holdout_cases=holdout_cases,
            ranking_policy=ranking_policy,
            evaluation_policy=evaluation_policy,
            required_object_types=required_object_types,
            reader=reader,
            snapshots=snapshots,
            staged=staged,
            gateway=gateway,
            clock=clock,
            total_timeout_seconds=remaining,
            query_timeout_seconds=min(budget.call_timeout_seconds, remaining),
            deadline=deadline,
            record_stage=record_stage,
        )
        completed_campaign = report
        _check_deadline(deadline)
        bounded.validate_identity()
    except OntologyRetrievalCampaignAbortedError as failure:
        if evidence is not None:
            evidence.record(
                "aborted",
                {
                    "binding_digest": plan.binding_digest,
                    "stage": stage,
                    "embedding_calls": bounded.calls,
                    "campaign_stage": failure.stage,
                    "calibration": asdict(failure.calibration) if failure.calibration else None,
                    "completed": [asdict(item) for item in failure.completed],
                },
            )
        raise OntologyRetrievalExecutionAbortedError(
            binding_digest=plan.binding_digest,
            stage=stage,
            embedding_calls=bounded.calls,
            campaign_failure=failure,
        ) from None
    except (ValueError, PermissionError, TimeoutError):
        if evidence is not None:
            evidence.record(
                "aborted",
                {
                    "binding_digest": plan.binding_digest,
                    "stage": stage,
                    "embedding_calls": bounded.calls,
                    "completed_campaign": (
                        asdict(completed_campaign) if completed_campaign is not None else None
                    ),
                },
            )
        raise OntologyRetrievalExecutionAbortedError(
            binding_digest=plan.binding_digest,
            stage=stage,
            embedding_calls=bounded.calls,
            completed_campaign=completed_campaign,
        ) from None
    except asyncio.CancelledError as cancelled:
        if evidence is not None:
            try:
                evidence.record(
                    "cancelled",
                    {
                        "binding_digest": plan.binding_digest,
                        "stage": stage,
                        "embedding_calls": bounded.calls,
                    },
                )
            except OntologyEvaluationEvidenceError as failure:
                cancelled.add_note("ontology cancellation evidence could not be retained")
                raise cancelled from failure
        raise
    result = OntologyRetrievalExecutionReport(
        report, budget, bounded.calls, asyncio.get_running_loop().time() - started
    )
    if evidence is not None:
        evidence.record("completed", {"report": asdict(result), "campaign_digest": report.digest})
    return result
