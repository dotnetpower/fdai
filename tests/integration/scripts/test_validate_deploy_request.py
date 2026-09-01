from __future__ import annotations

import hashlib
import importlib.util
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
_TENANT = "00000000-0000-0000-0000-000000000000"
_SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
_TARGET_BINDING = hashlib.sha256(f"{_TENANT}:{_SUBSCRIPTION}".encode()).hexdigest()
_CONTEXT = hashlib.sha256(
    (
        '{"commit_sha":"' + _COMMIT + '","environment":"dev",'
        '"schema_version":"fdai.deployment-context.v1","selection":'
        '{"deploy_console":false,"deploy_dev_operations_gateway":false,'
        '"deploy_document_ingestion":false,'
        '"deploy_isolated_executor":false,"deploy_monitoring":false,'
        '"deploy_operator_api":false,"runtime_image_revision":""}}'
    ).encode()
).hexdigest()


def _bound_request(mode: str) -> str:
    prefix = _MODULE._request_binding_prefix(
        target_binding=_TARGET_BINDING,
        context_digest=_CONTEXT,
        mode=mode,
        region="koreacentral",
    )
    wire_prefix = "apply" if mode in {"apply", "resume"} else "plan"
    return f"{wire_prefix}-{prefix}{'abcd' * 5}0001"


def _request(**overrides: str) -> dict[str, str]:
    values = {
        "APPLY": "false",
        "TARGET_ENVIRONMENT": "dev",
        "DEPLOY_DEV_OPERATIONS_GATEWAY": "false",
        "DEPLOY_CORE_MODEL_QUORUM": "false",
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
        "DEPLOY_OPERATOR_CHANNEL_EDGE": "false",
        "VALIDATE_CHATOPS_CHANNELS": "false",
        "DEPLOY_DOCUMENT_INGESTION": "false",
        "DEPLOY_MONITORING": "false",
        "RUNTIME_IMAGE_REVISION": "",
        "REQUEST_ID": "",
        "CONTEXT_DIGEST": "",
        "COMMIT_SHA": "",
        "PLAN_ID": "",
        "PLAN_DIGEST": "",
        "ACTUAL_TARGET_TENANT_ID": _TENANT,
        "ACTUAL_TARGET_SUBSCRIPTION_ID": _SUBSCRIPTION,
        "ACTUAL_TARGET_REGION": "koreacentral",
    }
    values.update(overrides)
    return values


def test_unprotected_plan_request_is_valid() -> None:
    validate(_request(), checkout_commit=_COMMIT)


def test_protected_plan_request_is_bound_to_checkout_and_preflight() -> None:
    validate(
        _request(
            REQUEST_ID=_bound_request("plan"),
            CONTEXT_DIGEST=_CONTEXT,
            COMMIT_SHA=_COMMIT,
            DEPLOY_PREFLIGHT_INPUT_JSON="{}",
        ),
        checkout_commit=_COMMIT,
    )


def test_exact_apply_request_is_bound_to_sealed_plan() -> None:
    validate(
        _request(
            APPLY="true",
            REQUEST_ID=_bound_request("apply"),
            CONTEXT_DIGEST=_CONTEXT,
            COMMIT_SHA=_COMMIT,
            PLAN_ID="plan-123-1",
            PLAN_DIGEST=_DIGEST,
        ),
        checkout_commit=_COMMIT,
    )


def test_protected_request_rejects_repository_target_mismatch() -> None:
    with pytest.raises(ValueError, match="does not match"):
        validate(
            _request(
                REQUEST_ID=_bound_request("plan"),
                CONTEXT_DIGEST=_CONTEXT,
                COMMIT_SHA=_COMMIT,
                DEPLOY_PREFLIGHT_INPUT_JSON="{}",
                ACTUAL_TARGET_SUBSCRIPTION_ID="00000000-0000-0000-0000-000000000002",
            ),
            checkout_commit=_COMMIT,
        )


def test_protected_request_rejects_repository_region_mismatch() -> None:
    with pytest.raises(ValueError, match="does not match"):
        validate(
            _request(
                REQUEST_ID=_bound_request("plan"),
                CONTEXT_DIGEST=_CONTEXT,
                COMMIT_SHA=_COMMIT,
                DEPLOY_PREFLIGHT_INPUT_JSON="{}",
                ACTUAL_TARGET_REGION="westus3",
            ),
            checkout_commit=_COMMIT,
        )


def test_protected_request_rejects_selection_outside_the_context() -> None:
    with pytest.raises(ValueError, match="does not match the selected"):
        validate(
            _request(
                REQUEST_ID=_bound_request("plan"),
                CONTEXT_DIGEST=_CONTEXT,
                COMMIT_SHA=_COMMIT,
                DEPLOY_PREFLIGHT_INPUT_JSON="{}",
                DEPLOY_CONSOLE="true",
            ),
            checkout_commit=_COMMIT,
        )


