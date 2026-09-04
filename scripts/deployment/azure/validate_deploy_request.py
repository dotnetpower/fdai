#!/usr/bin/env python3
"""Validate one deploy-dev request before Azure or Terraform operations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_PLAN_REQUEST = re.compile(
    r"^plan-([0-9a-f]{48}|rca-[0-9a-f]{48}|chatops-[0-9a-f]{24}|quorum-[0-9a-f]{24}|"
    r"model-[0-9a-f]{32}-[0-9a-f]{64})$"
)
_APPLY_REQUEST = re.compile(
    r"^apply-([0-9a-f]{48}|rca-[0-9a-f]{48}|chatops-[0-9a-f]{24}|quorum-[0-9a-f]{24}|"
    r"model-[0-9a-f]{64})$"
)
_PLAN_ID = re.compile(r"^plan-[1-9][0-9]*-[1-9][0-9]*$")
_TRUE = "true"
_GUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_API_SCOPE = re.compile(r"^api://[^/]+/[^/]+$")


def _enabled(values: Mapping[str, str], key: str) -> bool:
    value = values.get(key, "false")
    if value not in {_TRUE, "false"}:
        raise ValueError(f"{key} must be true or false")
    return value == _TRUE


def _require_match(value: str, pattern: re.Pattern[str], message: str) -> None:
    if pattern.fullmatch(value) is None:
        raise ValueError(message)


def validate(values: Mapping[str, str], *, checkout_commit: str) -> None:
    """Reject mixed, stale, or unbound deployment requests."""
    apply = _enabled(values, "APPLY")
    deploy_gateway = _enabled(values, "DEPLOY_DEV_OPERATIONS_GATEWAY")
    deploy_console = _enabled(values, "DEPLOY_CONSOLE")
    deploy_core_model_quorum = _enabled(values, "DEPLOY_CORE_MODEL_QUORUM")
    deploy_executor = _enabled(values, "DEPLOY_ISOLATED_EXECUTOR")
    deploy_ohl = _enabled(values, "DEPLOY_OHL_SCALE_OUT_EVIDENCE_TARGET")
    promote_image = _enabled(values, "PROMOTE_RUNTIME_IMAGE")
    verify_effect = _enabled(values, "VERIFY_EXECUTOR_EFFECT")
    cutover = _enabled(values, "CUTOVER_ISOLATED_EXECUTOR_AUTHORITY")
    model_only = _enabled(values, "MODEL_BINDING_ONLY")
    validate_chatops = _enabled(values, "VALIDATE_CHATOPS_CHANNELS")
    design_mocks = _enabled(values, "DEPLOY_DESIGN_MOCKS")
    monitoring = _enabled(values, "DEPLOY_MONITORING")
    rca_reader_identity = _enabled(values, "RCA_READER_IDENTITY_ONLY")
    resume = _enabled(values, "RESUME_VERIFICATION")
    request_id = values.get("REQUEST_ID", "")
    context_digest = values.get("CONTEXT_DIGEST", "")
    runtime_image_revision = values.get("RUNTIME_IMAGE_REVISION", "")
    if deploy_console and _API_SCOPE.fullmatch(values.get("ENTRA_CONSOLE_API_SCOPE", "")) is None:
        raise ValueError(
            "ENTRA_CONSOLE_API_SCOPE must use api://<audience>/<scope> "
            "when deploy_console is enabled"
        )
    if re.fullmatch(r"(?:plan|apply)-(?:rca-)?[0-9a-f]{48}", request_id):
        if values.get("TARGET_ENVIRONMENT") == "prod":
            raise ValueError("fdaictl production deployment inputs are not implemented")
        _require_match(
            context_digest,
            _SHA64,
            "context_digest must be a lowercase SHA-256 digest",
        )
        actual_target = _target_binding(
            tenant_id=values.get("ACTUAL_TARGET_TENANT_ID", ""),
            subscription_id=values.get("ACTUAL_TARGET_SUBSCRIPTION_ID", ""),
        )
        request_mode = "resume" if resume else ("apply" if apply else "plan")
        expected_prefix = _request_binding_prefix(
            target_binding=actual_target,
            context_digest=context_digest,
            mode=request_mode,
            region=values.get("ACTUAL_TARGET_REGION", ""),
        )
        request_suffix = request_id.removeprefix("plan-").removeprefix("apply-")
        request_suffix = request_suffix.removeprefix("rca-")
        if request_suffix[:24] != expected_prefix:
            raise ValueError("repository Azure target does not match the approved profile")
        unsupported = (
            "DEPLOY_CORE_MODEL_QUORUM",
            "DEPLOY_DESIGN_MOCKS",
            "DEPLOY_OPERATOR_CHANNEL_EDGE",
            "DEPLOY_OHL_SCALE_OUT_EVIDENCE_TARGET",
            "CUTOVER_ISOLATED_EXECUTOR_AUTHORITY",
            "VERIFY_EXECUTOR_EFFECT",
            "MODEL_BINDING_ONLY",
            "VALIDATE_CHATOPS_CHANNELS",
        )
        if any(_enabled(values, key) for key in unsupported):
            raise ValueError("fdaictl request contains unsupported deployment inputs")
        image_rev = values.get("RUNTIME_IMAGE_REVISION", "")
        if image_rev and _SHA40.fullmatch(image_rev) is None:
            raise ValueError("runtime_image_revision MUST be a lowercase 40-character git SHA")
        if deploy_gateway and values.get("TARGET_ENVIRONMENT") != "dev":
            raise ValueError("deploy_dev_operations_gateway is restricted to the dev environment")
        if _deployment_context_digest(values) != context_digest:
            raise ValueError("deployment context does not match the selected workflow inputs")

    if validate_chatops and (
        values.get("TARGET_ENVIRONMENT") != "staging"
        or not _enabled(values, "DEPLOY_OPERATOR_API")
        or not _enabled(values, "DEPLOY_OPERATOR_CHANNEL_EDGE")
    ):
        raise ValueError(
            "ChatOps channel validation requires staging, deploy_operator_api, "
            "and deploy_operator_channel_edge"
        )

    if promote_image and not runtime_image_revision:
        raise ValueError("promote_runtime_image requires runtime_image_revision")
    if cutover and (not deploy_executor or not deploy_gateway):
        raise ValueError(
            "authority cutover requires deploy_isolated_executor and deploy_dev_operations_gateway"
        )
    if verify_effect and (not apply or not deploy_gateway):
        raise ValueError(
            "executor effect verification requires apply and deploy_dev_operations_gateway"
        )
    if resume and verify_effect:
        raise ValueError("executor effect verification cannot run during resume verification")
    if deploy_ohl and (values.get("TARGET_ENVIRONMENT") != "dev" or not deploy_gateway):
        raise ValueError(
            "the OHL scale-out evidence target requires dev and deploy_dev_operations_gateway"
        )
    if deploy_ohl and any(
        not values.get(key, "")
        for key in (
            "OHL_SCALE_OUT_EVIDENCE_CAMPAIGN_ID",
            "OHL_SCALE_OUT_EVIDENCE_IMAGE_VERSION",
            "OHL_SCALE_OUT_EVIDENCE_INITIATOR_PRINCIPAL_ID",
            "OHL_SCALE_OUT_EVIDENCE_SSH_PUBLIC_KEY",
        )
    ):
        raise ValueError(
            "the OHL scale-out evidence target requires campaign, initiator, "
            "exact image-version, and SSH-key repository variables"
        )
    if apply and promote_image:
        raise ValueError("runtime image promotion is not allowed during exact apply")
    if promote_image and not request_id:
        raise ValueError("runtime image promotion requires a protected plan request")

    targets = (
        "DEPLOY_CONSOLE",
        "DEPLOY_CORE_MODEL_QUORUM",
        "DEPLOY_OPERATOR_API",
        "DEPLOY_ISOLATED_EXECUTOR",
        "DEPLOY_DEV_OPERATIONS_GATEWAY",
        "DEPLOY_OHL_SCALE_OUT_EVIDENCE_TARGET",
        "DEPLOY_DOCUMENT_INGESTION",
        "DEPLOY_MONITORING",
    )
    if deploy_core_model_quorum:
        if values.get("TARGET_ENVIRONMENT") != "dev":
            raise ValueError("core model quorum deployment is restricted to dev")
        if not request_id:
            raise ValueError("core model quorum deployment requires a protected request")
        mixed = (
            "DEPLOY_CONSOLE",
            "DEPLOY_OPERATOR_API",
            "DEPLOY_ISOLATED_EXECUTOR",
            "DEPLOY_DEV_OPERATIONS_GATEWAY",
            "DEPLOY_OHL_SCALE_OUT_EVIDENCE_TARGET",
            "DEPLOY_DOCUMENT_INGESTION",
            "DEPLOY_MONITORING",
            "DEPLOY_DESIGN_MOCKS",
            "CUTOVER_ISOLATED_EXECUTOR_AUTHORITY",
            "PROMOTE_RUNTIME_IMAGE",
            "VERIFY_EXECUTOR_EFFECT",
            "MODEL_BINDING_ONLY",
        )
        if any(_enabled(values, key) for key in mixed) or values.get("RUNTIME_IMAGE_REVISION", ""):
            raise ValueError(
                "core model quorum deployment cannot be combined with another bounded operation"
            )
    if design_mocks:
        if values.get("TARGET_ENVIRONMENT") != "dev":
            raise ValueError("design-mocks deployment is restricted to the dev environment")
        if any(_enabled(values, key) for key in targets):
            raise ValueError(
                "deploy_design_mocks cannot be combined with another deployment target"
            )
    application_target = any(
        _enabled(values, key)
        for key in (
            "DEPLOY_CONSOLE",
            "DEPLOY_OPERATOR_API",
            "DEPLOY_ISOLATED_EXECUTOR",
            "DEPLOY_DEV_OPERATIONS_GATEWAY",
            "DEPLOY_OHL_SCALE_OUT_EVIDENCE_TARGET",
            "DEPLOY_DOCUMENT_INGESTION",
        )
    )
    if monitoring and not application_target and runtime_image_revision:
        raise ValueError("deploy_monitoring cannot be combined with another deployment target")

    if rca_reader_identity:
        mixed = targets
        if (
            any(_enabled(values, key) for key in mixed)
            or design_mocks
            or model_only
            or deploy_core_model_quorum
            or validate_chatops
            or runtime_image_revision
        ):
            raise ValueError(
                "deploy_rca_reader_identity cannot be combined with another deployment target"
            )

    if model_only:
        if not request_id:
            raise ValueError("model-binding deployment requires a protected request")
        mixed = (
            *targets,
            "DEPLOY_DESIGN_MOCKS",
            "CUTOVER_ISOLATED_EXECUTOR_AUTHORITY",
            "PROMOTE_RUNTIME_IMAGE",
            "VERIFY_EXECUTOR_EFFECT",
        )
        if any(_enabled(values, key) for key in mixed):
            raise ValueError(
                "model-binding deployment cannot be combined with another bounded operation"
            )

    if apply:
        _require_match(
            request_id,
            _APPLY_REQUEST,
            "apply request_id must be a bounded fdaictl id",
        )
        _require_match(
            values.get("CONTEXT_DIGEST", ""),
            _SHA64,
            "apply context_digest must be a lowercase SHA-256 digest",
        )
        _require_match(
            values.get("COMMIT_SHA", ""),
            _SHA40,
            "apply commit_sha must be a lowercase git SHA",
        )
        if values["COMMIT_SHA"] != checkout_commit:
            raise ValueError("requested apply commit does not match the workflow checkout")
        _require_match(values.get("PLAN_ID", ""), _PLAN_ID, "plan_id is invalid")
        _require_match(
            values.get("PLAN_DIGEST", ""),
            _SHA64,
            "plan_digest must be a lowercase SHA-256 digest",
        )
    elif request_id:
        _require_match(request_id, _PLAN_REQUEST, "request_id must be a bounded fdaictl plan id")
        _require_match(
            values.get("CONTEXT_DIGEST", ""),
            _SHA64,
            "context_digest must be a lowercase SHA-256 digest",
        )
        _require_match(
            values.get("COMMIT_SHA", ""),
            _SHA40,
            "commit_sha must be a lowercase git SHA",
        )
        if values["COMMIT_SHA"] != checkout_commit:
            raise ValueError("requested commit does not match the workflow checkout")
        if not values.get("DEPLOY_PREFLIGHT_INPUT_JSON", ""):
            raise ValueError("DEPLOY_PREFLIGHT_INPUT_JSON is required for protected plans")


def main() -> int:
    checkout = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    try:
        validate(os.environ, checkout_commit=checkout)
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    return 0


def _target_binding(*, tenant_id: str, subscription_id: str) -> str:
    if _GUID.fullmatch(tenant_id) is None or _GUID.fullmatch(subscription_id) is None:
        raise ValueError("repository Azure target is invalid")
    material = f"{tenant_id.lower()}:{subscription_id.lower()}".encode()
    return hashlib.sha256(material).hexdigest()


def _request_binding_prefix(
    *,
    target_binding: str,
    context_digest: str,
    mode: str,
    region: str,
) -> str:
    material = json.dumps(
        {
            "target_binding": target_binding,
            "context_digest": context_digest,
            "mode": mode,
            "region": region.casefold(),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(material).hexdigest()[:24]


def _deployment_context_digest(values: Mapping[str, str]) -> str:
    material = json.dumps(
        {
            "schema_version": "fdai.deployment-context.v1",
            "environment": values.get("TARGET_ENVIRONMENT", ""),
            "commit_sha": values.get("COMMIT_SHA", ""),
            "selection": {
                "deploy_console": _enabled(values, "DEPLOY_CONSOLE"),
                "deploy_dev_operations_gateway": _enabled(values, "DEPLOY_DEV_OPERATIONS_GATEWAY"),
                "deploy_document_ingestion": _enabled(values, "DEPLOY_DOCUMENT_INGESTION"),
                "deploy_isolated_executor": _enabled(values, "DEPLOY_ISOLATED_EXECUTOR"),
                "deploy_monitoring": _enabled(values, "DEPLOY_MONITORING"),
                "deploy_operator_api": _enabled(values, "DEPLOY_OPERATOR_API"),
                "deploy_rca_reader_identity": _enabled(values, "RCA_READER_IDENTITY_ONLY"),
                "runtime_image_revision": values.get("RUNTIME_IMAGE_REVISION", ""),
            },
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(material).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
