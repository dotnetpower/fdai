"""JSON projection helpers for resolved LLM endpoint records."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fdai.rule_catalog.schema.llm_registry import Invocation
from fdai.rule_catalog.schema.model_binding_policy import ModelSelectionMode
from fdai.rule_catalog.schema.model_endpoint import ModelApiStyle


def _narrator_to_dict(narrator: Any) -> dict[str, str]:
    payload = {
        "endpoint": narrator.endpoint,
        "deployment": narrator.deployment,
        "api_version": narrator.api_version,
    }
    if narrator.api_style is not ModelApiStyle.AZURE_OPENAI:
        payload["api_style"] = narrator.api_style.value
    if narrator.auth_audience != "https://cognitiveservices.azure.com/.default":
        payload["auth_audience"] = narrator.auth_audience
    return payload


def _capability_to_dict(capability: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": capability.name,
        "status": capability.status.value,
        "publisher": capability.publisher,
        "family": capability.family,
        "sku": capability.sku,
        "capacity_tpm": capability.capacity_tpm,
        "invocation": capability.invocation,
        "reasons": list(capability.reasons),
    }
    if capability.capacity_unit != "tpm":
        payload["capacity"] = {
            "unit": capability.capacity_unit,
            "value": capability.capacity_value or 0,
        }
    if capability.selection_mode != "auto":
        payload["selection_mode"] = capability.selection_mode
    if capability.version is not None:
        payload["version"] = capability.version
    return payload


def _narrator_from_dict(raw: Any) -> Any:
    from fdai.rule_catalog.schema.llm_resolver import NarratorCandidate

    if not isinstance(raw, dict):
        return None
    endpoint = raw.get("endpoint")
    deployment = raw.get("deployment")
    if not (isinstance(endpoint, str) and isinstance(deployment, str)):
        return None
    api_version = raw.get("api_version")
    api_style = raw.get("api_style", ModelApiStyle.AZURE_OPENAI.value)
    auth_audience = raw.get(
        "auth_audience",
        "https://cognitiveservices.azure.com/.default",
    )
    return NarratorCandidate(
        endpoint=endpoint,
        deployment=deployment,
        api_version=api_version if isinstance(api_version, str) else "2024-08-01-preview",
        api_style=ModelApiStyle(api_style),
        auth_audience=str(auth_audience),
    )


def _resolved_models_from_json[ResolvedModelsType](
    text: str,
    *,
    model_type: Callable[..., ResolvedModelsType],
    schema_version: str,
    max_bytes: int,
) -> ResolvedModelsType:
    if len(text.encode("utf-8")) > max_bytes:
        raise ValueError(f"resolved models JSON exceeds the {max_bytes}-byte limit")
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        raw = _json_object(decoded, "resolved models")
        capabilities = _json_array(raw.get("capabilities"), "resolved models.capabilities")
        decoded_schema_version = _required_json_string(
            raw.get("schema_version"), "resolved models.schema_version"
        )
        if decoded_schema_version != schema_version:
            raise ValueError("resolved models schema_version is unsupported")
        binding_policy = _optional_json_object(
            raw.get("binding_policy"), "resolved models.binding_policy"
        )
        from fdai.rule_catalog.schema.model_endpoint import ModelEndpointBinding

        return model_type(
            schema_version=decoded_schema_version,
            region=_required_json_string(raw.get("region"), "resolved models.region"),
            subscription_id=_required_json_string(
                raw.get("subscription_id"), "resolved models.subscription_id"
            ),
            deployer_object_id=_required_json_string(
                raw.get("deployer_object_id"), "resolved models.deployer_object_id"
            ),
            mixed_model_mode=_required_json_string(
                raw.get("mixed_model_mode"), "resolved models.mixed_model_mode"
            ),
            capabilities=tuple(
                _resolved_capability_from_json(capability, index=index)
                for index, capability in enumerate(capabilities)
            ),
            narrator=_optional_narrator(raw.get("narrator"), "resolved models.narrator"),
            narrator_candidates=_narrator_list(
                raw.get("narrator_candidates", []),
                "resolved models.narrator_candidates",
            ),
            vision_candidates=_narrator_list(
                raw.get("vision_candidates", []), "resolved models.vision_candidates"
            ),
            web_search_candidates=_narrator_list(
                raw.get("web_search_candidates", []),
                "resolved models.web_search_candidates",
            ),
            reasoner_primary_candidates=_narrator_list(
                raw.get("reasoner_primary_candidates", []),
                "resolved models.reasoner_primary_candidates",
            ),
            endpoint_bindings=tuple(
                ModelEndpointBinding.from_dict(
                    _json_object(binding, f"resolved models.endpoint_bindings[{index}]")
                )
                for index, binding in enumerate(
                    _json_array(
                        raw.get("endpoint_bindings", []),
                        "resolved models.endpoint_bindings",
                    )
                )
            ),
            binding_policy_environment=(
                _required_json_string(
                    binding_policy.get("environment"),
                    "resolved models.binding_policy.environment",
                )
                if binding_policy is not None
                else None
            ),
            binding_policy_revision=(
                _non_negative_json_integer(
                    binding_policy.get("revision"),
                    "resolved models.binding_policy.revision",
                )
                if binding_policy is not None
                else None
            ),
            binding_policy_digest=(
                _required_json_string(
                    binding_policy.get("digest"),
                    "resolved models.binding_policy.digest",
                )
                if binding_policy is not None
                else None
            ),
            binding_policy_expected_active_digest=(
                _required_json_string(
                    binding_policy.get("expected_active_digest"),
                    "resolved models.binding_policy.expected_active_digest",
                )
                if binding_policy is not None
                and binding_policy.get("expected_active_digest") is not None
                else None
            ),
        )
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        raise ValueError("resolved models JSON is malformed") from exc


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"resolved models JSON has duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"resolved models JSON constant {value!r} is invalid")


def _json_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} MUST be an object")
    return value


def _optional_json_object(value: object, label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    return _json_object(value, label)


def _json_array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} MUST be an array")
    return value


def _required_json_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} MUST be a non-empty string")
    return value


def _optional_json_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _required_json_string(value, label)


def _non_negative_json_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} MUST be a non-negative integer")
    return value


def _resolved_capability_from_json(value: object, *, index: int) -> Any:
    from fdai.rule_catalog.schema.llm_resolver import CapabilityStatus, ResolvedCapability

    label = f"resolved models.capabilities[{index}]"
    capability = _json_object(value, label)
    raw_reasons = _json_array(capability.get("reasons", []), f"{label}.reasons")
    reasons = tuple(
        _required_json_string(reason, f"{label}.reasons[{reason_index}]")
        for reason_index, reason in enumerate(raw_reasons)
    )
    raw_capacity = _optional_json_object(capability.get("capacity"), f"{label}.capacity")
    invocation = _required_json_string(capability.get("invocation"), f"{label}.invocation")
    try:
        normalized_invocation = Invocation(invocation).value
    except ValueError as exc:
        raise ValueError(f"{label}.invocation is invalid") from exc
    return ResolvedCapability(
        name=_required_json_string(capability.get("name"), f"{label}.name"),
        status=CapabilityStatus(_required_json_string(capability.get("status"), f"{label}.status")),
        publisher=_optional_json_string(capability.get("publisher"), f"{label}.publisher"),
        family=_optional_json_string(capability.get("family"), f"{label}.family"),
        sku=_optional_json_string(capability.get("sku"), f"{label}.sku"),
        capacity_tpm=_non_negative_json_integer(
            capability.get("capacity_tpm"), f"{label}.capacity_tpm"
        ),
        invocation=normalized_invocation,
        reasons=reasons,
        capacity_unit=(
            _required_json_string(raw_capacity.get("unit"), f"{label}.capacity.unit")
            if raw_capacity is not None
            else "tpm"
        ),
        capacity_value=(
            _non_negative_json_integer(raw_capacity.get("value"), f"{label}.capacity.value")
            if raw_capacity is not None
            else None
        ),
        selection_mode=_required_json_string(
            capability.get("selection_mode", ModelSelectionMode.AUTO.value),
            f"{label}.selection_mode",
        ),
        version=_optional_json_string(capability.get("version"), f"{label}.version"),
    )


def _optional_narrator(value: object, label: str) -> Any:
    if value is None:
        return None
    candidate = _narrator_from_dict(_json_object(value, label))
    if candidate is None:
        raise ValueError(f"{label} is invalid")
    return candidate


def _narrator_list(value: object, label: str) -> tuple[Any, ...]:
    raw_candidates = _json_array(value, label)
    return tuple(
        candidate
        for index, raw in enumerate(raw_candidates)
        if (candidate := _optional_narrator(raw, f"{label}[{index}]")) is not None
    )


__all__ = [
    "_capability_to_dict",
    "_narrator_from_dict",
    "_narrator_to_dict",
    "_resolved_models_from_json",
]