def test_fdaictl_request_rejects_unbound_production_inputs() -> None:
    with pytest.raises(ValueError, match="production deployment inputs"):
        validate(
            _request(
                TARGET_ENVIRONMENT="prod",
                REQUEST_ID=_bound_request("plan"),
                CONTEXT_DIGEST=_CONTEXT,
                COMMIT_SHA=_COMMIT,
                DEPLOY_PREFLIGHT_INPUT_JSON="{}",
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


def test_model_plan_requires_exact_proposal_and_no_other_target() -> None:
    request_id = "plan-model-" + "e" * 32 + "-" + "d" * 64

    validate(
        _request(
            MODEL_BINDING_ONLY="true",
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
                REQUEST_ID=request_id,
                DEPLOY_CONSOLE="true",
            ),
            checkout_commit=_COMMIT,
        )
    with pytest.raises(ValueError, match="bounded fdaictl plan id"):
        validate(
            _request(
                MODEL_BINDING_ONLY="true",
                REQUEST_ID="plan-model-" + "d" * 64,
                CONTEXT_DIGEST=_DIGEST,
                COMMIT_SHA=_COMMIT,
                DEPLOY_PREFLIGHT_INPUT_JSON="{}",
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


def test_core_model_quorum_is_dev_only_protected_and_exclusive() -> None:
    protected = {
        "DEPLOY_CORE_MODEL_QUORUM": "true",
        "REQUEST_ID": "plan-quorum-" + "c" * 24,
        "CONTEXT_DIGEST": _DIGEST,
        "COMMIT_SHA": _COMMIT,
        "DEPLOY_PREFLIGHT_INPUT_JSON": "{}",
    }
    validate(_request(**protected), checkout_commit=_COMMIT)

    with pytest.raises(ValueError, match="restricted to dev"):
        validate(
            _request(**protected, TARGET_ENVIRONMENT="staging"),
            checkout_commit=_COMMIT,
        )
    with pytest.raises(ValueError, match="requires a protected request"):
        validate(
            _request(DEPLOY_CORE_MODEL_QUORUM="true"),
            checkout_commit=_COMMIT,
        )
    with pytest.raises(ValueError, match="cannot be combined"):
        validate(
            _request(**protected, DEPLOY_OPERATOR_API="true"),
            checkout_commit=_COMMIT,
        )


def test_chatops_validation_requires_staging_operator_surfaces() -> None:
    validate(
        _request(
            TARGET_ENVIRONMENT="staging",
            DEPLOY_OPERATOR_API="true",
            DEPLOY_OPERATOR_CHANNEL_EDGE="true",
            VALIDATE_CHATOPS_CHANNELS="true",
        ),
        checkout_commit=_COMMIT,
    )

    for overrides in (
        {"TARGET_ENVIRONMENT": "dev"},
        {"DEPLOY_OPERATOR_API": "false"},
        {"DEPLOY_OPERATOR_CHANNEL_EDGE": "false"},
    ):
        request = {
            "TARGET_ENVIRONMENT": "staging",
            "DEPLOY_OPERATOR_API": "true",
            "DEPLOY_OPERATOR_CHANNEL_EDGE": "true",
            "VALIDATE_CHATOPS_CHANNELS": "true",
        }
        request.update(overrides)
        with pytest.raises(ValueError, match="ChatOps channel validation requires"):
            validate(
                _request(**request),
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


# -- Gateway selection via fdaictl --


def _gateway_context() -> str:
    return hashlib.sha256(
        (
            '{"commit_sha":"' + _COMMIT + '","environment":"dev",'
            '"schema_version":"fdai.deployment-context.v1","selection":'
            '{"deploy_console":false,"deploy_dev_operations_gateway":true,'
            '"deploy_document_ingestion":false,'
            '"deploy_isolated_executor":false,"deploy_monitoring":false,'
            '"deploy_operator_api":false,"runtime_image_revision":""}}'
        ).encode()
    ).hexdigest()


def _gateway_bound_request(mode: str) -> str:
    ctx = _gateway_context()
    prefix = _MODULE._request_binding_prefix(
        target_binding=_TARGET_BINDING,
        context_digest=ctx,
        mode=mode,
        region="koreacentral",
    )
    wire_prefix = "apply" if mode in {"apply", "resume"} else "plan"
    return f"{wire_prefix}-{prefix}{'abcd' * 5}0001"


def test_fdaictl_gateway_plan_round_trip() -> None:
    """Protected plan with gateway selection produces a valid context digest."""
    ctx = _gateway_context()
    validate(
        _request(
            REQUEST_ID=_gateway_bound_request("plan"),
            CONTEXT_DIGEST=ctx,
            COMMIT_SHA=_COMMIT,
            DEPLOY_DEV_OPERATIONS_GATEWAY="true",
            DEPLOY_PREFLIGHT_INPUT_JSON="{}",
        ),
        checkout_commit=_COMMIT,
    )


def test_fdaictl_gateway_rejects_non_dev_environment() -> None:
    """Gateway via fdaictl is restricted to dev."""
    ctx = _gateway_context()
    with pytest.raises(ValueError, match="restricted to the dev environment"):
        validate(
            _request(
                TARGET_ENVIRONMENT="staging",
                REQUEST_ID=_gateway_bound_request("plan"),
                CONTEXT_DIGEST=ctx,
                COMMIT_SHA=_COMMIT,
                DEPLOY_DEV_OPERATIONS_GATEWAY="true",
                DEPLOY_PREFLIGHT_INPUT_JSON="{}",
            ),
            checkout_commit=_COMMIT,
        )


# -- Runtime image revision via fdaictl --

_IMAGE_REVISION = "24e4df68a50eed8cf355c8278836d40dc399cb54"


def _executor_context(*, image_revision: str = _IMAGE_REVISION) -> str:
    return hashlib.sha256(
        (
            '{"commit_sha":"' + _COMMIT + '","environment":"dev",'
            '"schema_version":"fdai.deployment-context.v1","selection":'
            '{"deploy_console":false,"deploy_dev_operations_gateway":false,'
            '"deploy_document_ingestion":false,'
            '"deploy_isolated_executor":true,"deploy_monitoring":false,'
            '"deploy_operator_api":false,"runtime_image_revision":"' + image_revision + '"}}'
        ).encode()
    ).hexdigest()


def _executor_bound_request(mode: str, ctx: str) -> str:
    prefix = _MODULE._request_binding_prefix(
        target_binding=_TARGET_BINDING,
        context_digest=ctx,
        mode=mode,
        region="koreacentral",
    )
    wire_prefix = "apply" if mode in {"apply", "resume"} else "plan"
    return f"{wire_prefix}-{prefix}{'abcd' * 5}0001"


def test_fdaictl_runtime_image_revision_plan_apply_parity() -> None:
    """Plan and apply with runtime_image_revision share the same context digest."""
    ctx = _executor_context()
    plan_id = _executor_bound_request("plan", ctx)
    apply_id = _executor_bound_request("apply", ctx)
    validate(
        _request(
            REQUEST_ID=plan_id,
            CONTEXT_DIGEST=ctx,
            COMMIT_SHA=_COMMIT,
            DEPLOY_ISOLATED_EXECUTOR="true",
            RUNTIME_IMAGE_REVISION=_IMAGE_REVISION,
            DEPLOY_PREFLIGHT_INPUT_JSON="{}",
        ),
        checkout_commit=_COMMIT,
    )
    validate(
        _request(
            APPLY="true",
            REQUEST_ID=apply_id,
            CONTEXT_DIGEST=ctx,
            COMMIT_SHA=_COMMIT,
            PLAN_ID="plan-1-1",
            PLAN_DIGEST="b" * 64,
            DEPLOY_ISOLATED_EXECUTOR="true",
            RUNTIME_IMAGE_REVISION=_IMAGE_REVISION,
        ),
        checkout_commit=_COMMIT,
    )


def test_fdaictl_runtime_image_revision_digest_drift() -> None:
    """Changing the image revision changes the context digest."""
    ctx_with = _executor_context(image_revision=_IMAGE_REVISION)
    ctx_without = _executor_context(image_revision="")
    assert ctx_with != ctx_without
    with pytest.raises(ValueError, match="does not match the selected"):
        validate(
            _request(
                REQUEST_ID=_executor_bound_request("plan", ctx_without),
                CONTEXT_DIGEST=ctx_without,
                COMMIT_SHA=_COMMIT,
                DEPLOY_ISOLATED_EXECUTOR="true",
                RUNTIME_IMAGE_REVISION=_IMAGE_REVISION,
                DEPLOY_PREFLIGHT_INPUT_JSON="{}",
            ),
            checkout_commit=_COMMIT,
        )


def test_fdaictl_runtime_image_revision_requires_executor() -> None:
    """runtime_image_revision without executor is rejected."""
    with pytest.raises(ValueError, match="requires deploy_isolated_executor"):
        validate(
            _request(RUNTIME_IMAGE_REVISION=_IMAGE_REVISION),
            checkout_commit=_COMMIT,
        )


def test_fdaictl_runtime_image_revision_invalid_sha() -> None:
    """Non-40-char SHA is rejected by the fdaictl validator."""
    bad_ctx = _executor_context(image_revision="not-a-sha")
    with pytest.raises(ValueError, match="lowercase 40-character git SHA"):
        validate(
            _request(
                REQUEST_ID=_executor_bound_request("plan", bad_ctx),
                CONTEXT_DIGEST=bad_ctx,
                COMMIT_SHA=_COMMIT,
                DEPLOY_ISOLATED_EXECUTOR="true",
                RUNTIME_IMAGE_REVISION="not-a-sha",
                DEPLOY_PREFLIGHT_INPUT_JSON="{}",
            ),
            checkout_commit=_COMMIT,
        )
