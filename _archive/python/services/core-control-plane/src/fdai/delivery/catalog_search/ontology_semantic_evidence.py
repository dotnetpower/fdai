"""Offline consistency checks of pinned diagnostics, never provider or quality attestation."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal

from fdai_service_contracts.ontology_query import content_digest
from pydantic import BaseModel, ConfigDict, Field, StrictInt, TypeAdapter

from fdai.core.ontology_platform import QueryManifest
from fdai.delivery.azure.llm.semantic_planning_config import candidate_proposal_schema_digest
from fdai.rule_catalog.schema.rule_semantic_evaluation import RetrievalEvaluationPolicy
from fdai.shared.providers.ontology_instance import json_values_equal

from .generation import SemanticGenerationBuild
from .ontology_candidate_proposal import OntologyCandidateProposal, candidate_proposal_payload
from .ontology_candidate_selection import OntologyCandidateClause
from .ontology_evaluation import OntologyRetrievalEvaluationCase
from .ontology_evaluation_evidence import (
    _MAX_RECORD_BYTES,
    _RECORD,
    _read_private_evidence_bytes,
)
from .ontology_evaluation_runner import summarize_retrieval_measurements
from .ontology_semantic_evaluation import (
    OntologySemanticEvaluationPlan,
    OntologySemanticEvaluationReport,
    prepare_ontology_semantic_evaluation,
)
from .ontology_snapshot_store import OntologyStagedProjection
from .ontology_snapshot_validation import OntologySnapshotValidation
from .ranking import CatalogRankingPolicy

_Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
_DIGEST = TypeAdapter(_Digest)
_PLAN = TypeAdapter(OntologySemanticEvaluationPlan)
_REPORT = TypeAdapter(OntologySemanticEvaluationReport)
_VALIDATION = TypeAdapter(OntologySnapshotValidation)


class _ProposalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    call_index: int = Field(strict=True, ge=1, le=64)
    proposal_digest: _Digest
    status: Literal["select", "clarify"]
    reason: str
    clauses: tuple[OntologyCandidateClause, ...] = Field(max_length=8)
    quote_spans: tuple[tuple[StrictInt, StrictInt], ...] = Field(max_length=8)
    observation_digest: _Digest
    response_schema_digest: _Digest
    quote_invalid_clauses: int = Field(strict=True, ge=0, le=8)

    def proposal(self, query: str) -> OntologyCandidateProposal:
        if any(not 0 <= start < end <= len(query) for start, end in self.quote_spans):
            raise ValueError("semantic evidence quote span is outside the frozen query")
        proposal = OntologyCandidateProposal.model_validate(
            {
                "status": self.status,
                "reason": self.reason,
                "clauses": self.clauses,
                "clause_quotes": tuple(query[start:end] for start, end in self.quote_spans),
            }
        )
        proposal.validate_source_quotes(query)
        if content_digest(proposal.model_dump(mode="json")) != self.proposal_digest:
            raise ValueError("semantic evidence proposal digest changed")
        return proposal


def verify_ontology_semantic_evidence(
    path: Path,
    *,
    expected_file_digest: str,
    plan: OntologySemanticEvaluationPlan,
    build: SemanticGenerationBuild,
    manifest: QueryManifest,
    staged: OntologyStagedProjection,
    cases: Sequence[OntologyRetrievalEvaluationCase],
    calibration_queries: Sequence[str],
    ranking_policy: CatalogRankingPolicy,
    evaluation_policy: RetrievalEvaluationPolicy,
    required_object_types: tuple[str, ...],
) -> OntologySemanticEvaluationReport:
    """Recompute frozen bindings, proposal identities and metrics without provider I/O.

    Pin the file digest and prepared inputs independently, not from the file being checked.
    A valid failed report is returned unchanged. Inconsistent or incomplete evidence raises
    a redacted ValueError. Recorded graph observations, model outputs and result digests are
    not independently reobserved here; consistency is neither authenticity nor qualification.
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
        model_binding=plan.model_binding,
        model_name=plan.model_name,
        model_version=plan.model_version,
        source_commit=plan.source_commit,
        budget=plan.budget,
        stage=plan.stage,
    )
    if expected != plan:
        raise ValueError("ontology semantic evidence frozen input binding changed")
    raw = _read_private_evidence_bytes(path, expected_file_digest)
    phase = "record_sequence"
    try:
        lines = raw.splitlines()
        if (
            not raw.endswith(b"\n")
            or len(lines) != 4 + 3 * len(cases)
            or any(len(line) + 1 > _MAX_RECORD_BYTES for line in lines)
        ):
            raise ValueError("incomplete evidence")
        records = tuple(_RECORD.validate_json(line, strict=True) for line in lines)
        for index, (record, line) in enumerate(zip(records, lines, strict=True)):
            if (
                record.sequence != index
                or record.source_commit != plan.source_commit
                or record.schema_version != "1.1.0"
                or record.recorded_at.tzinfo is None
                or (index > 0 and record.recorded_at < records[index - 1].recorded_at)
                or content_digest(json.loads(line))
                != content_digest(_RECORD.dump_python(record, mode="json"))
            ):
                raise ValueError("record identity changed")
        if (
            records[0].event != "started"
            or not json_values_equal(
                records[0].payload,
                {
                    "kind": "typed_semantic_evaluation",
                    "plan": _PLAN.dump_python(plan, mode="json"),
                },
            )
            or records[-1].event != "completed"
        ):
            raise ValueError("missing exact start or completion")

        phase = "report"
        report = _REPORT.validate_python(records[-1].payload.get("report"))
        encoded_report = _REPORT.dump_python(report, mode="json")
        if (
            content_digest(records[-1].payload) != content_digest({"report": encoded_report})
            or report.binding_digest != plan.binding_digest
            or report.stage != plan.stage
            or report.proposal_calls != len(cases)
            or len(report.measurements) != len(cases)
            or len(report.outcomes) != len(cases)
            or len(report.proposal_digests) != len(cases)
            or not math.isfinite(report.elapsed_seconds)
            or not 0 <= report.elapsed_seconds <= plan.budget.total_timeout_seconds
        ):
            raise ValueError("inconsistent report")

        phase = "source_validation"
        for record, stage, validation in zip(
            (records[1], records[-2]),
            ("source_before", "source_after"),
            report.source_validations,
            strict=True,
        ):
            _DIGEST.validate_python(validation.checked_projection_digest)
            if (
                record.event != "stage"
                or record.payload
                != {"stage": stage, "validation": _VALIDATION.dump_python(validation, mode="json")}
                or validation.snapshot_digest != staged.snapshot_digest
                or validation.generation_digest != build.metadata.generation_digest
                or validation.source_generation != staged.source_generation
                or validation.source_projection_digest != staged.source_projection_digest
                or validation.manifest_digest != manifest.manifest_digest
                or validation.principal_scope_digest
                != manifest.coverage_receipt.principal_scope_digest
                or validation.validator_id != "semantic-evaluation-source-check"
                or validation.checked_at.tzinfo is None
            ):
                raise ValueError("inconsistent source validation")
        if report.source_validations[1].checked_at < report.source_validations[0].checked_at:
            raise ValueError("source observation time regressed")

        phase = "proposal_measurement"
        document_ids = {
            item.rule_id for item in build.documents if item.rule_id.startswith("object:")
        }
        for index, case in enumerate(cases):
            intent, proposal_row, measured = records[2 + 3 * index : 5 + 3 * index]
            payload = candidate_proposal_payload(
                query=case.query, manifest=manifest, build=build, staged=staged
            )
            retained = _ProposalRecord.model_validate(proposal_row.payload)
            proposal = retained.proposal(case.query)
            measurement = report.measurements[index]
            _DIGEST.validate_python(measurement.result_digest)
            retrieved = measurement.retrieved_document_ids
            outcome = "selected" if proposal.status == "select" else "clarified"
            if (
                (intent.event, proposal_row.event, measured.event)
                != ("semantic_call_intent", "semantic_proposal", "semantic_measurement")
                or content_digest(intent.payload)
                != content_digest(
                    {
                        "call_index": index + 1,
                        "case_id": case.case_id,
                        "input_digest": payload["input_digest"],
                    }
                )
                or retained.call_index != index + 1
                or content_digest(proposal_row.payload)
                != content_digest(retained.model_dump(mode="json"))
                or retained.proposal_digest != report.proposal_digests[index]
                or retained.response_schema_digest
                != candidate_proposal_schema_digest(
                    manifest=manifest,
                    query=case.query,
                    build=build,
                )
                or report.outcomes[index] != outcome
                or content_digest(measured.payload)
                != content_digest(
                    {
                        "call_index": index + 1,
                        "outcome": outcome,
                        "measurement": encoded_report["measurements"][index],
                    }
                )
                or len(retrieved) > evaluation_policy.top_k
                or tuple(sorted(set(retrieved))) != retrieved
                or not set(retrieved) <= document_ids
                or (
                    outcome == "clarified"
                    and (
                        retrieved
                        or measurement.result_digest
                        != content_digest({"clarification": retained.proposal_digest})
                    )
                )
            ):
                raise ValueError("inconsistent proposal or measurement")
        phase = "metrics"
        metrics, failures = summarize_retrieval_measurements(
            cases, report.measurements, evaluation_policy
        )
        if report.cohort_metrics != metrics or report.failure_codes != failures:
            raise ValueError("reported metrics differ from frozen measurements")
    except ValueError:
        raise ValueError(f"ontology semantic evidence is inconsistent: {phase}") from None
    return report
