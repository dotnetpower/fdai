"""Focused tests for the repository golden dataset delivery adapter."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from fdai.delivery.golden_question_dataset import (
    GoldenCaseObservation,
    evaluate_golden_case_observation,
    load_golden_question_dataset,
)

_ROOT = Path(__file__).resolve().parents[4]
_DATASET_ROOT = _ROOT / "eval" / "golden-dataset"


def _passing_observation(case):
    return GoldenCaseObservation(
        case_id=case.case_id,
        frame=case.expected_frame,
        capabilities=case.required_capabilities,
        object_types=case.required_object_types,
        link_types=case.required_link_types,
        function_types=case.required_function_types,
        ontology=case.expected_ontology,
        disposition=case.expected_disposition,
        fact_kinds=case.required_facts,
        limitations=case.required_limitations,
        claim_kinds=(),
        evidence_posture=case.evidence_posture,
        authority_posture=case.authority_posture,
        execution_authority=False,
        transport_passed=True,
        assessment_digest="sha256:" + "a" * 64,
    )


def test_typed_observation_adapter_certifies_complete_case() -> None:
    case = load_golden_question_dataset(_DATASET_ROOT).cases[0]

    certification = evaluate_golden_case_observation(case, _passing_observation(case))

    assert certification.passed is True


def test_typed_observation_adapter_fails_closed_on_missing_axes() -> None:
    case = load_golden_question_dataset(_DATASET_ROOT).cases[0]
    observation = _passing_observation(case)

    assert (
        evaluate_golden_case_observation(
            case,
            replace(observation, ontology=None),
        ).semantic_frame_matched
        is False
    )


def test_typed_observation_matches_ontology_path_semantics_not_local_path_id() -> None:
    case = next(
        item
        for item in load_golden_question_dataset(_DATASET_ROOT).cases
        if item.expected_disposition == "answered"
        and item.expected_ontology is not None
        and item.expected_ontology.paths
    )
    observation = _passing_observation(case)
    ontology = observation.ontology
    assert ontology is not None
    renamed = replace(
        ontology,
        paths=tuple(
            replace(path, path_id=f"runtime-{index}") for index, path in enumerate(ontology.paths)
        ),
    )

    certification = evaluate_golden_case_observation(
        case,
        replace(observation, ontology=renamed),
    )

    assert certification.semantic_frame_matched is True
    assert (
        evaluate_golden_case_observation(
            case,
            replace(observation, limitations=()),
        ).required_facts_present
        is False
    )
    assert (
        evaluate_golden_case_observation(
            case,
            replace(observation, execution_authority=True),
        ).authority_posture_matched
        is False
    )


def test_fresh_answer_case_cannot_pass_by_returning_a_hold() -> None:
    case = next(
        item
        for item in load_golden_question_dataset(_DATASET_ROOT).cases
        if item.expected_disposition == "answered" and item.evidence_posture.value == "fresh"
    )
    held = replace(
        _passing_observation(case),
        capabilities=(),
        object_types=(),
        link_types=(),
        function_types=(),
        ontology=None,
        disposition="held",
        fact_kinds=(),
        limitations=(),
        evidence_posture=type(case.evidence_posture).UNAVAILABLE,
    )

    certification = evaluate_golden_case_observation(case, held)

    assert certification.disposition_allowed is False
    assert certification.passed is False


def test_action_draft_keeps_execution_derived_gates() -> None:
    case = next(
        item
        for item in load_golden_question_dataset(_DATASET_ROOT).cases
        if item.expected_disposition == "action_draft"
    )
    incomplete = replace(
        _passing_observation(case),
        capabilities=(),
        object_types=(),
        link_types=(),
        function_types=(),
        ontology=None,
        fact_kinds=(),
        limitations=(),
    )

    certification = evaluate_golden_case_observation(case, incomplete)

    assert certification.capabilities_exact is False
    assert certification.required_facts_present is False
    assert certification.passed is False


def test_expected_clarification_does_not_require_unperformed_read_facts() -> None:
    case = next(
        item
        for item in load_golden_question_dataset(_DATASET_ROOT).cases
        if item.expected_disposition == "clarification"
    )
    clarification = replace(
        _passing_observation(case),
        capabilities=(),
        object_types=(),
        link_types=(),
        function_types=(),
        ontology=None,
        disposition="clarification",
        fact_kinds=(),
        limitations=(),
        evidence_posture=type(case.evidence_posture).UNAVAILABLE,
    )

    certification = evaluate_golden_case_observation(case, clarification)

    assert certification.semantic_frame_matched is True
    assert certification.capabilities_exact is True
    assert certification.required_facts_present is True
    assert certification.evidence_posture_matched is True
    assert certification.passed is True


def test_expected_hold_preserves_exact_evidence_posture() -> None:
    case = next(
        item
        for item in load_golden_question_dataset(_DATASET_ROOT).cases
        if item.expected_disposition == "held" and item.evidence_posture.value != "unavailable"
    )
    held = replace(
        _passing_observation(case),
        capabilities=(),
        object_types=(),
        link_types=(),
        function_types=(),
        ontology=None,
        disposition="held",
        fact_kinds=(),
        limitations=(),
        evidence_posture=type(case.evidence_posture).UNAVAILABLE,
    )

    certification = evaluate_golden_case_observation(case, held)

    assert certification.evidence_posture_matched is False
    assert certification.passed is False


def test_loader_rejects_unsupported_artifact_schema(tmp_path: Path) -> None:
    dataset_root = tmp_path / "golden-dataset"
    shutil.copytree(_DATASET_ROOT, dataset_root)
    coverage_path = dataset_root / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["schema_version"] = "2.0.0"
    coverage_path.write_text(json.dumps(coverage), encoding="utf-8")

    with pytest.raises(ValueError, match="coverage schema version"):
        load_golden_question_dataset(dataset_root)
