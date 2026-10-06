"""Approval profile Terraform input validation."""

from __future__ import annotations

import json
from typing import Any

from fdai_service_contracts.approval_profile import approval_profile_policy_digest


class ApprovalProfileTfvarsError(ValueError):
    """Raised when deploy-time approval profile input is invalid."""


def materialize_approval_profile(raw_json: str, *, development_profile_json: str = "") -> str:
    """Validate one deploy-time approval profile revision and return canonical JSON."""
    if development_profile_json.strip():
        raise ApprovalProfileTfvarsError(
            "FDAI_APPROVAL_PROFILE_JSON and FDAI_FULL_AUTHORITY_DEVELOPMENT_PROFILE_JSON "
            "are mutually exclusive"
        )
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ApprovalProfileTfvarsError(
            "FDAI_APPROVAL_PROFILE_JSON must contain valid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise ApprovalProfileTfvarsError("FDAI_APPROVAL_PROFILE_JSON must contain a JSON object")
    expected_fields = {
        "revision_id",
        "approval_profile",
        "executor_principal",
        "effective_from",
        "operator_principal",
        "policy_digest",
    }
    if set(payload) != expected_fields:
        raise ApprovalProfileTfvarsError(
            "FDAI_APPROVAL_PROFILE_JSON has unexpected approval profile fields"
        )
    if payload.get("approval_profile") != "single-operator-production":
        raise ApprovalProfileTfvarsError(
            "FDAI_APPROVAL_PROFILE_JSON must select single-operator-production"
        )
    if payload.get("policy_digest") != approval_profile_policy_digest(payload):
        raise ApprovalProfileTfvarsError(
            "FDAI_APPROVAL_PROFILE_JSON policy_digest does not match revision content"
        )
    return json.dumps(_payload_dict(payload), separators=(",", ":"), sort_keys=True)


def bind_approval_profile(
    materialized: dict[str, Any],
    *,
    service: str,
    raw_json: str | None,
    development_profile_json: str,
) -> None:
    """Attach validated approval profile JSON to Core tfvars when configured."""

    if not raw_json:
        return
    if service != "core-control-plane":
        raise ApprovalProfileTfvarsError(
            "approval profile binding is valid only for core-control-plane"
        )
    materialized["approval_profile_json"] = materialize_approval_profile(
        raw_json,
        development_profile_json=development_profile_json,
    )


def _payload_dict(payload: dict[Any, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in payload.items()}
