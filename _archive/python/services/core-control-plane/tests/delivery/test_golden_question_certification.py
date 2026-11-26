"""Focused golden semantic receipt certification tests."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fdai.delivery.golden_question_certification import (
    SemanticReceiptGoldenCertificationPort,
    golden_observation_from_semantic_receipt,
)
from fdai.delivery.golden_question_dataset import load_golden_question_dataset
from fdai_service_contracts.ontology_query import content_digest

_ROOT = Path(__file__).resolve().parents[4]
_DATASET_ROOT = _ROOT / "eval" / "golden-dataset"
_DIGEST = "sha256:" + ("a" * 64)


class _PassingTurns:
    async def submit(self, case):
        ontology = case.expected_ontology
        paths = [] if ontology is None else [asdict(path) for path in ontology.paths]
        subject_type = next(
            (
                object_type
                for object_type in case.required_object_types
                if object_type.casefold() == case.expected_frame.subject
            ),
            case.expected_frame.subject.capitalize(),
        )
        assurance = {
            "schema_version": "1.0.0",
            "frame": {
                "operation": case.expected_frame.operation,
                "subject_types": [subject_type],
                "measure_concepts": list(case.expected_frame.measure_concepts),
                "temporal_scope": case.expected_frame.temporal_scope,
                "output_shape": case.expected_frame.output_shape or "semantic_answer",
                "frame_digest": _DIGEST,
            },
            "capabilities": list(case.required_capabilities),
            "object_types": list(case.required_object_types),
            "link_types": list(case.required_link_types),
            "function_types": list(case.required_function_types),
            "ontology_paths": paths,
            "fact_kinds": list(case.required_facts),
            "limitation_kinds": list(case.required_limitations),
            "claim_kinds": [],
            "evidence_posture": (
                "unavailable"
                if case.expected_disposition in {"clarification", "unsupported"}
                else case.evidence_posture.value
            ),
            "authority_posture": case.authority_posture.value,
            "read_performed": True,
            "execution_authority": False,
        }
        assurance["observation_digest"] = content_digest(assurance)
        return {
            "schema_version": "2.0.0",
            "projection_id": "00000000-0000-0000-0000-000000000000",
            "request_id": "00000000-0000-0000-0000-000000000000",
            "disposition": case.expected_disposition,
            "reason_code": "semantic_answer_verified",
            "ontology_release_digest": _DIGEST,
            "principal_manifest_digest": _DIGEST,
            "plan_digest": _DIGEST,
            "execution_receipt_digest": _DIGEST,
            "assurance_observation": assurance,
            "execution_authority": False,
        }


def test_semantic_receipt_maps_to_typed_golden_observation() -> None:
    case = load_golden_question_dataset(_DATASET_ROOT).cases[0]

    receipt = _run_submit(case)
    observation = golden_observation_from_semantic_receipt(case, receipt)

    assert observation.case_id == case.case_id
    assert observation.transport_passed is True
    assert observation.execution_authority is False


async def test_semantic_receipt_port_covers_and_certifies_the_exact_corpus() -> None:
    corpus = load_golden_question_dataset(_DATASET_ROOT)
    port = SemanticReceiptGoldenCertificationPort(turns=_PassingTurns())

    receipt = await port.certify(
        corpus,
        ontology_release_digest=_DIGEST,
        principal_manifest_digests=(_DIGEST,),
    )

    assert receipt.case_count == 560
    assert receipt.passed_case_count == 560
    assert receipt.passed is True


def _run_submit(case):
    import asyncio

    return asyncio.run(_PassingTurns().submit(case))
