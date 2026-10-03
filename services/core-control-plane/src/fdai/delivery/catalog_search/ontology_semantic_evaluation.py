"""Separate, evidence-gated measurements of model-proposed typed candidate meaning."""

from __future__ import annotations

import asyncio
import logging
import math
import re
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
from .ontology_candidate_proposal import (
    OntologyCandidateModelBinding,
    OntologyCandidateProposer,
    candidate_proposal_payload,
)
from .ontology_candidate_reader import OntologyInstanceCandidateReader
from .ontology_candidate_selection import SELECTION_STRATEGY, OntologyCandidateSelection
from .ontology_evaluation import (
    OntologyRetrievalEvaluationCase,
    prepare_ontology_retrieval_evaluation,
)
from .ontology_evaluation_evidence import (
    OntologyEvaluationEvidence,
    OntologyEvaluationEvidenceError,
)
from .ontology_evaluation_runner import (
    OntologyRetrievalMeasurement,
    summarize_retrieval_measurements,
)
from .ontology_snapshot_store import OntologyGenerationSnapshotStore, OntologyStagedProjection
from .ontology_snapshot_validation import (
    OntologySnapshotValidation,
    validate_snapshot_against_current_graph,
)
from .ontology_vector_store import _check_deadline
from .ranking import CatalogRankingPolicy

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OntologySemanticEvaluationBudget:
    max_proposal_calls: int = 64
    total_timeout_seconds: float = 600
    query_timeout_seconds: float = 5

    def __post_init__(self) -> None:
        if (
            type(self.max_proposal_calls) is not int
            or not 1 <= self.max_proposal_calls <= 64
            or not math.isfinite(self.total_timeout_seconds)
            or not math.isfinite(self.query_timeout_seconds)
            or not 0 < self.query_timeout_seconds <= min(5, self.total_timeout_seconds)
            or not self.total_timeout_seconds <= 600
        ):
            raise ValueError("semantic evaluation requires bounded calls and deadlines")


@dataclass(frozen=True, slots=True)
class OntologySemanticEvaluationPlan:
    binding_digest: str
    model_binding: OntologyCandidateModelBinding
    model_name: str
    model_version: str
    source_commit: str
    budget: OntologySemanticEvaluationBudget
    stage: Literal["calibration", "holdout"]


@dataclass(frozen=True, slots=True)
class OntologySemanticEvaluationReport:
    binding_digest: str
    stage: Literal["calibration", "holdout"]
    measurements: tuple[OntologyRetrievalMeasurement, ...]
    outcomes: tuple[Literal["selected", "clarified"], ...]
    proposal_digests: tuple[str, ...]
    source_validations: tuple[OntologySnapshotValidation, OntologySnapshotValidation]
    cohort_metrics: tuple[CohortMetric, ...]
    failure_codes: tuple[str, ...]
    proposal_calls: int
    elapsed_seconds: float
    production_qualification: Literal[False] = field(default=False, init=False)
    execution_authority: Literal[False] = field(default=False, init=False)

    @property
    def passed(self) -> bool:
        return not self.failure_codes


class OntologySemanticEvaluationAbortedError(RuntimeError):
    def __init__(self, binding_digest: str, calls: int, completed: int) -> None:
        self.binding_digest, self.proposal_calls, self.completed = binding_digest, calls, completed
        super().__init__(
            f"semantic evaluation aborted after {calls} proposals and {completed} cases"
        )


def prepare_ontology_semantic_evaluation(
    *,
    build: SemanticGenerationBuild,
    manifest: QueryManifest,
    staged: OntologyStagedProjection,
    cases: Sequence[OntologyRetrievalEvaluationCase],
    calibration_queries: Sequence[str],
    ranking_policy: CatalogRankingPolicy,
    evaluation_policy: RetrievalEvaluationPolicy,
    required_object_types: tuple[str, ...],
    model_binding: OntologyCandidateModelBinding,
    model_name: str,
    model_version: str,
    source_commit: str,
    budget: OntologySemanticEvaluationBudget,
    stage: Literal["calibration", "holdout"] = "calibration",
) -> OntologySemanticEvaluationPlan:
    if (
        not re.fullmatch(r"[a-f0-9]{40}", source_commit)
        or any(not value.strip() or len(value) > 128 for value in (model_name, model_version))
        or any(
            re.fullmatch(r"sha256:[a-f0-9]{64}", value) is None
            for value in (
                model_binding.target_digest,
                model_binding.deployment_digest,
                model_binding.request_parameters_digest,
            )
        )
        or model_binding.prompt_manifest.profile_id != "diagnostic.ontology-candidate-selection"
        or stage not in ("calibration", "holdout")
        or (stage == "calibration") != (not calibration_queries)
        or len(cases) > budget.max_proposal_calls
    ):
        raise ValueError("semantic evaluation provenance, stage or call bound is invalid")
    retrieval = prepare_ontology_retrieval_evaluation(
        build=build,
        manifest=manifest,
        cases=cases,
        calibration_queries=calibration_queries,
        ranking_policy=ranking_policy,
        evaluation_policy=evaluation_policy,
        required_object_types=required_object_types,
    )
    binding = content_digest(
        {
            "schema_version": "1.0.0",
            "strategy": SELECTION_STRATEGY,
            "retrieval_preflight": retrieval.binding_digest,
            "ordered_cases": [case.case_id for case in cases],
            "snapshot": asdict(staged),
            "model_binding": asdict(model_binding),
            "model_name": model_name,
            "model_version": model_version,
            "source_commit": source_commit,
            "budget": asdict(budget),
            "stage": stage,
        }
    )
    return OntologySemanticEvaluationPlan(
        binding, model_binding, model_name, model_version, source_commit, budget, stage
    )


