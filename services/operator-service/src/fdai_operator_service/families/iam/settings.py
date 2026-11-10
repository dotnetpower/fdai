"""Model and runtime settings routes over revisioned request outboxes."""

from __future__ import annotations

import re
from datetime import UTC
from typing import Final

from fdai_operator_service.families.iam.capabilities import IamCapability, has_capability
from fdai_operator_service.families.iam.contracts import (
    AuthorizePrincipal,
    DocumentOcrPlanCommand,
    DocumentOcrPolicyCommand,
    ModelBindingDraftCommand,
    ModelBindingRequestCommand,
    ModelPreferenceCommand,
    ModelSettingsOutbox,
    RuntimeSettingsCommand,
    RuntimeSettingsOutbox,
    SlackWebhookTestCommand,
    SlackWebhookTester,
    TeamsA1OnboardingPlanCommand,
    TeamsWorkflowTestCommand,
    TeamsWorkflowTester,
    WebSearchSettingsCommand,
)
from fdai_operator_service.families.iam.errors import IamFamilyError
from fdai_operator_service.families.iam.http import (
    error_response,
    family_error,
    read_json_object,
    require_revision,
    require_string,
)
from fdai_operator_service.slack_webhook_diagnostics import (
    SlackWebhookTestConflictError,
    SlackWebhookTestProviderError,
)
from fdai_operator_service.teams_workflow_binding import TeamsWorkflowBindingError
from fdai_operator_service.teams_workflow_diagnostics import (
    TeamsWorkflowBindingUnavailableError,
    TeamsWorkflowTestConflictError,
    TeamsWorkflowTestProviderError,
)
from fdai_service_contracts import DocumentOcrPolicy, ModelBindingPolicy
from pydantic import ValidationError
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

_MAX_BODY_BYTES: Final = 16_000
_POLICY_DIGEST: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_ENVIRONMENT: Final = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_IDEMPOTENCY_KEY: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_NO_STORE_HEADERS: Final = {"cache-control": "no-store"}


def _include_model_catalog(request: Request) -> bool:
    view = request.query_params.get("view", "full")
    if view not in {"full", "summary"}:
        raise HTTPException(400, "model settings view MUST be full or summary")
    if view == "summary" and request.query_params.get("refresh_catalog") == "1":
        raise HTTPException(400, "catalog refresh requires the full model settings view")
    return view == "full"


