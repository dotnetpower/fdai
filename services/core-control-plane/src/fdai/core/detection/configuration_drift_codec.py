"""Strict JSON boundary for deterministic configuration drift evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any

from fdai.core.detection.configuration_drift import (
    ConfigurationDriftPerformance,
    ConfigurationDriftReport,
    ConfigurationLink,
    ConfigurationObservation,
    ConfigurationResource,
    DriftFinding,
    DriftType,
    DriftVerdict,
    EvidenceCompleteness,
    FrozenConfigurationBaseline,
    KnowledgeGroundingStatus,
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
_REPORT_KEYS = {
    "schema_version",
    "baseline_version",
    "baseline_sha256",
    "scope",
    "observed_at",
    "verdict",
    "knowledge_status",
    "knowledge_citations",
    "findings",
    "mutation_count",
    "approval_request_count",
    "mitigation_execution_count",
    "unsupported_claim_count",
    "performance",
}
_FINDING_KEYS = {
    "target",
    "field",
    "baseline_value",
    "actual_value",
    "verdict",
    "drift_type",
    "source",
}
_PERFORMANCE_KEYS = {
    "baseline_load_ms",
    "observation_ms",
    "comparison_ms",
    "knowledge_ms",
    "total_ms",
    "resource_count",
    "finding_count",
}


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
        "performance": report.performance.to_dict() if report.performance is not None else None,
    }


def report_from_dict(raw: Mapping[str, Any]) -> ConfigurationDriftReport:
    """Decode a persisted report and reject unknown or missing evidence fields."""

    _exact_keys("report", raw, _REPORT_KEYS)
    _schema_version(raw)
    findings = _objects(raw, "findings")
    citations = _strings(raw, "knowledge_citations")
    performance_raw = raw.get("performance")
    if performance_raw is not None and not isinstance(performance_raw, Mapping):
        raise ValueError("report.performance MUST be an object or null")
    return ConfigurationDriftReport(
        baseline_version=_string(raw, "baseline_version"),
        baseline_sha256=_string(raw, "baseline_sha256"),
        scope=_string(raw, "scope"),
        observed_at=_timestamp(raw, "observed_at"),
        verdict=_enum(raw, "verdict", DriftVerdict),
        findings=tuple(_finding(item) for item in findings),
        knowledge_status=_enum(raw, "knowledge_status", KnowledgeGroundingStatus),
        knowledge_citations=citations,
        mutation_count=_integer(raw, "mutation_count"),
        approval_request_count=_integer(raw, "approval_request_count"),
        mitigation_execution_count=_integer(raw, "mitigation_execution_count"),
        unsupported_claim_count=_integer(raw, "unsupported_claim_count"),
        performance=None if performance_raw is None else _performance(performance_raw),
    )


def _finding(raw: Mapping[str, Any]) -> DriftFinding:
    _exact_keys("finding", raw, _FINDING_KEYS)
    return DriftFinding(
        target=_string(raw, "target"),
        field=_string(raw, "field"),
        baseline_value=raw.get("baseline_value"),
        actual_value=raw.get("actual_value"),
        verdict=_enum(raw, "verdict", DriftVerdict),
        drift_type=_enum(raw, "drift_type", DriftType),
        source=_string(raw, "source"),
    )


def _performance(raw: Mapping[str, Any]) -> ConfigurationDriftPerformance:
    _exact_keys("performance", raw, _PERFORMANCE_KEYS)
    return ConfigurationDriftPerformance(
        baseline_load_ms=_number(raw, "baseline_load_ms"),
        observation_ms=_number(raw, "observation_ms"),
        comparison_ms=_number(raw, "comparison_ms"),
        knowledge_ms=_number(raw, "knowledge_ms"),
        total_ms=_number(raw, "total_ms"),
        resource_count=_integer(raw, "resource_count"),
        finding_count=_integer(raw, "finding_count"),
    )


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


def _integer(raw: Mapping[str, Any], key: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{key} MUST be a non-negative integer")
    return value


def _number(raw: Mapping[str, Any], key: str) -> float:
    value = raw.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{key} MUST be a number")
    return float(value)


def _enum[T: StrEnum](raw: Mapping[str, Any], key: str, enum_type: type[T]) -> T:
    try:
        return enum_type(_string(raw, key))
    except ValueError as exc:
        raise ValueError(f"{key} is invalid") from exc


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


__all__ = [
    "baseline_from_dict",
    "observation_from_dict",
    "report_from_dict",
    "report_to_dict",
]
