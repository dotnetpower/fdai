"""Load the repository bilingual golden dataset into the Core assurance contract."""

from __future__ import annotations

import json
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from fdai.core.conversation.question_campaign import QuestionCampaignHardZeroCounters
from fdai.core.conversation.question_golden import (
    GoldenAuthorityPosture,
    GoldenCaseCertification,
    GoldenOntologyExpectation,
    GoldenOntologyPath,
    GoldenOntologyPathStep,
    GoldenQuestionCase,
    GoldenQuestionCorpus,
    GoldenSemanticFrame,
    build_golden_corpus,
)
from fdai.core.conversation.question_perspectives import QuestionEvidencePosture

_MAX_DATASET_FILE_BYTES = 8 * 1024 * 1024
_EXPECTED_FILES = (
    "coverage.json",
    "expectations.json",
    "questions.en.json",
    "questions.ko.json",
)
_EXPECTED_DISPOSITIONS = {
    "action_draft": "action_draft",
    "answer": "answered",
    "clarify": "clarification",
    "hold": "held",
    "unsupported": "unsupported",
}
_NON_EXECUTING_DISPOSITIONS = frozenset({"clarification", "held", "unsupported"})


@dataclass(frozen=True, slots=True)
class GoldenCaseObservation:
    """Typed transport result used to evaluate one golden case without answer text parsing."""

    case_id: str
    frame: GoldenSemanticFrame | None
    capabilities: tuple[str, ...]
    object_types: tuple[str, ...]
    link_types: tuple[str, ...]
    function_types: tuple[str, ...]
    ontology: GoldenOntologyExpectation | None
    disposition: str
    fact_kinds: tuple[str, ...]
    limitations: tuple[str, ...]
    claim_kinds: tuple[str, ...]
    evidence_posture: QuestionEvidencePosture | None
    authority_posture: GoldenAuthorityPosture | None
    execution_authority: bool
    transport_passed: bool
    assessment_digest: str
    hard_zero: QuestionCampaignHardZeroCounters = QuestionCampaignHardZeroCounters()

    def __post_init__(self) -> None:
        for name, values in (
            ("capabilities", self.capabilities),
            ("object types", self.object_types),
            ("link types", self.link_types),
            ("function types", self.function_types),
            ("fact kinds", self.fact_kinds),
            ("limitations", self.limitations),
            ("claim kinds", self.claim_kinds),
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError(f"golden observation {name} MUST be ordered and unique")


def evaluate_golden_case_observation(
    case: GoldenQuestionCase,
    observation: GoldenCaseObservation,
) -> GoldenCaseCertification:
    """Reduce one fully typed observation to the existing deterministic golden gates."""

    if observation.case_id != case.case_id:
        raise ValueError("golden observation binds a different case")
    expected_non_answer = case.expected_disposition in _NON_EXECUTING_DISPOSITIONS
    frame_matched = _frame_matches(case.expected_frame, observation.frame)
    ontology_matched = _ontology_matches(case.expected_ontology, observation.ontology)
    if expected_non_answer:
        evidence_posture_matched = (
            observation.evidence_posture is case.evidence_posture
            if case.expected_disposition == "held"
            else observation.evidence_posture is QuestionEvidencePosture.UNAVAILABLE
        )
    else:
        evidence_posture_matched = observation.evidence_posture is case.evidence_posture
    return GoldenCaseCertification(
        case_id=case.case_id,
        semantic_frame_matched=frame_matched and (expected_non_answer or ontology_matched),
        capabilities_exact=expected_non_answer
        or (
            set(case.required_capabilities) <= set(observation.capabilities)
            and set(case.required_object_types) <= set(observation.object_types)
            and set(case.required_link_types) <= set(observation.link_types)
            and set(case.required_function_types) <= set(observation.function_types)
        ),
        disposition_allowed=observation.disposition == case.expected_disposition,
        required_facts_present=expected_non_answer
        or (
            set(case.required_facts) <= set(observation.fact_kinds)
            and set(case.required_limitations) <= set(observation.limitations)
        ),
        forbidden_claims_absent=not set(case.forbidden_claims) & set(observation.claim_kinds),
        evidence_posture_matched=evidence_posture_matched,
        authority_posture_matched=(
            not observation.execution_authority
            and observation.authority_posture is case.authority_posture
        ),
        transport_passed=observation.transport_passed,
        assessment_digest=observation.assessment_digest,
        hard_zero=observation.hard_zero,
    )


def _frame_matches(expected: GoldenSemanticFrame, observed: GoldenSemanticFrame | None) -> bool:
    if observed is None:
        return False
    return (
        observed.operation == expected.operation
        and observed.subject == expected.subject
        and observed.temporal_scope == expected.temporal_scope
        and (
            not expected.measure_concepts or observed.measure_concepts == expected.measure_concepts
        )
        and (expected.output_shape is None or observed.output_shape == expected.output_shape)
    )


def _ontology_matches(
    expected: GoldenOntologyExpectation | None,
    observed: GoldenOntologyExpectation | None,
) -> bool:
    if expected is None:
        return True
    if observed is None:
        return False
    return (
        observed.anchor_type == expected.anchor_type
        and set(expected.target_types) <= set(observed.target_types)
        and observed.min_traversal_depth == expected.min_traversal_depth
        and observed.max_traversal_depth == expected.max_traversal_depth
        and _canonical_paths(observed) == _canonical_paths(expected)
    )


def _canonical_paths(
    expectation: GoldenOntologyExpectation,
) -> tuple[tuple[tuple[str, str, str], ...], ...]:
    return tuple(
        sorted(
            tuple(
                (step.from_type, step.link_type, step.to_type)
                if step.direction == "outgoing"
                else (step.to_type, step.link_type, step.from_type)
                for step in path.steps
            )
            for path in expectation.paths
        )
    )


def load_golden_question_dataset(dataset_root: Path) -> GoldenQuestionCorpus:
    """Load one exact artifact set and reject cross-file identity or locale drift."""

    payloads = {name: _read_object(dataset_root / name) for name in _EXPECTED_FILES}
    expectations_payload = payloads["expectations.json"]
    coverage_payload = payloads["coverage.json"]
    english_payload = payloads["questions.en.json"]
    korean_payload = payloads["questions.ko.json"]
    if _required_string(expectations_payload, "schema_version") != "1.0.0":
        raise ValueError("golden expectation schema version is unsupported")
    if _required_string(coverage_payload, "schema_version") != "1.0.0":
        raise ValueError("golden coverage schema version is unsupported")
    if any(
        _required_string(payload, "schema_version") != "2.0.0"
        for payload in (english_payload, korean_payload)
    ):
        raise ValueError("golden question schema version is unsupported")
    dataset_version = _required_string(expectations_payload, "dataset_version")
    if any(
        _required_string(payload, "dataset_version") != dataset_version
        for payload in (coverage_payload, english_payload, korean_payload)
    ):
        raise ValueError("golden dataset versions MUST match")
    if _required_string(english_payload, "locale") != "en":
        raise ValueError("golden English question artifact locale is invalid")
    if _required_string(korean_payload, "locale") != "ko":
        raise ValueError("golden Korean question artifact locale is invalid")
    source_digest = _required_string(english_payload, "source_digest")
    if _required_string(korean_payload, "source_digest") != source_digest:
        raise ValueError("golden question source digests MUST match")

    expectations = _index_rows(
        expectations_payload,
        array_name="cases",
        id_name="semantic_pair_id",
    )
    coverage = _index_rows(
        coverage_payload,
        array_name="expectations",
        id_name="expectation_id",
    )
    english = _index_rows(english_payload, array_name="questions", id_name="case_id")
    korean = _index_rows(korean_payload, array_name="questions", id_name="case_id")
    if set(expectations) != set(coverage):
        raise ValueError("golden coverage MUST exactly match expectations")
    if set(english) != set(korean):
        raise ValueError("golden localized questions MUST have exact identity parity")

    cases: list[GoldenQuestionCase] = []
    for pair_id in sorted(english):
        english_row = english[pair_id]
        korean_row = korean[pair_id]
        expectation_id = _required_string(english_row, "expectation_id")
        if _required_string(korean_row, "expectation_id") != expectation_id:
            raise ValueError("golden bilingual questions bind different expectations")
        expectation = expectations.get(expectation_id)
        coverage_row = coverage.get(expectation_id)
        if expectation is None or coverage_row is None:
            raise ValueError("golden question references an unknown expectation")
        variation_kind = _required_string(english_row, "variation_kind")
        runtime_context = _required_string(english_row, "runtime_context")
        if (
            _required_string(korean_row, "variation_kind") != variation_kind
            or _required_string(korean_row, "runtime_context") != runtime_context
        ):
            raise ValueError("golden bilingual question metadata MUST match")
        if _required_string(coverage_row, "runtime_context") != runtime_context:
            raise ValueError("golden question runtime context conflicts with coverage")
        cases.extend(
            _build_pair(
                pair_id=pair_id,
                expectation=expectation,
                coverage=coverage_row,
                variation_kind=variation_kind,
                runtime_context=runtime_context,
                english_question=_required_string(english_row, "question"),
                korean_question=_required_string(korean_row, "question"),
            )
        )
    return build_golden_corpus(
        corpus_version=dataset_version,
        cases=cases,
        source_digest=source_digest,
    )


def _build_pair(
    *,
    pair_id: str,
    expectation: Mapping[str, Any],
    coverage: Mapping[str, Any],
    variation_kind: str,
    runtime_context: str,
    english_question: str,
    korean_question: str,
) -> tuple[GoldenQuestionCase, GoldenQuestionCase]:
    semantics = _required_object(expectation, "expected_semantics")
    retrieval = _required_object(expectation, "semantic_retrieval")
    answer_oracle = _required_object(expectation, "answer_oracle")
    operation = _required_string(semantics, "operation")
    expected_frame = GoldenSemanticFrame(
        operation=operation,
        subject=_required_string(semantics, "subject_type").casefold(),
        measure_concepts=(),
        output_shape=None,
        temporal_scope=_required_string(semantics, "temporal_scope"),
    )
    required_capabilities = _string_tuple(semantics, "required_capabilities")
    allowed_dispositions = _string_tuple(semantics, "allowed_dispositions")
    expected_posture = _required_string(coverage, "expected_posture")
    try:
        expected_disposition = _EXPECTED_DISPOSITIONS[expected_posture]
    except KeyError as error:
        raise ValueError("golden expected posture is unsupported") from error
    required_facts = _string_tuple(answer_oracle, "required_fact_kinds")
    forbidden_claims = _string_tuple(answer_oracle, "forbidden_claims")
    evidence_posture = QuestionEvidencePosture(_required_string(coverage, "evidence_posture"))
    authority_posture = (
        GoldenAuthorityPosture.DRAFT_ONLY
        if operation == "action_draft"
        else GoldenAuthorityPosture.READ_ONLY
    )
    required_object_types = _string_tuple(retrieval, "required_object_types")
    required_link_types = _string_tuple(retrieval, "required_link_types")
    required_function_types = _string_tuple(retrieval, "required_function_types")
    expected_ontology = _ontology_expectation(expectation)
    required_limitations = _string_tuple(answer_oracle, "required_limitations")

    def localized_case(*, locale: str, question: str) -> GoldenQuestionCase:
        return GoldenQuestionCase(
            case_id=f"{pair_id}.{locale}",
            semantic_pair_id=pair_id,
            locale=locale,
            question=question,
            expected_frame=expected_frame,
            required_capabilities=required_capabilities,
            allowed_dispositions=allowed_dispositions,
            expected_disposition=expected_disposition,
            required_facts=required_facts,
            forbidden_claims=forbidden_claims,
            evidence_posture=evidence_posture,
            authority_posture=authority_posture,
            required_object_types=required_object_types,
            required_link_types=required_link_types,
            required_function_types=required_function_types,
            expected_ontology=expected_ontology,
            required_limitations=required_limitations,
            runtime_context=runtime_context,
            variation_kind=variation_kind,
        )

    return (
        localized_case(locale="en", question=english_question),
        localized_case(locale="ko", question=korean_question),
    )


def _ontology_expectation(expectation: Mapping[str, Any]) -> GoldenOntologyExpectation:
    ontology = _required_object(expectation, "expected_ontology")
    raw_paths = _required_array(ontology, "paths")
    paths = tuple(
        sorted(
            (
                GoldenOntologyPath(
                    path_id=_required_string(path, "path_id"),
                    steps=tuple(
                        GoldenOntologyPathStep(
                            from_type=_required_string(step, "from_type"),
                            link_type=_required_string(step, "link_type"),
                            direction=_required_string(step, "direction"),
                            to_type=_required_string(step, "to_type"),
                        )
                        for step in _required_array(path, "steps")
                    ),
                )
                for path in raw_paths
            ),
            key=lambda item: item.path_id,
        )
    )
    return GoldenOntologyExpectation(
        anchor_type=_required_string(ontology, "anchor_type"),
        target_types=_string_tuple(ontology, "target_types"),
        paths=paths,
        min_traversal_depth=_required_int(ontology, "min_traversal_depth"),
        max_traversal_depth=_required_int(ontology, "max_traversal_depth"),
    )


def _read_object(path: Path) -> dict[str, Any]:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as error:
        raise ValueError(f"golden dataset file is unavailable: {path.name}") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_DATASET_FILE_BYTES:
        raise ValueError(f"golden dataset file is invalid: {path.name}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"golden dataset file is unreadable: {path.name}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"golden dataset file root MUST be an object: {path.name}")
    return cast(dict[str, Any], payload)


def _index_rows(
    payload: Mapping[str, Any], *, array_name: str, id_name: str
) -> dict[str, Mapping[str, Any]]:
    rows = _required_array(payload, array_name)
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        identifier = _required_string(row, id_name)
        if identifier in indexed:
            raise ValueError(f"golden dataset contains duplicate {id_name}")
        indexed[identifier] = row
    if not indexed:
        raise ValueError(f"golden dataset {array_name} MUST be non-empty")
    return indexed


def _required_array(payload: Mapping[str, Any], name: str) -> tuple[Mapping[str, Any], ...]:
    value = payload.get(name)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"golden dataset {name} MUST be an object array")
    return tuple(cast(Mapping[str, Any], item) for item in value)


def _required_object(payload: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = payload.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"golden dataset {name} MUST be an object")
    return cast(Mapping[str, Any], value)


def _required_string(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"golden dataset {name} MUST be non-empty text")
    return value


def _required_int(payload: Mapping[str, Any], name: str) -> int:
    value = payload.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"golden dataset {name} MUST be an integer")
    return value


def _string_tuple(payload: Mapping[str, Any], name: str) -> tuple[str, ...]:
    value = payload.get(name)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"golden dataset {name} MUST be a text array")
    return tuple(sorted(cast(list[str], value)))


__all__ = [
    "GoldenCaseObservation",
    "evaluate_golden_case_observation",
    "load_golden_question_dataset",
]