def make_model_settings_routes(
    *, outbox: ModelSettingsOutbox | None, authorize: AuthorizePrincipal
) -> tuple[Route, ...]:
    """Build model settings routes that persist policy but never provision a model."""

    async def get_settings(request: Request) -> Response:
        principal = await authorize(request)
        if outbox is None:
            return error_response(503, "model settings outbox is not configured")
        include_catalog = _include_model_catalog(request)
        refresh_catalog = request.query_params.get("refresh_catalog") == "1"
        try:
            projection = await outbox.projection(
                principal.oid,
                can_manage_web_search=has_capability(
                    principal.roles, IamCapability.MANAGE_GROUP_MEMBERSHIP
                ),
                can_manage_model_bindings=has_capability(
                    principal.roles, IamCapability.MANAGE_MODEL_BINDINGS
                ),
                refresh_model_catalog=refresh_catalog,
                include_model_catalog=include_catalog,
            )
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(dict(projection), headers=_NO_STORE_HEADERS)

    async def put_binding_policy(request: Request) -> Response:
        principal = await authorize(request)
        if not has_capability(principal.roles, IamCapability.MANAGE_MODEL_BINDINGS):
            return error_response(403, "Owner role is required")
        if outbox is None:
            return error_response(503, "model settings outbox is not configured")
        body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
        _require_exact_fields(
            body,
            {"policy", "expected_revision", "idempotency_key"},
        )
        policy_raw = body.get("policy")
        if not isinstance(policy_raw, dict):
            return error_response(400, "policy MUST be an object")
        try:
            policy = ModelBindingPolicy.model_validate(policy_raw)
        except ValidationError as exc:
            return error_response(400, _validation_message(exc))
        expected_revision = require_revision(body)
        if policy.revision != expected_revision + 1:
            return error_response(400, "policy revision MUST advance expected_revision by one")
        idempotency_key = _idempotency_key(body)
        try:
            receipt = await outbox.save_binding_policy(
                ModelBindingDraftCommand(
                    actor_id=principal.oid,
                    policy=policy.model_dump(mode="json", exclude_none=True),
                    policy_digest=policy.digest(),
                    expected_revision=expected_revision,
                    idempotency_key=idempotency_key,
                )
            )
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(dict(receipt), headers=_NO_STORE_HEADERS)

    async def post_binding_assessment(request: Request) -> Response:
        return await _request_binding_operation(
            request,
            authorize=authorize,
            outbox=outbox,
            operation="assessment",
        )

    async def post_binding_plan(request: Request) -> Response:
        return await _request_binding_operation(
            request,
            authorize=authorize,
            outbox=outbox,
            operation="plan",
        )

    async def put_preference(request: Request) -> Response:
        principal = await authorize(request)
        if outbox is None:
            return error_response(503, "model settings outbox is not configured")
        include_catalog = _include_model_catalog(request)
        body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
        requested = body.get("preferred_narrator_model")
        if not isinstance(requested, str):
            return error_response(400, "preferred_narrator_model MUST be a string")
        try:
            await outbox.set_preference(
                ModelPreferenceCommand(
                    principal_id=principal.oid,
                    preferred_narrator_model=requested,
                    expected_revision=require_revision(body),
                )
            )
            projection = await outbox.projection(
                principal.oid,
                can_manage_web_search=has_capability(
                    principal.roles, IamCapability.MANAGE_GROUP_MEMBERSHIP
                ),
                can_manage_model_bindings=has_capability(
                    principal.roles, IamCapability.MANAGE_MODEL_BINDINGS
                ),
                include_model_catalog=include_catalog,
            )
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(dict(projection), headers=_NO_STORE_HEADERS)

    async def put_web_search(request: Request) -> Response:
        principal = await authorize(request)
        if not has_capability(principal.roles, IamCapability.MANAGE_GROUP_MEMBERSHIP):
            return error_response(403, "Owner role is required")
        if outbox is None:
            return error_response(503, "model settings outbox is not configured")
        include_catalog = _include_model_catalog(request)
        body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
        enabled = body.get("enabled")
        domains = body.get("allowed_domains")
        if not isinstance(enabled, bool):
            return error_response(400, "enabled MUST be a boolean")
        if not isinstance(domains, list) or not all(isinstance(item, str) for item in domains):
            return error_response(400, "allowed_domains MUST be a string array")
        try:
            normalized = _normalize_domains(tuple(domains))
            if enabled and not normalized:
                return error_response(
                    400, "allowed_domains MUST contain at least one host when enabled"
                )
            await outbox.set_web_search_settings(
                WebSearchSettingsCommand(
                    actor_id=principal.oid,
                    enabled=enabled,
                    allowed_domains=normalized,
                    expected_revision=require_revision(body),
                )
            )
            projection = await outbox.projection(
                principal.oid,
                can_manage_web_search=True,
                can_manage_model_bindings=has_capability(
                    principal.roles, IamCapability.MANAGE_MODEL_BINDINGS
                ),
                include_model_catalog=include_catalog,
            )
        except IamFamilyError as exc:
            return family_error(exc)
        except ValueError as exc:
            return error_response(400, str(exc))
        return JSONResponse(dict(projection), headers=_NO_STORE_HEADERS)

    async def put_document_ocr_policy(request: Request) -> Response:
        principal = await authorize(request)
        if not has_capability(principal.roles, IamCapability.MANAGE_MODEL_BINDINGS):
            return error_response(403, "Owner role is required")
        if outbox is None:
            return error_response(503, "model settings outbox is not configured")
        body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
        _require_exact_fields(
            body,
            {"policy", "expected_revision", "idempotency_key"},
        )
        policy_raw = body.get("policy")
        if not isinstance(policy_raw, dict):
            return error_response(400, "policy MUST be an object")
        try:
            policy = DocumentOcrPolicy.model_validate(policy_raw)
        except ValidationError as exc:
            return error_response(400, _validation_message(exc))
        expected_revision = require_revision(body)
        if policy.revision != expected_revision + 1:
            return error_response(400, "policy revision MUST advance expected_revision by one")
        command = DocumentOcrPolicyCommand(
            actor_id=principal.oid,
            policy=policy.model_dump(mode="json"),
            policy_digest=policy.digest(),
            expected_revision=expected_revision,
            idempotency_key=_idempotency_key(body),
        )
        try:
            receipt = await outbox.save_document_ocr_policy(command)
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(dict(receipt), status_code=202, headers=_NO_STORE_HEADERS)

    async def post_document_ocr_plan(request: Request) -> Response:
        principal = await authorize(request)
        if not has_capability(principal.roles, IamCapability.MANAGE_MODEL_BINDINGS):
            return error_response(403, "Owner role is required")
        if outbox is None:
            return error_response(503, "model settings outbox is not configured")
        body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
        _require_exact_fields(
            body,
            {"environment", "policy_revision", "policy_digest", "idempotency_key"},
        )
        environment = _bounded_string(body, "environment", maximum=32)
        if _ENVIRONMENT.fullmatch(environment) is None:
            return error_response(400, "environment MUST be dev, staging, or prod style")
        policy_digest = _bounded_string(body, "policy_digest", maximum=71)
        if _POLICY_DIGEST.fullmatch(policy_digest) is None:
            return error_response(400, "policy_digest MUST be a lowercase SHA-256 digest")
        policy_revision = body.get("policy_revision")
        if (
            not isinstance(policy_revision, int)
            or isinstance(policy_revision, bool)
            or policy_revision < 1
        ):
            return error_response(400, "policy_revision MUST be a positive integer")
        command = DocumentOcrPlanCommand(
            actor_id=principal.oid,
            environment=environment,
            policy_revision=policy_revision,
            policy_digest=policy_digest,
            idempotency_key=_idempotency_key(body),
        )
        try:
            receipt = await outbox.request_document_ocr_plan(command)
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(dict(receipt), status_code=202, headers=_NO_STORE_HEADERS)

    return (
        Route("/models/settings", get_settings, methods=["GET"]),
        Route("/models/binding-policy", put_binding_policy, methods=["PUT"]),
        Route(
            "/models/binding-policy/assess",
            post_binding_assessment,
            methods=["POST"],
        ),
        Route("/models/binding-policy/plan", post_binding_plan, methods=["POST"]),
        Route("/models/web-search-settings", put_web_search, methods=["PUT"]),
        Route("/models/document-ocr-policy", put_document_ocr_policy, methods=["PUT"]),
        Route("/models/document-ocr-policy/plan", post_document_ocr_plan, methods=["POST"]),
        Route("/me/model-preferences", put_preference, methods=["PUT"]),
    )


