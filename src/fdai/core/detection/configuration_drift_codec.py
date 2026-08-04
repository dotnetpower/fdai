"""Strict JSON boundary for deterministic configuration drift evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from fdai.core.detection.configuration_drift import (
    ConfigurationDriftReport,
    ConfigurationLink,
    ConfigurationObservation,
    ConfigurationResource,
    EvidenceCompleteness,
    FrozenConfigurationBaseline,
)

_SCHEMA_VERSION = "1.0.0"
_BASELINE_KEYS = {
    "schema_version",
    "version",
    "created_at",
    "scope",
    "source",
    "document_sha256",
    "resources",
    "links",
    "allowed_exceptions",
    "unknown_items",
}
_OBSERVATION_KEYS = {
    "schema_version",
    "scope",
    "observed_at",
    "source",
    "completeness",
    "resources",
    "links",
}
_RESOURCE_KEYS = {
    "local_name",
    "resource_type",
    "region",
    "attributes",
    "unknown_attributes",
    "unauthorized_attributes",
}
_LINK_KEYS = {"source", "relation", "target"}


def baseline_from_dict(raw: Mapping[str, Any]) -> FrozenConfigurationBaseline:
    """Decode a frozen baseline and reject unknown or missing fields."""

    _exact_keys("baseline", raw, _BASELINE_KEYS)
    _schema_version(raw)
    return FrozenConfigurationBaseline(
        version=_string(raw, "version"),
        created_at=_timestamp(raw, "created_at"),
        scope=_string(raw, "scope"),
        source=_string(raw, "source"),
        document_sha256=_string(raw, "document_sha256"),
        resources=tuple(_resource(item) for item in _objects(raw, "resources")),
        links=tuple(_link(item) for item in _objects(raw, "links")),
        allowed_exceptions=_strings(raw, "allowed_exceptions"),
        unknown_items=_strings(raw, "unknown_items"),
    )


def observation_from_dict(raw: Mapping[str, Any]) -> ConfigurationObservation:
    """Decode one bounded current-state observation."""

    _exact_keys("observation", raw, _OBSERVATION_KEYS)
    _schema_version(raw)
    try:
        completeness = EvidenceCompleteness(_string(raw, "completeness"))
    except ValueError as exc:
        raise ValueError("observation.completeness is invalid") from exc
    return ConfigurationObservation(
        scope=_string(raw, "scope"),
        observed_at=_timestamp(raw, "observed_at"),
        source=_string(raw, "source"),
        completeness=completeness,
        resources=tuple(_resource(item) for item in _objects(raw, "resources")),
        links=tuple(_link(item) for item in _objects(raw, "links")),
    )


def report_to_dict(report: ConfigurationDriftReport) -> dict[str, object]:
    """Serialize a report without provider identifiers or exception text."""

    return {
        "schema_version": _SCHEMA_VERSION,
        "baseline_version": report.baseline_version,
        "baseline_sha256": report.baseline_sha256,
        "scope": report.scope,
        "observed_at": report.observed_at.isoformat(),
        "verdict": report.verdict.value,
        "knowledge_status": report.knowledge_status.value,
        "knowledge_citations": list(report.knowledge_citations),
        "findings": [
            {
                "target": finding.target,
                "field": finding.field,
                "baseline_value": finding.baseline_value,
                "actual_value": finding.actual_value,
                "verdict": finding.verdict.value,
                "drift_type": finding.drift_type.value,
                "source": finding.source,
            }
            for finding in report.findings
        ],
        "mutation_count": report.mutation_count,
        "approval_request_count": report.approval_request_count,
        "mitigation_execution_count": report.mitigation_execution_count,
        "unsupported_claim_count": report.unsupported_claim_count,
    }


def _resource(raw: Mapping[str, Any]) -> ConfigurationResource:
    _exact_keys("resource", raw, _RESOURCE_KEYS)
    attributes = raw.get("attributes")
    if not isinstance(attributes, Mapping):
        raise ValueError("resource.attributes MUST be an object")
    return ConfigurationResource(
        local_name=_string(raw, "local_name"),
        resource_type=_string(raw, "resource_type"),
        region=_string(raw, "region"),
        attributes=attributes,
        unknown_attributes=frozenset(_strings(raw, "unknown_attributes")),
        unauthorized_attributes=frozenset(_strings(raw, "unauthorized_attributes")),
    )


def _link(raw: Mapping[str, Any]) -> ConfigurationLink:
    _exact_keys("link", raw, _LINK_KEYS)
    return ConfigurationLink(
        source=_string(raw, "source"),
        relation=_string(raw, "relation"),
        target=_string(raw, "target"),
    )


def _schema_version(raw: Mapping[str, Any]) -> None:
    if _string(raw, "schema_version") != _SCHEMA_VERSION:
        raise ValueError(f"schema_version MUST be {_SCHEMA_VERSION}")


def _exact_keys(name: str, raw: Mapping[str, Any], expected: set[str]) -> None:
    missing = expected - set(raw)
    unknown = set(raw) - expected
    if missing:
        raise ValueError(f"{name} is missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"{name} has unknown fields: {', '.join(sorted(unknown))}")


def _string(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} MUST be a non-empty string")
    return value


def _timestamp(raw: Mapping[str, Any], key: str) -> datetime:
    try:
        return datetime.fromisoformat(_string(raw, key).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{key} MUST be an RFC 3339 timestamp") from exc


def _sequence(raw: Mapping[str, Any], key: str) -> Sequence[Any]:
    value = raw.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} MUST be an array")
    return value


def _strings(raw: Mapping[str, Any], key: str) -> tuple[str, ...]:
    values = _sequence(raw, key)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{key} MUST contain only non-empty strings")
    return tuple(values)


def _objects(raw: Mapping[str, Any], key: str) -> tuple[Mapping[str, Any], ...]:
    values = _sequence(raw, key)
    if any(not isinstance(value, Mapping) for value in values):
        raise ValueError(f"{key} MUST contain only objects")
    return tuple(values)


__all__ = ["baseline_from_dict", "observation_from_dict", "report_to_dict"]
