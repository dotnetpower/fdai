from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_PATH = _ROOT / "scripts/deployment/azure/validate_deploy_request.py"
_SPEC = importlib.util.spec_from_file_location("validate_deploy_request", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
validate = _MODULE.validate

_COMMIT = "a" * 40
_DIGEST = "b" * 64


def _request(**overrides: str) -> dict[str, str]:
    values = {
        "APPLY": "false",
        "TARGET_ENVIRONMENT": "dev",
        "DEPLOY_DEV_OPERATIONS_GATEWAY": "false",
        "DEPLOY_ISOLATED_EXECUTOR": "false",
        "DEPLOY_OHL_SCALE_OUT_EVIDENCE_TARGET": "false",
        "PROMOTE_RUNTIME_IMAGE": "false",
        "VERIFY_EXECUTOR_EFFECT": "false",
        "CUTOVER_ISOLATED_EXECUTOR_AUTHORITY": "false",
        "MODEL_BINDING_ONLY": "false",
        "RESUME_VERIFICATION": "false",
        "DEPLOY_DESIGN_MOCKS": "false",
        "DEPLOY_CONSOLE": "false",
        "DEPLOY_OPERATOR_API": "false",
        "DEPLOY_DOCUMENT_INGESTION": "false",
        "DEPLOY_MONITORING": "false",
        "REQUEST_ID": "",
        "CONTEXT_DIGEST": "",
        "COMMIT_SHA": "",
        "PLAN_ID": "",
        "PLAN_DIGEST": "",
    }
    values.update(overrides)
    return values


def test_unprotected_plan_request_is_valid() -> None:
    validate(_request(), checkout_commit=_COMMIT)


def test_protected_plan_request_is_bound_to_checkout_and_preflight() -> None:
    validate(
        _request(
            REQUEST_ID="plan-" + "c" * 24,
            CONTEXT_DIGEST=_DIGEST,
            COMMIT_SHA=_COMMIT,
            DEPLOY_PREFLIGHT_INPUT_JSON="{}",
        ),
        checkout_commit=_COMMIT,
    )


def test_exact_apply_request_is_bound_to_sealed_plan() -> None:
    validate(
        _request(
            APPLY="true",
            REQUEST_ID="apply-" + "c" * 24,
            CONTEXT_DIGEST=_DIGEST,
            COMMIT_SHA=_COMMIT,
            PLAN_ID="plan-123-1",
            PLAN_DIGEST=_DIGEST,
        ),
        checkout_commit=_COMMIT,
    )


def test_retired_event_bus_request_is_rejected() -> None:
    with pytest.raises(ValueError, match="bounded fdaictl plan id"):
        validate(
            _request(
                REQUEST_ID="plan-evh-" + "c" * 20,
                CONTEXT_DIGEST=_DIGEST,
                COMMIT_SHA=_COMMIT,
                DEPLOY_PREFLIGHT_INPUT_JSON="{}",
            ),
            checkout_commit=_COMMIT,
        )


def test_model_plan_requires_exact_policy_digest_and_no_other_target() -> None:
    policy = json.dumps({"environment": "dev", "revision": 1})
    canonical = json.dumps(json.loads(policy), separators=(",", ":"), sort_keys=True).encode()
    request_id = "plan-model-" + hashlib.sha256(canonical).hexdigest()

    validate(
        _request(
            MODEL_BINDING_ONLY="true",
            MODEL_BINDING_POLICY=policy,
            REQUEST_ID=request_id,
            CONTEXT_DIGEST=_DIGEST,
            COMMIT_SHA=_COMMIT,
            DEPLOY_PREFLIGHT_INPUT_JSON="{}",
        ),
        checkout_commit=_COMMIT,
    )
    with pytest.raises(ValueError, match="cannot be combined"):
        validate(
            _request(
                MODEL_BINDING_ONLY="true",
                MODEL_BINDING_POLICY=policy,
                REQUEST_ID=request_id,
                DEPLOY_CONSOLE="true",
            ),
            checkout_commit=_COMMIT,
        )


def test_design_mocks_are_dev_only_and_exclusive() -> None:
    validate(_request(DEPLOY_DESIGN_MOCKS="true"), checkout_commit=_COMMIT)
    with pytest.raises(ValueError, match="cannot be combined"):
        validate(
            _request(DEPLOY_DESIGN_MOCKS="true", DEPLOY_MONITORING="true"),
            checkout_commit=_COMMIT,
        )


def test_monitoring_is_exclusive() -> None:
    validate(_request(DEPLOY_MONITORING="true"), checkout_commit=_COMMIT)
    with pytest.raises(ValueError, match="deploy_monitoring cannot be combined"):
        validate(
            _request(DEPLOY_MONITORING="true", DEPLOY_OPERATOR_API="true"),
            checkout_commit=_COMMIT,
        )


def test_runtime_image_and_effect_requests_keep_authority_prerequisites() -> None:
    with pytest.raises(ValueError, match="requires deploy_isolated_executor"):
        validate(_request(PROMOTE_RUNTIME_IMAGE="true"), checkout_commit=_COMMIT)
    with pytest.raises(ValueError, match="requires apply"):
        validate(_request(VERIFY_EXECUTOR_EFFECT="true"), checkout_commit=_COMMIT)
    with pytest.raises(ValueError, match="cannot run during resume"):
        validate(
            _request(
                APPLY="true",
                RESUME_VERIFICATION="true",
                VERIFY_EXECUTOR_EFFECT="true",
                DEPLOY_DEV_OPERATIONS_GATEWAY="true",
            ),
            checkout_commit=_COMMIT,
        )


def test_ohl_target_requires_complete_dev_gateway_binding() -> None:
    with pytest.raises(ValueError, match="requires dev"):
        validate(
            _request(DEPLOY_OHL_SCALE_OUT_EVIDENCE_TARGET="true"),
            checkout_commit=_COMMIT,
        )


def test_boolean_inputs_are_strict() -> None:
    with pytest.raises(ValueError, match="APPLY must be true or false"):
        validate(_request(APPLY="yes"), checkout_commit=_COMMIT)
