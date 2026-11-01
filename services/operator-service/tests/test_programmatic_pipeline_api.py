"""Tests for the Operator API programmatic pipeline submission boundary."""

from __future__ import annotations

import hashlib
import json

import pytest
from fdai_operator_service.programmatic_pipeline_api import (
    ProgrammaticPipelineOperatorEndpoint,
    ProgrammaticPipelineSubmissionError,
    submit_pipeline,
    submit_reviewed_programmatic_pipeline,
)

REVIEWED_SOURCE = "def main(client, inputs):\n    return {'count': len(inputs)}\n"
REVIEWED_DIGEST = hashlib.sha256(REVIEWED_SOURCE.encode("utf-8")).hexdigest()


def _valid_payload() -> dict[str, object]:
    return {
        "run_id": "run-op-1",
        "idempotency_key": "idem-op-1",
        "reviewed_source": REVIEWED_SOURCE,
        "reviewed_source_digest": REVIEWED_DIGEST,
        "sandbox_profile_id": "pipeline.local-read",
        "allowed_read_tools": ["tool.read-inventory"],
        "input_json": [json.dumps({"region": "koreacentral"})],
    }


def test_operator_submission_accepts_reviewed_digest_and_omits_sensitive_fields() -> None:
    response = submit_reviewed_programmatic_pipeline(
        principal_id="operator@example.com",
        roles=frozenset({"contributor"}),
        payload=_valid_payload(),
        reviewed_digest_allowlist=frozenset({REVIEWED_DIGEST}),
    )
    assert response["status"] == "accepted_proposal"
    assert response["reviewed_source_digest"] == REVIEWED_DIGEST
    assert response["execution_authority"] == "none"
    serialized = json.dumps(response)
    assert "capability_token" not in serialized
    assert "socket" not in serialized
    assert "credential" not in serialized


def test_operator_submission_rejects_unreviewed_or_mismatched_source_digest() -> None:
    payload = _valid_payload()
    with pytest.raises(ProgrammaticPipelineSubmissionError) as exc_info:
        submit_reviewed_programmatic_pipeline(
            principal_id="operator@example.com",
            roles=frozenset({"owner"}),
            payload=payload,
            reviewed_digest_allowlist=frozenset({"0" * 64}),
        )
    assert exc_info.value.code == "unreviewed_source_digest"
    assert exc_info.value.status_code == 403

    tampered = _valid_payload()
    tampered["reviewed_source"] = "def main(client, inputs):\n    return {}\n"
    with pytest.raises(ProgrammaticPipelineSubmissionError) as mismatch_info:
        submit_reviewed_programmatic_pipeline(
            principal_id="operator@example.com",
            roles=frozenset({"owner"}),
            payload=tampered,
            reviewed_digest_allowlist=frozenset({REVIEWED_DIGEST}),
        )
    assert mismatch_info.value.code == "digest_mismatch"


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "capability_token",
        "runner_socket",
        "socket_path",
        "runner_transport",
        "credentials",
        "secret",
        "authorization",
    ],
)
def test_operator_submission_rejects_tokens_transport_details_and_credentials(
    forbidden_key: str,
) -> None:
    payload = _valid_payload()
    payload[forbidden_key] = "must-not-cross-boundary"
    with pytest.raises(ProgrammaticPipelineSubmissionError) as exc_info:
        submit_reviewed_programmatic_pipeline(
            principal_id="operator@example.com",
            roles=frozenset({"owner"}),
            payload=payload,
            reviewed_digest_allowlist=frozenset({REVIEWED_DIGEST}),
        )
    assert exc_info.value.code == "forbidden_boundary_field"