async def _request_binding_operation(
    request: Request,
    *,
    authorize: AuthorizePrincipal,
    outbox: ModelSettingsOutbox | None,
    operation: str,
) -> Response:
    principal = await authorize(request)
    if not has_capability(principal.roles, IamCapability.MANAGE_MODEL_BINDINGS):
        return error_response(403, "Owner role is required")
    if outbox is None:
        return error_response(503, "model settings outbox is not configured")
    body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
    _require_exact_fields(
        body,
        {"environment", "policy_revision", "policy_digest", "idempotency_key"},
    )
    environment = _bounded_string(body, "environment", maximum=32)
    if _ENVIRONMENT.fullmatch(environment) is None:
        return error_response(400, "environment MUST be dev, staging, or prod style")
    policy_digest = _bounded_string(body, "policy_digest", maximum=71)
    if _POLICY_DIGEST.fullmatch(policy_digest) is None:
        return error_response(400, "policy_digest MUST be a lowercase SHA-256 digest")
    idempotency_key = _idempotency_key(body)
    policy_revision = body.get("policy_revision")
    if (
        not isinstance(policy_revision, int)
        or isinstance(policy_revision, bool)
        or policy_revision < 1
    ):
        return error_response(400, "policy_revision MUST be a positive integer")
    command = ModelBindingRequestCommand(
        actor_id=principal.oid,
        environment=environment,
        policy_revision=policy_revision,
        policy_digest=policy_digest,
        idempotency_key=idempotency_key,
    )
    try:
        receipt = (
            await outbox.request_binding_assessment(command)
            if operation == "assessment"
            else await outbox.request_binding_plan(command)
        )
    except IamFamilyError as exc:
        return family_error(exc)
    return JSONResponse(dict(receipt), status_code=202, headers=_NO_STORE_HEADERS)


