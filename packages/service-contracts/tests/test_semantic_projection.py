from __future__ import annotations

import copy
from typing import Any

import pytest
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.semantic_projection import (
    PANTHEON_ASSURANCE_REQUEST_KIND,
    SEMANTIC_QUERY_REQUEST_KIND,
    pantheon_assurance_evidence_digest,
    semantic_projection_commitment_violation,
    semantic_projection_evidence_digest,
    semantic_projection_id,
)


def _semantic_projection() -> dict[str, Any]:
    semantic_result = {
        "disposition": "answered",
        "reason_code": "semantic_answer_verified",
        "principal_manifest_digest": "sha256:" + ("a" * 64),
        "execution_receipt_digest": "sha256:" + ("b" * 64),
        "evidence_refs": ["receipt:one"],
        "answer": "검증된 답변입니다.",
    }
    projection: dict[str, Any] = {
        "schema_version": "1.4.0",
        "request_id": "request-1",
        "correlation_id": "correlation-1",
        "idempotency_key": "idempotency-1",
        "status": "answered",
        "recorded_at": "2026-09-29T01:00:00.000+00:00",
        "payload": {"request_kind": SEMANTIC_QUERY_REQUEST_KIND, "request_digest": "d1"},
        "evidence_digest": content_digest(semantic_result),
        "semantic_result": semantic_result,
    }
    projection["projection_id"] = semantic_projection_id(projection)
    return projection


def _pantheon_projection() -> dict[str, Any]:
    assurance = {
        "assessment_id": "assessment-1",
        "trace_receipt_id": "trace-1",
        "pantheon_diagnostic": {"owner": "bragi", "route": "explicit"},
        "assessment_state": "completed",
    }
    projection: dict[str, Any] = {
        "schema_version": "1.4.0",
        "request_id": "request-2",
        "correlation_id": "correlation-2",
        "idempotency_key": "idempotency-2",
        "status": "held",
        "recorded_at": "2026-09-29T01:00:00.000+00:00",
        "payload": {
            "request_kind": PANTHEON_ASSURANCE_REQUEST_KIND,
            "pantheon_assurance": assurance,
        },
        "evidence_digest": pantheon_assurance_evidence_digest(assurance),
        "semantic_result": {"disposition": "held"},
    }
    projection["projection_id"] = semantic_projection_id(projection)
    return projection


def test_projection_id_ignores_an_existing_id_and_binds_all_content() -> None:
    projection = _semantic_projection()
    without_id = {key: value for key, value in projection.items() if key != "projection_id"}

    assert semantic_projection_id(projection) == semantic_projection_id(without_id)
    assert (
        semantic_projection_id({**without_id, "recorded_at": "later"})
        != projection["projection_id"]
    )


def test_projection_id_requires_a_string_request_id() -> None:
    with pytest.raises(ValueError, match="request_id"):
        semantic_projection_id({"request_id": 7})


@pytest.mark.parametrize("builder", [_semantic_projection, _pantheon_projection])
def test_committed_projection_has_no_violation(builder: Any) -> None:
    projection = builder()

    assert semantic_projection_evidence_digest(projection) == projection["evidence_digest"]
    assert semantic_projection_commitment_violation(projection) is None


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("semantic_result", "principal_manifest_digest"), "sha256:" + ("c" * 64)),
        (("semantic_result", "execution_receipt_digest"), "sha256:" + ("d" * 64)),
        (("semantic_result", "evidence_refs"), ["receipt:forged"]),
        (("semantic_result", "answer"), "Forged answer."),
    ],
)
def test_changed_manifest_receipt_or_answer_breaks_the_evidence_digest(
    path: tuple[str, str],
    value: object,
) -> None:
    projection = copy.deepcopy(_semantic_projection())
    projection[path[0]][path[1]] = value

    assert semantic_projection_commitment_violation(projection) == "evidence_digest_mismatch"


def test_changed_payload_breaks_the_projection_id() -> None:
    projection = copy.deepcopy(_semantic_projection())
    projection["payload"]["rule_search"] = {"grants_action_authority": True}

    assert semantic_projection_commitment_violation(projection) == "projection_id_mismatch"


def test_recomputed_evidence_digest_cannot_hide_a_changed_result() -> None:
    projection = copy.deepcopy(_semantic_projection())
    projection["semantic_result"]["answer"] = "Forged answer."
    projection["evidence_digest"] = content_digest(projection["semantic_result"])

    assert semantic_projection_commitment_violation(projection) == "projection_id_mismatch"


def test_changed_pantheon_trace_breaks_the_evidence_digest() -> None:
    projection = copy.deepcopy(_pantheon_projection())
    projection["payload"]["pantheon_assurance"]["trace_receipt_id"] = "trace-forged"

    assert semantic_projection_commitment_violation(projection) == "evidence_digest_mismatch"


def test_pantheon_timing_outside_the_evidence_body_keeps_the_evidence_digest() -> None:
    projection = _pantheon_projection()
    assurance = projection["payload"]["pantheon_assurance"]

    assert pantheon_assurance_evidence_digest(
        {**assurance, "turn_timing": {"elapsed_ms": 5}}
    ) == pantheon_assurance_evidence_digest(assurance)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda projection: projection.pop("payload"),
        lambda projection: projection["payload"].pop("request_kind"),
        lambda projection: projection["payload"].update({"request_kind": "unknown"}),
        lambda projection: projection.pop("semantic_result"),
        lambda projection: projection.update({"request_id": None}),
    ],
)
def test_uncomputable_commitment_fails_closed(mutate: Any) -> None:
    projection = copy.deepcopy(_semantic_projection())
    mutate(projection)

    assert semantic_projection_commitment_violation(projection) == "commitment_uncomputable"


def test_pantheon_result_missing_an_evidence_field_fails_closed() -> None:
    projection = copy.deepcopy(_pantheon_projection())
    del projection["payload"]["pantheon_assurance"]["pantheon_diagnostic"]

    assert semantic_projection_commitment_violation(projection) == "commitment_uncomputable"
    with pytest.raises(ValueError, match="pantheon_diagnostic"):
        pantheon_assurance_evidence_digest(projection["payload"]["pantheon_assurance"])
