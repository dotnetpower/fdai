"""Authenticated Operator API submission boundary for reviewed programmatic tool pipelines."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_BOUNDED_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_FORBIDDEN_BOUNDARY_KEYS = frozenset(
    {
        "capability_token",
        "capability_tokens",
        "runner_socket",
        "socket_path",
        "workspace_root",
        "transport",
        "runner_transport",
        "credential",
        "credentials",
        "secret",
        "secrets",
        "access_token",
        "authorization",
    }
)
_ALLOWED_SUBMISSION_ROLES = frozenset({"contributor", "approver", "owner"})


class ProgrammaticPipelineSubmissionError(ValueError):
    """Raised when a pipeline submission violates boundary, digest, or RBAC rules."""

    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class ValidatedPipelineSubmission:
    principal_id: str
    run_id: str
    idempotency_key: str
    reviewed_source: str
    reviewed_source_digest: str
    input_json: tuple[str, ...]
    allowed_read_tools: tuple[str, ...]
    sandbox_profile_id: str


def submit_reviewed_programmatic_pipeline(
    *,
    principal_id: str,
    roles: frozenset[str] | set[str],
    payload: Mapping[str, Any],
    reviewed_digest_allowlist: frozenset[str] | set[str],
) -> dict[str, object]:
    """Validate and accept a reviewed-source pipeline submission at the Operator API boundary.

    Enforces:
    - Authenticated principal and Contributor/Approver/Owner role check.
    - Strict rejection of any capability token, runner transport detail, or credential field.
    - Exact SHA-256 match between `reviewed_source` and `reviewed_source_digest` plus membership
      in `reviewed_digest_allowlist`.
    - Sanitized response projection free of capability tokens, transport paths, and credentials.
    """
    actor = principal_id.strip()
    if not actor:
        raise ProgrammaticPipelineSubmissionError(
            "unauthenticated",
            "authenticated principal is required",
            status_code=401,
        )
    normalized_roles = {r.strip().lower() for r in roles if r.strip()}
    if not (normalized_roles & _ALLOWED_SUBMISSION_ROLES):
        raise ProgrammaticPipelineSubmissionError(
            "forbidden_role",
            "pipeline submission requires contributor, approver, or owner role",
            status_code=403,
        )

    if not isinstance(payload, Mapping):
        raise ProgrammaticPipelineSubmissionError(
            "invalid_payload",
            "submission payload must be a JSON object",
        )
    _reject_forbidden_boundary_fields(payload)

    run_id = _bounded_id(payload, "run_id")
    idempotency_key = _bounded_id(payload, "idempotency_key")
    sandbox_profile_id = _bounded_id(payload, "sandbox_profile_id")
    reviewed_source = _non_empty_text(payload, "reviewed_source")
    if len(reviewed_source.encode("utf-8")) > 256_000:
        raise ProgrammaticPipelineSubmissionError(
            "source_too_large",
            "reviewed_source exceeds 256000 bytes",
        )
    reviewed_source_digest = _non_empty_text(payload, "reviewed_source_digest")
    if _DIGEST_RE.fullmatch(reviewed_source_digest) is None:
        raise ProgrammaticPipelineSubmissionError(
            "invalid_digest",
            "reviewed_source_digest must be a 64-character lowercase SHA-256 hex digest",
        )
    computed_digest = hashlib.sha256(reviewed_source.encode("utf-8")).hexdigest()
    if computed_digest != reviewed_source_digest:
        raise ProgrammaticPipelineSubmissionError(
            "digest_mismatch",
            "reviewed_source does not match reviewed_source_digest",
        )
    if reviewed_source_digest not in reviewed_digest_allowlist:
        raise ProgrammaticPipelineSubmissionError(
            "unreviewed_source_digest",
            "reviewed_source_digest is not in the reviewed source allowlist",
            status_code=403,
        )

    raw_tools = payload.get("allowed_read_tools")
    if not isinstance(raw_tools, list) or not (1 <= len(raw_tools) <= 64):
        raise ProgrammaticPipelineSubmissionError(
            "invalid_tools",
            "allowed_read_tools must be a list of 1 to 64 read tool identifiers",
        )
    tools: list[str] = []
    for item in raw_tools:
        if (
            not isinstance(item, str)
            or _BOUNDED_ID_RE.fullmatch(item) is None
            or "pipeline" in item
        ):
            raise ProgrammaticPipelineSubmissionError(
                "invalid_tool_id",
                "allowed_read_tools contains an invalid or recursive tool identifier",
            )
        tools.append(item)
    if len(set(tools)) != len(tools):
        raise ProgrammaticPipelineSubmissionError(
            "duplicate_tool_ids",
            "allowed_read_tools must not contain duplicate tool identifiers",
        )

    raw_inputs = payload.get("input_json", [])
    if not isinstance(raw_inputs, list) or len(raw_inputs) > 64:
        raise ProgrammaticPipelineSubmissionError(
            "invalid_inputs",
            "input_json must be a list of at most 64 JSON strings",
        )
    inputs: list[str] = []
    for item in raw_inputs:
        if not isinstance(item, str):
            raise ProgrammaticPipelineSubmissionError(
                "invalid_input_item",
                "each input_json item must be a serialized JSON string",
            )
        try:
            parsed = json.loads(item)
        except json.JSONDecodeError as exc:
            raise ProgrammaticPipelineSubmissionError(
                "malformed_input_json",
                "each input_json item must be valid JSON",
            ) from exc
        _reject_forbidden_boundary_fields(parsed)
        inputs.append(item)

    submission = ValidatedPipelineSubmission(
        principal_id=actor,
        run_id=run_id,
        idempotency_key=idempotency_key,
        reviewed_source=reviewed_source,
        reviewed_source_digest=reviewed_source_digest,
        input_json=tuple(inputs),
        allowed_read_tools=tuple(sorted(set(tools))),
        sandbox_profile_id=sandbox_profile_id,
    )
    return {
        "schema_version": "fdai.operator.programmatic-pipeline-submission.v1",
        "status": "accepted_proposal",
        "principal_id": submission.principal_id,
        "run_id": submission.run_id,
        "idempotency_key": submission.idempotency_key,
        "reviewed_source_digest": submission.reviewed_source_digest,
        "sandbox_profile_id": submission.sandbox_profile_id,
        "allowed_read_tools": list(submission.allowed_read_tools),
        "input_count": len(submission.input_json),
        "execution_authority": "none",
    }


def _reject_forbidden_boundary_fields(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_BOUNDARY_KEYS:
                raise ProgrammaticPipelineSubmissionError(
                    "forbidden_boundary_field",
                    f"field {key!r} must never cross the Operator API boundary",
                )
            _reject_forbidden_boundary_fields(child)
    elif isinstance(value, list):
        for item in value:
            _reject_forbidden_boundary_fields(item)


def _non_empty_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProgrammaticPipelineSubmissionError(
            f"missing_{key}",
            f"{key} must be a non-empty string",
        )
    return value


def _bounded_id(payload: Mapping[str, Any], key: str) -> str:
    value = _non_empty_text(payload, key)
    if _BOUNDED_ID_RE.fullmatch(value) is None:
        raise ProgrammaticPipelineSubmissionError(
            f"invalid_{key}",
            f"{key} must be a bounded identifier",
        )
    return value


__all__ = [
    "ProgrammaticPipelineSubmissionError",
    "ValidatedPipelineSubmission",
    "submit_reviewed_programmatic_pipeline",
]
