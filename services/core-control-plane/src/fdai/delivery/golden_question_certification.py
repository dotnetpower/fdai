"""Execute and reduce the bilingual golden corpus through typed semantic receipts."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fdai_service_contracts import SemanticAssuranceObservation
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.conversation.question_campaign import QuestionCampaignHardZeroCounters
from fdai.core.conversation.question_golden import (
    GoldenAuthorityPosture,
    GoldenCaseCertification,
    GoldenCertificationReceipt,
    GoldenOntologyExpectation,
    GoldenOntologyPath,
    GoldenOntologyPathStep,
    GoldenQuestionCase,
    GoldenQuestionCorpus,
    GoldenSemanticFrame,
    evaluate_golden_certification,
)
from fdai.core.conversation.question_perspectives import QuestionEvidencePosture
from fdai.delivery.golden_question_dataset import (
    GoldenCaseObservation,
    evaluate_golden_case_observation,
)

_DIGEST_PREFIX = "sha256:"


class GoldenSemanticTurnPort(Protocol):
    """Submit one immutable case and return its authenticated v2 semantic receipt."""

    async def submit(self, case: GoldenQuestionCase) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class GoldenCertificationLimits:
    """Absolute per-turn and campaign deadlines for one golden execution."""

    per_turn_seconds: float = 90.0
    total_seconds: float = 7_200.0

    def __post_init__(self) -> None:
        if not 0 < self.per_turn_seconds <= 90:
            raise ValueError("golden per-turn deadline MUST be in (0, 90]")
        if not 0 < self.total_seconds <= 7_200:
            raise ValueError("golden total deadline MUST be in (0, 7200]")


_DEFAULT_LIMITS = GoldenCertificationLimits()


class SemanticReceiptGoldenCertificationPort:
    """Certify every corpus case from an authenticated content-free receipt."""

    def __init__(
        self,
        *,
        turns: GoldenSemanticTurnPort,
        limits: GoldenCertificationLimits = _DEFAULT_LIMITS,
    ) -> None:
        self._turns = turns
        self._limits = limits

    async def certify(
        self,
        corpus: GoldenQuestionCorpus,
        *,
        ontology_release_digest: str,
        principal_manifest_digests: tuple[str, ...],
    ) -> GoldenCertificationReceipt:
        """Run all cases serially and record a failed gate for every bounded failure."""

        started = time.monotonic()
        results: list[GoldenCaseCertification] = []
        for case in corpus.cases:
            remaining = self._limits.total_seconds - (time.monotonic() - started)
            if remaining <= 0:
                results.append(_failed_case(case, reason="golden_campaign_deadline_exceeded"))
                continue
            timeout = min(self._limits.per_turn_seconds, remaining)
            try:
                receipt = await asyncio.wait_for(self._turns.submit(case), timeout=timeout)
                observation = golden_observation_from_semantic_receipt(case, receipt)
                results.append(evaluate_golden_case_observation(case, observation))
            except Exception as error:  # noqa: BLE001 - one bad turn must not erase case accounting
                results.append(
                    _failed_case(
                        case,
                        reason=_bounded_failure_reason(error),
                    )
                )
        return evaluate_golden_certification(
            corpus=corpus,
            ontology_release_digest=ontology_release_digest,
            principal_manifest_digests=principal_manifest_digests,
            results=results,
        )


def golden_observation_from_semantic_receipt(
    case: GoldenQuestionCase,
    receipt: Mapping[str, object],
) -> GoldenCaseObservation:
    """Validate and reduce one Console semantic receipt without reading answer prose."""

    if receipt.get("schema_version") != "2.0.0":
        raise ValueError("golden semantic receipt requires schema version 2.0.0")
    projection_id = _uuid_text(receipt, "projection_id")
    request_id = _uuid_text(receipt, "request_id")
    disposition = _text(receipt, "disposition")
    reason_code = _text(receipt, "reason_code")
    if receipt.get("execution_authority") is not False:
        raise ValueError("golden semantic receipt MUST deny execution authority")
    assurance = SemanticAssuranceObservation.model_validate(receipt.get("assurance_observation"))
    frame = _golden_frame(case, assurance)
    ontology = _golden_ontology(case, assurance)
    assessment_digest = content_digest(
        {
            "case_id": case.case_id,
            "projection_id": projection_id,
            "request_id": request_id,
            "disposition": disposition,
            "reason_code": reason_code,
            "assurance_observation_digest": assurance.observation_digest,
            "ontology_release_digest": receipt.get("ontology_release_digest"),
            "principal_manifest_digest": receipt.get("principal_manifest_digest"),
            "plan_digest": receipt.get("plan_digest"),
            "execution_receipt_digest": receipt.get("execution_receipt_digest"),
            "execution_authority": False,
        }
    )
    forbidden = set(case.forbidden_claims) & set(assurance.claim_kinds)
    return GoldenCaseObservation(
        case_id=case.case_id,
        frame=frame,
        capabilities=assurance.capabilities,
        object_types=assurance.object_types,
        link_types=assurance.link_types,
        function_types=assurance.function_types,
        ontology=ontology,
        disposition=disposition,
        fact_kinds=assurance.fact_kinds,
        limitations=assurance.limitation_kinds,
        claim_kinds=assurance.claim_kinds,
        evidence_posture=QuestionEvidencePosture(assurance.evidence_posture),
        authority_posture=GoldenAuthorityPosture(assurance.authority_posture),
        execution_authority=False,
        transport_passed=True,
        assessment_digest=assessment_digest,
        hard_zero=QuestionCampaignHardZeroCounters(
            unsupported_claim_count=len(forbidden),
        ),
    )


def _golden_frame(
    case: GoldenQuestionCase,
    observation: SemanticAssuranceObservation,
) -> GoldenSemanticFrame | None:
    frame = observation.frame
    expected_subject = case.expected_frame.subject
    if frame is None or expected_subject not in {
        subject.casefold() for subject in frame.subject_types
    }:
        return None
    return GoldenSemanticFrame(
        operation=frame.operation.value,
        subject=expected_subject,
        measure_concepts=frame.measure_concepts,
        output_shape=frame.output_shape,
        temporal_scope=frame.temporal_scope,
    )


def _golden_ontology(
    case: GoldenQuestionCase,
    observation: SemanticAssuranceObservation,
) -> GoldenOntologyExpectation | None:
    frame = observation.frame
    expected = case.expected_ontology
    if (
        frame is None
        or expected is None
        or expected.anchor_type.casefold()
        not in {subject.casefold() for subject in frame.subject_types}
    ):
        return None
    paths = tuple(
        GoldenOntologyPath(
            path_id=path.path_id,
            steps=tuple(
                GoldenOntologyPathStep(
                    from_type=step.from_type,
                    link_type=step.link_type,
                    direction=step.direction,
                    to_type=step.to_type,
                )
                for step in path.steps
            ),
        )
        for path in observation.ontology_paths
    )
    depths = tuple(len(path.steps) for path in paths)
    target_types = (
        tuple(sorted({step.to_type for path in paths for step in path.steps}))
        if paths
        else (expected.anchor_type,)
    )
    return GoldenOntologyExpectation(
        anchor_type=expected.anchor_type,
        target_types=target_types,
        paths=paths,
        min_traversal_depth=min(depths, default=0),
        max_traversal_depth=max(depths, default=0),
    )


def _failed_case(case: GoldenQuestionCase, *, reason: str) -> GoldenCaseCertification:
    return GoldenCaseCertification(
        case_id=case.case_id,
        semantic_frame_matched=False,
        capabilities_exact=False,
        disposition_allowed=False,
        required_facts_present=False,
        forbidden_claims_absent=False,
        evidence_posture_matched=False,
        authority_posture_matched=False,
        transport_passed=False,
        assessment_digest=content_digest({"case_id": case.case_id, "failure": reason}),
    )


def _bounded_failure_reason(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return "golden_turn_deadline_exceeded"
    return type(error).__name__.casefold()[:64] or "golden_turn_failed"


def _text(receipt: Mapping[str, object], key: str) -> str:
    value = receipt.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"golden semantic receipt {key} is malformed")
    return value


def _uuid_text(receipt: Mapping[str, object], key: str) -> str:
    value = _text(receipt, key)
    try:
        UUID(value)
    except ValueError as error:
        raise ValueError(f"golden semantic receipt {key} is malformed") from error
    return value


__all__ = [
    "GoldenCertificationLimits",
    "GoldenSemanticTurnPort",
    "SemanticReceiptGoldenCertificationPort",
    "golden_observation_from_semantic_receipt",
]
