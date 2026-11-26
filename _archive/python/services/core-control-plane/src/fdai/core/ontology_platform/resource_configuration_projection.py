"""Reviewed configuration projections, excluding arbitrary provider payloads and clock churn."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai_service_contracts.ontology_query import content_digest

from fdai.shared.providers.ontology_instance import OntologyObjectRecord

MODEL_CONFIGURATION_FIELDS = (
    "model_name",
    "model_version",
    "sku_name",
    "capacity_units",
    "current_capacity_units",
    "capacity_transitioning",
    "capacity_tpm",
    "capacity_tpm_source",
)
_MODEL_TEXT_FIELDS = frozenset({"model_name", "model_version", "sku_name"})
_MODEL_INTEGER_FIELDS = frozenset({"capacity_units", "current_capacity_units", "capacity_tpm"})
GENERIC_CONFIGURATION_FIELDS = ("location", "sku_name", "capacity_units")
_MAX_INTEGER = 2_147_483_647


@dataclass(frozen=True, slots=True)
class ReviewedConfiguration:
    """Only reviewed values or field digests, with explicit unavailable fields."""

    values: Mapping[str, Any]
    missing_fields: tuple[str, ...]
    digest: str


def project_resource_configuration(record: OntologyObjectRecord) -> ReviewedConfiguration:
    """Project lifted neutral facts only; never hash or return the raw provider payload."""
    payload = record.properties.get("properties")
    payload = payload if isinstance(payload, Mapping) else {}
    model = record.properties.get("type") == "llm-model-deployment"
    fields = MODEL_CONFIGURATION_FIELDS if model else GENERIC_CONFIGURATION_FIELDS
    values: dict[str, Any] = {}
    missing: list[str] = []
    for field in fields:
        raw = record.properties.get("location") if field == "location" else payload.get(field)
        value = _reviewed_value(field, raw)
        if (
            field == "capacity_tpm"
            and payload.get("capacity_tpm_source") != "properties.rateLimits"
        ):
            value = None
        if value is None:
            missing.append(field)
        values[field] = value if model or value is None else {"digest": content_digest(value)}
    if model:
        desired = values["capacity_units"]
        current = values["current_capacity_units"]
        transitioning = values["capacity_transitioning"]
        if (
            desired is not None
            and current is not None
            and transitioning is not None
            and transitioning != (desired != current)
        ):
            values["capacity_transitioning"] = None
            missing.append("capacity_transitioning")
        if values["capacity_tpm"] is None:
            values["capacity_tpm_source"] = None
            missing.append("capacity_tpm_source")
    return ReviewedConfiguration(
        values=values,
        missing_fields=tuple(sorted(set(missing))),
        digest=content_digest(values),
    )


def _reviewed_value(field: str, raw: Any) -> object:
    if field in _MODEL_TEXT_FIELDS or field == "location":
        return raw if isinstance(raw, str) and raw.strip() and len(raw) <= 256 else None
    if field in _MODEL_INTEGER_FIELDS:
        return (
            raw
            if isinstance(raw, int) and not isinstance(raw, bool) and 0 <= raw <= _MAX_INTEGER
            else None
        )
    if field == "capacity_transitioning":
        return raw if isinstance(raw, bool) else None
    if field == "capacity_tpm_source":
        return raw if raw == "properties.rateLimits" else None
    return None


__all__ = [
    "GENERIC_CONFIGURATION_FIELDS",
    "MODEL_CONFIGURATION_FIELDS",
    "ReviewedConfiguration",
    "project_resource_configuration",
]
