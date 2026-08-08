"""JSON projection helpers for resolved LLM endpoint records."""

from __future__ import annotations

from typing import Any

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


__all__ = ["_capability_to_dict", "_narrator_from_dict", "_narrator_to_dict"]