def test_operator_submission_enforces_authentication_and_role_gate() -> None:
    with pytest.raises(ProgrammaticPipelineSubmissionError) as unauth_info:
        submit_reviewed_programmatic_pipeline(
            principal_id="   ",
            roles=frozenset({"owner"}),
            payload=_valid_payload(),
            reviewed_digest_allowlist=frozenset({REVIEWED_DIGEST}),
        )
    assert unauth_info.value.status_code == 401

    with pytest.raises(ProgrammaticPipelineSubmissionError) as role_info:
        submit_reviewed_programmatic_pipeline(
            principal_id="reader@example.com",
            roles=frozenset({"reader"}),
            payload=_valid_payload(),
            reviewed_digest_allowlist=frozenset({REVIEWED_DIGEST}),
        )
    assert role_info.value.status_code == 403

    dup_tools = _valid_payload()
    dup_tools["allowed_read_tools"] = ["tool.read-inventory", "tool.read-inventory"]
    with pytest.raises(ProgrammaticPipelineSubmissionError) as dup_info:
        submit_reviewed_programmatic_pipeline(
            principal_id="owner@example.com",
            roles=frozenset({"owner"}),
            payload=dup_tools,
            reviewed_digest_allowlist=frozenset({REVIEWED_DIGEST}),
        )
    assert dup_info.value.code == "duplicate_tool_ids"


def test_operator_submission_rejects_control_characters_and_boolean_numeric_bounds() -> None:
    with pytest.raises(ProgrammaticPipelineSubmissionError) as bad_principal:
        submit_reviewed_programmatic_pipeline(
            principal_id="operator\x00@example.com",
            roles=frozenset({"owner"}),
            payload=_valid_payload(),
            reviewed_digest_allowlist=frozenset({REVIEWED_DIGEST}),
        )
    assert bad_principal.value.code == "invalid_principal_id"

    for field, bad_val, expected_code in (
        ("idempotency_key", "idem-\n1", "invalid_idempotency_key"),
        ("correlation_id", "corr-\x1f1", "invalid_correlation_id"),
        ("max_steps", True, "invalid_max_steps"),
        ("max_wall_seconds", False, "invalid_max_wall_seconds"),
    ):
        bad_payload = _valid_payload()
        bad_payload[field] = bad_val
        with pytest.raises(ProgrammaticPipelineSubmissionError) as exc_info:
            submit_reviewed_programmatic_pipeline(
                principal_id="owner@example.com",
                roles=frozenset({"owner"}),
                payload=bad_payload,
                reviewed_digest_allowlist=frozenset({REVIEWED_DIGEST}),
            )
        assert exc_info.value.code == expected_code


@pytest.mark.parametrize(
    "trojan_char",
    ["\u200b", "\u200c", "\u200d", "\ufeff", "\u202a", "\u202e", "\u2066", "\u2069"],
)
def test_operator_submission_rejects_trojan_unicode_and_tracks_submitted_count_and_digest(
    trojan_char: str,
) -> None:
    for field, expected_code in (
        ("expression", "invalid_expression"),
        ("pipeline_id", "invalid_pipeline_id"),
        ("reviewed_source", "invalid_reviewed_source"),
    ):
        bad_payload = _valid_payload()
        bad_payload[field] = f"safe_prefix{trojan_char}suffix"
        with pytest.raises(ProgrammaticPipelineSubmissionError) as exc_info:
            submit_pipeline(
                principal_id="owner@example.com",
                roles=frozenset({"owner"}),
                payload=bad_payload,
                reviewed_digest_allowlist=frozenset({REVIEWED_DIGEST}),
            )
        assert exc_info.value.code == expected_code

    endpoint = ProgrammaticPipelineOperatorEndpoint(
        reviewed_digest_allowlist=frozenset({REVIEWED_DIGEST}),
    )
    assert endpoint.submitted_count == 0
    first = endpoint.submit_pipeline(
        principal_id="owner@example.com",
        roles=frozenset({"owner"}),
        payload=_valid_payload(),
    )
    digest = str(first["submission_digest"])
    assert digest.startswith("sha256:") and len(digest) == 71
    assert endpoint.submitted_count == 1

    # Duplicate submission keeps same digest and does not inflate distinct count
    replay = endpoint.submit_pipeline(
        principal_id="owner@example.com",
        roles=frozenset({"owner"}),
        payload=_valid_payload(),
    )
    assert replay["submission_digest"] == digest
    assert endpoint.submitted_count == 1

    second_payload = _valid_payload()
    second_payload["run_id"] = "run-op-2"
    second_payload["idempotency_key"] = "idem-op-2"
    second = endpoint.submit(
        principal_id="owner@example.com",
        roles=frozenset({"owner"}),
        payload=second_payload,
    )
    assert second["submission_digest"] != digest
    assert endpoint.submitted_count == 2