async def run_ontology_semantic_evaluation(
    *,
    plan: OntologySemanticEvaluationPlan,
    build: SemanticGenerationBuild,
    manifest: QueryManifest,
    staged: OntologyStagedProjection,
    cases: Sequence[OntologyRetrievalEvaluationCase],
    calibration_queries: Sequence[str],
    ranking_policy: CatalogRankingPolicy,
    evaluation_policy: RetrievalEvaluationPolicy,
    required_object_types: tuple[str, ...],
    model: OntologyCandidateProposer,
    reader: OntologyInstanceCandidateReader,
    snapshots: OntologyGenerationSnapshotStore,
    gateway: SecuredObjectSetQueryGateway,
    clock: Callable[[], datetime],
    evidence: OntologyEvaluationEvidence,
) -> OntologySemanticEvaluationReport:
    """Measure prepared inputs; caller attests live identity and authorizes the attempt.

    Proposal calls count interface attempts, not independently observed HTTP dispatches.
    Preparation belongs to its own bounded receipt. No vector is built or model enabled here.
    """
    cases = tuple(cases)
    expected = prepare_ontology_semantic_evaluation(
        build=build,
        manifest=manifest,
        staged=staged,
        cases=cases,
        calibration_queries=calibration_queries,
        ranking_policy=ranking_policy,
        evaluation_policy=evaluation_policy,
        required_object_types=required_object_types,
        model_binding=model.candidate_proposal_binding(),
        model_name=plan.model_name,
        model_version=plan.model_version,
        source_commit=plan.source_commit,
        budget=plan.budget,
        stage=plan.stage,
    )
    if (
        expected != plan
        or not evidence.semantic_proposals
        or evidence.source_commit != plan.source_commit
    ):
        raise ValueError("semantic evaluation input or evidence binding changed")
    started = asyncio.get_running_loop().time()
    deadline = started + plan.budget.total_timeout_seconds
    measurements: list[OntologyRetrievalMeasurement] = []
    outcomes: list[Literal["selected", "clarified"]] = []
    proposals: list[str] = []
    calls = 0
    phase = "source_before"
    evidence.record("started", {"kind": "typed_semantic_evaluation", "plan": plan})

    def validate_reader() -> None:
        _check_deadline(deadline)
        if model.candidate_proposal_binding() != plan.model_binding:
            raise ValueError("semantic evaluation model binding changed")
        reader.validate_evaluation_binding(
            staged=staged,
            manifest=manifest,
            generation_digest=build.metadata.generation_digest,
            ranking_policy=ranking_policy,
            require_typed_selection=True,
        )

    async def validate_source() -> OntologySnapshotValidation:
        validate_reader()
        bound = min(deadline, asyncio.get_running_loop().time() + 120)
        async with asyncio.timeout_at(bound):
            result = await validate_snapshot_against_current_graph(
                snapshots=snapshots,
                staged=staged,
                gateway=gateway,
                manifest=manifest,
                as_of=clock(),
                embedding_space_id=build.metadata.embedding_space_id,
                embedding_model_version=build.metadata.embedding_model_version,
                embedding_dimension=build.metadata.embedding_dimension,
                validator_id="semantic-evaluation-source-check",
            )
        _check_deadline(bound)
        return result

    try:
        async with asyncio.timeout_at(deadline):
            before = await validate_source()
            evidence.record("stage", {"stage": "source_before", "validation": before})
            for case in cases:
                validate_reader()
                phase = "proposal"
                bound = min(
                    deadline, asyncio.get_running_loop().time() + plan.budget.query_timeout_seconds
                )
                async with asyncio.timeout_at(bound):
                    payload = candidate_proposal_payload(
                        query=case.query, manifest=manifest, build=build, staged=staged
                    )
                    evidence.record(
                        "semantic_call_intent",
                        {
                            "call_index": calls + 1,
                            "case_id": case.case_id,
                            "input_digest": payload["input_digest"],
                        },
                    )
                    _check_deadline(bound)
                    calls += 1
                    _LOGGER.info("ontology_semantic_proposal_started", extra={"call_index": calls})
                    proposed = await model.propose_candidate_selection(
                        query=case.query, manifest=manifest, build=build, staged=staged
                    )
                    _check_deadline(bound)
                    validate_reader()
                    phase = "proposal_binding"
                    observation = proposed.observation
                    if (
                        proposed.input_digest != payload["input_digest"]
                        or content_digest({"deployment": observation.model})
                        != plan.model_binding.deployment_digest
                        or observation.prompt_replay_manifest != plan.model_binding.prompt_manifest
                    ):
                        raise ValueError("semantic proposal observation binding changed")
                    proposed.proposal.validate_source_quotes(case.query)
                    proposal_digest = content_digest(proposed.proposal.model_dump(mode="json"))
                    evidence.record(
                        "semantic_proposal",
                        {
                            "call_index": calls,
                            "proposal_digest": proposal_digest,
                            "status": proposed.proposal.status,
                            "reason": proposed.proposal.reason,
                            "clauses": [
                                clause.model_dump(mode="json")
                                for clause in proposed.proposal.clauses
                            ],
                            "quote_spans": [
                                (case.query.index(quote), case.query.index(quote) + len(quote))
                                for quote in proposed.proposal.clause_quotes
                            ],
                            "observation_digest": content_digest(asdict(observation)),
                        },
                    )
                    _check_deadline(bound)
                    if proposed.proposal.status == "clarify":
                        if proposed.selection is not None:
                            raise ValueError("clarification cannot carry a candidate selection")
                        retrieved: tuple[str, ...] = ()
                        result_digest = content_digest({"clarification": proposal_digest})
                        outcome: Literal["selected", "clarified"] = "clarified"
                    else:
                        phase = "membership"
                        expected_selection = OntologyCandidateSelection.bind(
                            query=case.query,
                            manifest=manifest,
                            staged=staged,
                            clauses=proposed.proposal.clauses,
                        )
                        if proposed.selection != expected_selection:
                            raise ValueError("semantic proposal selection binding changed")
                        result = await reader.search(
                            case.query,
                            staged=staged,
                            manifest=manifest,
                            gateway=gateway,
                            as_of=clock(),
                            limit=evaluation_policy.top_k,
                            selection=expected_selection,
                        )
                        if result.score_kind != "predicate_membership" or result.authorized is None:
                            raise ValueError("semantic evaluation requires membership evidence")
                        retrieved = tuple(item[0] for item in result.scores)
                        result_digest = content_digest(
                            {
                                "selection_digest": result.selection_digest,
                                "authorized_result": result.authorized.result_digest,
                                "matched": result.matched_candidate_count,
                                "returned": result.returned_candidate_count,
                                "truncated": result.truncated,
                                "scores": result.scores,
                            }
                        )
                        outcome = "selected"
                    _check_deadline(bound)
                    measurement = OntologyRetrievalMeasurement(
                        case.case_id, query_digest(case.query), retrieved, result_digest
                    )
                    evidence.record(
                        "semantic_measurement",
                        {
                            "call_index": calls,
                            "measurement": measurement,
                            "outcome": outcome,
                        },
                    )
                    _check_deadline(bound)
                    measurements.append(measurement)
                    outcomes.append(outcome)
                    proposals.append(proposal_digest)
            phase = "source_after"
            after = await validate_source()
            evidence.record("stage", {"stage": "source_after", "validation": after})
            metrics, failures = summarize_retrieval_measurements(
                cases, measurements, evaluation_policy
            )
            report = OntologySemanticEvaluationReport(
                plan.binding_digest,
                plan.stage,
                tuple(measurements),
                tuple(outcomes),
                tuple(proposals),
                (before, after),
                metrics,
                failures,
                calls,
                asyncio.get_running_loop().time() - started,
            )
            _check_deadline(deadline)
            phase = "completion"
            evidence.record("completed", {"report": report})
            _check_deadline(deadline)
            return report
    except asyncio.CancelledError:
        try:
            evidence.record("cancelled", {"proposal_calls": calls, "completed": len(measurements)})
        except OntologyEvaluationEvidenceError:
            _LOGGER.error("ontology_semantic_cancellation_evidence_unavailable")
        raise
    except OntologyEvaluationEvidenceError:
        raise
    except (ValueError, PermissionError, TimeoutError, RuntimeError) as exc:
        evidence.record(
            "aborted",
            {
                "binding_digest": plan.binding_digest,
                "proposal_calls": calls,
                "completed": len(measurements),
                "failure_type": type(exc).__name__,
                "stage": phase,
            },
        )
        _LOGGER.warning(
            "ontology_semantic_evaluation_aborted",
            extra={"stage": phase, "proposal_calls": calls, "failure_type": type(exc).__name__},
        )
        raise OntologySemanticEvaluationAbortedError(
            plan.binding_digest, calls, len(measurements)
        ) from None
