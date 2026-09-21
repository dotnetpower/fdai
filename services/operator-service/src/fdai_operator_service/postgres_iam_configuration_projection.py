"""Validate and render inert IAM-backed runtime configuration projections."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime

from fdai_service_contracts import DocumentOcrPolicy, ModelBindingPolicy
from pydantic import ValidationError

from fdai_operator_service.families.iam.contracts import (
    JsonMapping,
    ModelBindingDraftCommand,
    ModelBindingRequestCommand,
    RuntimeSettingsCommand,
)
from fdai_operator_service.families.iam.errors import (
    IamConflictError,
    IamNotFoundError,
    IamUnavailableError,
)
from fdai_operator_service.postgres_family_store import StoredProposal


def runtime_settings_state(
    base_projection: Mapping[str, object],
    current: Mapping[str, object] | None,
    command: RuntimeSettingsCommand,
) -> dict[str, object]:
    projected = runtime_settings_projection(base_projection, current)
    if projected.get("revision") != command.expected_revision:
        raise IamConflictError("runtime settings revision mismatch")
    raw_settings = projected.get("settings")
    if not isinstance(raw_settings, list):
        raise IamUnavailableError("runtime settings projection has no settings")
    settings = {
        str(setting.get("key")): setting
        for setting in raw_settings
        if isinstance(setting, Mapping) and isinstance(setting.get("key"), str)
    }
    raw_overrides = current.get("overrides") if current is not None else None
    if raw_overrides is not None and not isinstance(raw_overrides, Mapping):
        raise IamUnavailableError("stored runtime settings overrides are malformed")
    overrides = dict(raw_overrides) if isinstance(raw_overrides, Mapping) else {}
    if not command.changes:
        raise ValueError("runtime settings changes MUST NOT be empty")
    for key, value in command.changes.items():
        setting = settings.get(key)
        if setting is None:
            raise ValueError(f"unknown runtime setting: {key}")
        if value is None:
            overrides.pop(key, None)
        else:
            overrides[key] = validate_runtime_setting_value(setting, value)
    return {
        "revision": command.expected_revision + 1,
        "overrides": overrides,
        "updated_at": datetime.now(UTC).isoformat(),
        "updated_by": command.actor_id,
    }


def runtime_settings_projection(
    base_projection: Mapping[str, object],
    state: Mapping[str, object] | None,
) -> dict[str, object]:
    projection = dict(base_projection)
    raw_settings = projection.get("settings")
    if not isinstance(raw_settings, list):
        raise IamUnavailableError("runtime settings projection has no settings")
    if state is None:
        return projection
    revision = state.get("revision")
    overrides = state.get("overrides")
    updated_at = state.get("updated_at")
    updated_by = state.get("updated_by")
    if (
        not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 1
        or not isinstance(overrides, Mapping)
        or not isinstance(updated_at, str)
        or not updated_at
        or not isinstance(updated_by, str)
        or not updated_by
    ):
        raise IamUnavailableError("stored runtime settings are malformed")
    settings: list[dict[str, object]] = []
    known_keys: set[str] = set()
    for raw_setting in raw_settings:
        if not isinstance(raw_setting, Mapping):
            raise IamUnavailableError("runtime settings projection contains a malformed setting")
        setting = dict(raw_setting)
        key = setting.get("key")
        if not isinstance(key, str) or not key or key in known_keys:
            raise IamUnavailableError("runtime settings projection contains an invalid key")
        known_keys.add(key)
        environment_value = setting.get("environment_value")
        if key in overrides:
            override = validate_runtime_setting_value(setting, overrides[key])
            setting["override_value"] = override
            setting["effective_value"] = override
        else:
            setting["override_value"] = None
            setting["effective_value"] = environment_value
        settings.append(setting)
    if set(overrides) - known_keys:
        raise IamUnavailableError("stored runtime settings contain an unknown key")
    projection.update(
        {
            "revision": revision,
            "updated_at": updated_at,
            "updated_by": updated_by,
            "settings": settings,
        }
    )
    return projection


def teams_a1_onboarding_projection(
    runtime_projection: Mapping[str, object],
    state: Mapping[str, object] | None,
    *,
    can_manage: bool,
) -> dict[str, object]:
    runtime = runtime_projection.get("runtime")
    environment = runtime.get("environment") if isinstance(runtime, Mapping) else "unspecified"
    if state is None:
        return {
            "revision": 0,
            "state": "not-configured",
            "environment": environment,
            "can_manage": can_manage,
            "execution_authority": False,
        }
    revision = state.get("revision")
    requested_environment = state.get("environment")
    if (
        not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 1
        or state.get("state") != "plan-requested"
        or requested_environment != environment
        or state.get("execution_authority") is not False
        or state.get("activation_boundary") != "protected-plan-only"
    ):
        raise IamUnavailableError("stored Teams A1 onboarding plan is malformed")
    return {
        "revision": revision,
        "state": "plan-requested",
        "environment": requested_environment,
        "can_manage": can_manage,
        "execution_authority": False,
    }


def validate_runtime_setting_value(setting: Mapping[str, object], value: object) -> object:
    key = setting.get("key")
    value_type = setting.get("value_type")
    if not isinstance(key, str):
        raise IamUnavailableError("runtime setting key is malformed")
    if value_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{key} MUST be a boolean")
        return value
    if value_type == "enum":
        options = setting.get("options")
        if not isinstance(value, str) or not isinstance(options, list) or value not in options:
            raise ValueError(f"{key} MUST be one of the projected options")
        return value
    if value_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{key} MUST be an integer")
        number = float(value)
    elif value_type == "number":
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise ValueError(f"{key} MUST be a number")
        number = float(value)
    else:
        raise IamUnavailableError("runtime setting type is malformed")
    if not math.isfinite(number):
        raise ValueError(f"{key} MUST be finite")
    minimum = setting.get("minimum")
    maximum = setting.get("maximum")
    if isinstance(minimum, int | float) and number < float(minimum):
        raise ValueError(f"{key} is below the projected minimum")
    if isinstance(maximum, int | float) and number > float(maximum):
        raise ValueError(f"{key} is above the projected maximum")
    return value


def binding_receipt(
    stored: StoredProposal,
    *,
    state: str,
    command: ModelBindingDraftCommand | ModelBindingRequestCommand,
) -> JsonMapping:
    policy_revision = (
        command.expected_revision + 1
        if isinstance(command, ModelBindingDraftCommand)
        else command.policy_revision
    )
    return {
        "proposal_id": stored.proposal_id,
        "accepted_at": stored.accepted_at,
        "duplicate": stored.duplicate,
        "state": state,
        "policy_digest": command.policy_digest,
        "policy_revision": policy_revision,
        "execution_authority": False,
        "activation_boundary": "protected-plan-only",
    }


def stored_binding_policy(state: Mapping[str, object]) -> ModelBindingPolicy:
    policy_raw = state.get("policy")
    if not isinstance(policy_raw, Mapping):
        raise IamUnavailableError("stored model binding policy is malformed")
    try:
        policy = ModelBindingPolicy.model_validate(policy_raw)
    except ValidationError as exc:
        raise IamUnavailableError("stored model binding policy is malformed") from exc
    if (
        state.get("environment") != policy.environment
        or state.get("revision") != policy.revision
        or state.get("policy_digest") != policy.digest()
        or state.get("state") != "draft"
        or state.get("execution_authority") is not False
        or state.get("activation_boundary") != "protected-plan-only"
    ):
        raise IamUnavailableError("stored model binding policy metadata is inconsistent")
    return policy


def binding_policy_projection(state: Mapping[str, object], *, can_manage: bool) -> JsonMapping:
    policy = stored_binding_policy(state)
    return {
        "environment": policy.environment,
        "revision": policy.revision,
        "state": "draft",
        "policy": policy.model_dump(mode="json", exclude_none=True),
        "policy_digest": policy.digest(),
        "can_manage": can_manage,
        "execution_authority": False,
        "activation_boundary": "protected-plan-only",
    }


def stored_document_ocr_policy(state: Mapping[str, object] | None) -> DocumentOcrPolicy:
    if state is None:
        raise IamNotFoundError("document OCR policy does not exist")
    policy_raw = state.get("policy")
    if not isinstance(policy_raw, Mapping):
        raise IamUnavailableError("stored document OCR policy is malformed")
    try:
        policy = DocumentOcrPolicy.model_validate(policy_raw)
    except ValidationError as exc:
        raise IamUnavailableError("stored document OCR policy is malformed") from exc
    if (
        state.get("environment") != policy.environment
        or state.get("revision") != policy.revision
        or state.get("policy_digest") != policy.digest()
        or state.get("state") not in {"plan-required", "plan-requested"}
        or state.get("execution_authority") is not False
        or state.get("activation_boundary") != "protected-plan-only"
    ):
        raise IamUnavailableError("stored document OCR policy metadata is inconsistent")
    return policy


def state_revision(state: Mapping[str, object] | None, *, label: str) -> int:
    if state is None:
        return 0
    revision = state.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise IamUnavailableError(f"stored {label} revision is malformed")
    return revision


def document_ocr_projection(
    base: object,
    state: Mapping[str, object] | None,
    plan_state: Mapping[str, object] | None,
    *,
    can_manage: bool,
) -> JsonMapping:
    projection: dict[str, object] = (
        dict(base)
        if isinstance(base, Mapping)
        else {
            "available": True,
            "effective_provider": "local_python",
            "local_python_available": True,
            "azure_available": False,
            "azure_resource_state": "absent",
            "korean_enabled": True,
        }
    )
    projection["can_manage"] = can_manage
    if state is None:
        projection.update(
            {
                "revision": 0,
                "desired_provider": projection.get("effective_provider", "local_python"),
                "azure_resource_desired": bool(projection.get("azure_resource_state") == "ready"),
                "deprovision_requested": False,
                "policy_digest": None,
                "request_state": (
                    "ready" if projection.get("azure_resource_state") == "ready" else "absent"
                ),
                "execution_authority": False,
            }
        )
        return projection
    policy = stored_document_ocr_policy(state)
    request_state = str(state.get("state"))
    if (
        plan_state is not None
        and plan_state.get("state") == "plan-requested"
        and plan_state.get("environment") == policy.environment
        and plan_state.get("policy_revision") == policy.revision
        and plan_state.get("policy_digest") == policy.digest()
        and plan_state.get("execution_authority") is False
        and plan_state.get("activation_boundary") == "protected-plan-only"
    ):
        request_state = "plan-requested"
    if projection.get("effective_provider") == policy.desired_provider.value and (
        not policy.azure_resource_desired or projection.get("azure_resource_state") == "ready"
    ):
        request_state = "ready"
    projection.update(
        {
            "revision": policy.revision,
            "desired_provider": policy.desired_provider.value,
            "azure_resource_desired": policy.azure_resource_desired,
            "deprovision_requested": policy.deprovision_requested,
            "policy_digest": policy.digest(),
            "request_state": request_state,
            "execution_authority": False,
        }
    )
    return projection


def document_ocr_receipt(
    stored: StoredProposal,
    *,
    state: str,
    policy: DocumentOcrPolicy,
) -> JsonMapping:
    return {
        "proposal_id": stored.proposal_id,
        "accepted_at": stored.accepted_at,
        "duplicate": stored.duplicate,
        "state": state,
        "policy_digest": policy.digest(),
        "policy_revision": policy.revision,
        "execution_authority": False,
        "activation_boundary": "protected-plan-only",
    }