def _bounded_string(body: dict[str, object], key: str, *, maximum: int) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise HTTPException(status_code=400, detail=f"{key} MUST be a bounded non-empty string")
    return value.strip()


def _idempotency_key(body: dict[str, object]) -> str:
    value = _bounded_string(body, "idempotency_key", maximum=256)
    if _IDEMPOTENCY_KEY.fullmatch(value) is None:
        raise HTTPException(
            status_code=400,
            detail="idempotency_key MUST use bounded ASCII identifier characters",
        )
    return value


def _require_exact_fields(body: dict[str, object], expected: set[str]) -> None:
    unknown = sorted(set(body) - expected)
    missing = sorted(expected - set(body))
    if unknown or missing:
        raise HTTPException(
            status_code=400,
            detail=f"request fields do not match contract: missing={missing}, unknown={unknown}",
        )


def _validation_message(exc: ValidationError) -> str:
    first = exc.errors()[0]
    location = ".".join(str(part) for part in first.get("loc", ())) or "policy"
    return f"{location}: {first.get('msg', 'invalid model binding policy')}"


def make_runtime_settings_routes(
    *,
    outbox: RuntimeSettingsOutbox | None,
    authorize: AuthorizePrincipal,
    teams_workflow_tester: TeamsWorkflowTester | None = None,
    slack_webhook_tester: SlackWebhookTester | None = None,
) -> tuple[Route, ...]:
    """Build runtime policy routes that stop at audited durable overrides."""

    async def get_settings(request: Request) -> Response:
        principal = await authorize(request)
        if outbox is None:
            return error_response(503, "runtime settings outbox is not configured")
        try:
            projection = await outbox.projection(
                can_manage=has_capability(principal.roles, IamCapability.MANAGE_RUNTIME_SETTINGS)
            )
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(dict(projection))

    async def put_settings(request: Request) -> Response:
        principal = await authorize(request)
        if not has_capability(principal.roles, IamCapability.MANAGE_RUNTIME_SETTINGS):
            return error_response(403, "Owner role is required")
        if outbox is None:
            return error_response(503, "runtime settings outbox is not configured")
        body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
        changes = body.get("changes")
        if not isinstance(changes, dict):
            return error_response(400, "changes MUST be an object")
        try:
            await outbox.update(
                RuntimeSettingsCommand(
                    actor_id=principal.oid,
                    changes=changes,
                    expected_revision=require_revision(body),
                )
            )
            projection = await outbox.projection(can_manage=True)
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(dict(projection))

    async def request_teams_a1_plan(request: Request) -> Response:
        principal = await authorize(request)
        if not has_capability(principal.roles, IamCapability.MANAGE_RUNTIME_SETTINGS):
            return error_response(403, "Owner role is required")
        if outbox is None:
            return error_response(503, "runtime settings outbox is not configured")
        body = await read_json_object(request, maximum=4 * 1024)
        _require_exact_fields(body, {"environment", "idempotency_key"})
        environment = require_string(body, "environment")
        if _ENVIRONMENT.fullmatch(environment) is None:
            return error_response(400, "environment is invalid")
        try:
            receipt = await outbox.request_teams_a1_plan(
                TeamsA1OnboardingPlanCommand(
                    actor_id=principal.oid,
                    environment=environment,
                    idempotency_key=_idempotency_key(body),
                )
            )
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(dict(receipt), headers=_NO_STORE_HEADERS)

    async def test_teams_workflow(request: Request) -> Response:
        principal = await authorize(request)
        if not has_capability(principal.roles, IamCapability.MANAGE_RUNTIME_SETTINGS):
            return error_response(403, "Owner role is required")
        if teams_workflow_tester is None:
            return error_response(
                503,
                "Teams Workflow diagnostics require the authoritative Operator store",
            )
        body = await read_json_object(request, maximum=8 * 1024)
        allowed_fields = {
            "request_id",
            "webhook_url",
            "channel_label",
            "selected_channel_ids",
            "delivery_targets",
            "remove_channel_id",
            "rename_channel_id",
            "test_channel_id",
            "email_recipient_mode",
            "custom_email",
            "selection_only",
            "clear_binding",
            "test_email",
        }
        unknown = sorted(set(body) - allowed_fields)
        missing = sorted({"request_id", "webhook_url"} - set(body))
        if unknown or missing:
            return error_response(
                400,
                f"request fields do not match contract: missing={missing}, unknown={unknown}",
            )
        raw_label = body.get("channel_label")
        if raw_label is not None and (not isinstance(raw_label, str) or len(raw_label) > 80):
            return error_response(400, "channel_label MUST be a bounded string")
        raw_selected = body.get("selected_channel_ids")
        if raw_selected is not None and (
            not isinstance(raw_selected, list)
            or len(raw_selected) > 32
            or any(not isinstance(item, str) or not item.strip() for item in raw_selected)
        ):
            return error_response(400, "selected_channel_ids MUST be a bounded string list")
        raw_targets = body.get("delivery_targets")
        if raw_targets is not None and (
            not isinstance(raw_targets, list)
            or len(raw_targets) > 16
            or any(not isinstance(item, str) or not item.strip() for item in raw_targets)
        ):
            return error_response(400, "delivery_targets MUST be a bounded string list")
        raw_remove = body.get("remove_channel_id")
        if raw_remove is not None and (not isinstance(raw_remove, str) or not raw_remove.strip()):
            return error_response(400, "remove_channel_id MUST be a non-empty string")
        raw_rename = body.get("rename_channel_id")
        if raw_rename is not None and (not isinstance(raw_rename, str) or not raw_rename.strip()):
            return error_response(400, "rename_channel_id MUST be a non-empty string")
        raw_test_ch = body.get("test_channel_id")
        if raw_test_ch is not None and (
            not isinstance(raw_test_ch, str) or not raw_test_ch.strip()
        ):
            return error_response(400, "test_channel_id MUST be a non-empty string")
        raw_email_mode = body.get("email_recipient_mode")
        if raw_email_mode is not None and raw_email_mode not in {"login", "custom"}:
            return error_response(400, "email_recipient_mode MUST be login or custom")
        raw_custom_email = body.get("custom_email")
        if raw_custom_email is not None and (
            not isinstance(raw_custom_email, str) or len(raw_custom_email) > 254
        ):
            return error_response(400, "custom_email MUST be a bounded string")
        raw_selection_only = body.get("selection_only", False)
        if not isinstance(raw_selection_only, bool):
            return error_response(400, "selection_only MUST be a boolean")
        raw_clear_binding = body.get("clear_binding", False)
        if not isinstance(raw_clear_binding, bool):
            return error_response(400, "clear_binding MUST be a boolean")
        raw_test_email = body.get("test_email", False)
        if not isinstance(raw_test_email, bool):
            return error_response(400, "test_email MUST be a boolean")
        try:
            result = await teams_workflow_tester.save_and_test(
                TeamsWorkflowTestCommand(
                    actor_id=principal.oid,
                    request_id=require_string(body, "request_id"),
                    webhook_url=require_string(body, "webhook_url"),
                    channel_label=raw_label.strip() if isinstance(raw_label, str) else None,
                    selected_channel_ids=(
                        tuple(item.strip() for item in raw_selected)
                        if isinstance(raw_selected, list)
                        else None
                    ),
                    delivery_targets=(
                        tuple(item.strip() for item in raw_targets)
                        if isinstance(raw_targets, list)
                        else None
                    ),
                    remove_channel_id=raw_remove.strip() if isinstance(raw_remove, str) else None,
                    rename_channel_id=raw_rename.strip() if isinstance(raw_rename, str) else None,
                    test_channel_id=raw_test_ch.strip() if isinstance(raw_test_ch, str) else None,
                    email_recipient_mode=(
                        raw_email_mode if isinstance(raw_email_mode, str) else None
                    ),
                    custom_email=(
                        raw_custom_email.strip() if isinstance(raw_custom_email, str) else None
                    ),
                    selection_only=raw_selection_only,
                    clear_binding=raw_clear_binding,
                    test_email=raw_test_email,
                )
            )
        except ValueError as exc:
            return error_response(400, str(exc), kind="invalid_webhook_url")
        except TeamsWorkflowBindingUnavailableError as exc:
            return error_response(503, str(exc), kind="binding_unavailable")
        except TeamsWorkflowBindingError as exc:
            return error_response(502, str(exc), kind="binding_provider_error")
        except TeamsWorkflowTestConflictError as exc:
            return error_response(409, str(exc), kind="request_conflict")
        except TeamsWorkflowTestProviderError as exc:
            return error_response(502, str(exc), kind="provider_error")
        return JSONResponse(
            {
                "request_id": result.request_id,
                "saved": result.saved,
                "binding_version": result.binding_version,
                "saved_at": result.saved_at.astimezone(UTC).isoformat(),
                "accepted": result.accepted,
                "provider_status": result.provider_status,
                "workflow_run_id": result.workflow_run_id,
                "tested_at": result.tested_at.astimezone(UTC).isoformat(),
            }
        )

    async def get_teams_workflow_binding(request: Request) -> Response:
        principal = await authorize(request)
        reveal = request.query_params.get("reveal") == "1"
        if not has_capability(
            principal.roles,
            IamCapability.VIEW_INTEGRATION_SECRETS,
        ):
            if reveal:
                return error_response(
                    403,
                    "Contributor, Approver, or Owner role is required",
                )
            return JSONResponse({"visible": False}, headers=_NO_STORE_HEADERS)
        if teams_workflow_tester is None:
            if not reveal:
                return JSONResponse(
                    {
                        "visible": True,
                        "configured": False,
                        "storage_available": False,
                    },
                    headers=_NO_STORE_HEADERS,
                )
            return error_response(
                503,
                "Teams Workflow binding storage is not configured",
                kind="binding_unavailable",
            )
        channel_id = request.query_params.get("channel_id")
        if channel_id is not None and re.fullmatch(r"^ch-[a-z0-9]{1,32}$", channel_id) is None:
            return error_response(400, "channel_id is invalid", kind="invalid_channel_id")
        try:
            if reveal:
                binding = (
                    await teams_workflow_tester.reveal_binding(
                        actor_id=principal.oid,
                        channel_id=channel_id,
                    )
                    if channel_id
                    else await teams_workflow_tester.reveal_binding(actor_id=principal.oid)
                )
            else:
                binding = await teams_workflow_tester.describe_binding(actor_id=principal.oid)
        except ValueError as exc:
            return error_response(400, str(exc), kind="invalid_channel_id")
        except TeamsWorkflowBindingUnavailableError as exc:
            if not reveal:
                return JSONResponse(
                    {
                        "visible": True,
                        "configured": False,
                        "storage_available": False,
                    },
                    headers=_NO_STORE_HEADERS,
                )
            return error_response(503, str(exc), kind="binding_unavailable")
        except TeamsWorkflowBindingError as exc:
            return error_response(502, str(exc), kind="binding_provider_error")
        if binding is None:
            return JSONResponse(
                {"visible": True, "configured": False},
                headers=_NO_STORE_HEADERS,
            )
        return JSONResponse(
            {
                "visible": True,
                "configured": True,
                **binding,
            },
            headers=_NO_STORE_HEADERS,
        )

    async def test_slack_webhook(request: Request) -> Response:
        principal = await authorize(request)
        if not has_capability(principal.roles, IamCapability.MANAGE_RUNTIME_SETTINGS):
            return error_response(403, "Owner role is required")
        if slack_webhook_tester is None:
            return error_response(
                503,
                "Slack webhook diagnostics require the authoritative Operator store",
            )
        body = await read_json_object(request, maximum=8 * 1024)
        _require_exact_fields(body, {"request_id", "webhook_url"})
        try:
            result = await slack_webhook_tester.test(
                SlackWebhookTestCommand(
                    actor_id=principal.oid,
                    request_id=require_string(body, "request_id"),
                    webhook_url=require_string(body, "webhook_url"),
                )
            )
        except ValueError as exc:
            return error_response(400, str(exc), kind="invalid_webhook_url")
        except SlackWebhookTestConflictError as exc:
            return error_response(409, str(exc), kind="request_conflict")
        except SlackWebhookTestProviderError as exc:
            return error_response(502, str(exc), kind="provider_error")
        return JSONResponse(
            {
                "request_id": result.request_id,
                "accepted": result.accepted,
                "provider_status": result.provider_status,
                "tested_at": result.tested_at.astimezone(UTC).isoformat(),
            }
        )

    return (
        Route("/runtime/settings", get_settings, methods=["GET"]),
        Route("/runtime/settings", put_settings, methods=["PUT"]),
        Route(
            "/runtime/integrations/teams-a1/plan",
            request_teams_a1_plan,
            methods=["POST"],
            name="request_teams_a1_plan",
        ),
        Route(
            "/runtime/integrations/teams-workflow/binding",
            get_teams_workflow_binding,
            methods=["GET"],
            name="get_teams_workflow_binding",
        ),
        Route(
            "/runtime/integrations/teams-workflow/test",
            test_teams_workflow,
            methods=["POST"],
            name="test_teams_workflow",
        ),
        Route(
            "/runtime/integrations/slack-webhook/test",
            test_slack_webhook,
            methods=["POST"],
            name="test_slack_webhook",
        ),
    )


def _normalize_domains(domains: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(
        dict.fromkeys(item.strip().casefold().rstrip(".") for item in domains if item.strip())
    )
    if len(normalized) > 100:
        raise ValueError("allowed_domains MUST contain at most 100 hosts")
    if any(not _valid_domain(domain) for domain in normalized):
        raise ValueError(
            "allowed_domains MUST contain hosts without schemes, paths, ports, or wildcards"
        )
    return normalized


def _valid_domain(domain: str) -> bool:
    if (
        len(domain) > 253
        or "." not in domain
        or any(token in domain for token in ("://", "/", ":", "*"))
    ):
        return False
    return all(
        bool(label)
        and len(label) <= 63
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(character.isalnum() or character == "-" for character in label)
        for label in domain.split(".")
    )


__all__ = ["make_model_settings_routes", "make_runtime_settings_routes"]
