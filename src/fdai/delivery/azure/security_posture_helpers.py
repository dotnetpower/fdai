"""Shared deterministic evaluators for Azure security posture controls."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Final

from fdai.core.security import (
    ControlStatus,
    RemediationPriority,
    SecurityControlObservation,
)
from fdai.delivery.azure.security_posture_models import AzureCveEvidence
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.projection import Severity

MISSING: Final[object] = object()


def control(
    record: ResourceRecord,
    assessed_at: datetime,
    control_id: str,
    title: str,
    category: str,
    status: ControlStatus,
    severity: Severity,
    current_value: str,
    expected_value: str,
    source: str,
    rationale: str,
    *,
    remediation: str = "",
    validation: str = "",
    priority: str = "none",
    due_days: int | None = None,
    compliance: tuple[str, ...] = (),
    cves: tuple[str, ...] = (),
    applicability: str = "applicable",
    patch_status: str = "",
    managed_note: str = "",
    source_url: str = "",
    source_urls: tuple[str, ...] = (),
) -> SecurityControlObservation:
    """Build one grounded control observation from a resource record."""

    reference = record.provider_ref or record.resource_id
    urls = source_urls or ((source_url,) if source_url else ())
    return SecurityControlObservation(
        control_id=control_id,
        title=title,
        category=category,
        resource_type=record.type,
        resource_ref=record.resource_id,
        status=status,
        severity=severity,
        current_value=current_value,
        expected_value=expected_value,
        rationale=rationale,
        source=source,
        collected_at=assessed_at,
        evidence_refs=(f"{reference}#{control_id}",),
        remediation=remediation,
        validation=validation,
        priority=RemediationPriority(priority),
        due_days=due_days,
        applicability=applicability,
        cve_ids=cves,
        compliance_controls=compliance,
        source_urls=urls,
        managed_service_note=managed_note,
        patch_status=patch_status,
    )


def mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def lookup(source: Mapping[str, Any], *keys: str) -> object:
    for key in keys:
        if key in source:
            return source[key]
    return MISSING


def display(value: object) -> str:
    if value is MISSING:
        return "unavailable"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def bool_status(value: object) -> ControlStatus:
    if value is MISSING:
        return ControlStatus.UNKNOWN
    return ControlStatus.PASS if value is True else ControlStatus.FAIL


def optional_bool_status(value: bool | None) -> ControlStatus:
    if value is None:
        return ControlStatus.UNKNOWN
    return ControlStatus.PASS if value else ControlStatus.FAIL


def presence_status(value: object) -> ControlStatus:
    if value is MISSING:
        return ControlStatus.UNKNOWN
    return ControlStatus.PASS if value not in (None, "", {}, ()) else ControlStatus.FAIL


def enabled_string_status(value: object, *, disabled: tuple[str, ...]) -> ControlStatus:
    if value is MISSING:
        return ControlStatus.UNKNOWN
    return ControlStatus.FAIL if str(value).lower() in disabled else ControlStatus.PASS


def disabled_string_status(value: object) -> ControlStatus:
    if value is MISSING:
        return ControlStatus.UNKNOWN
    return ControlStatus.PASS if str(value).lower() == "disabled" else ControlStatus.FAIL


def parameter_status(
    parameters: Mapping[str, str], name: str, *, expected: tuple[str, ...]
) -> ControlStatus:
    value = parameters.get(name)
    if value is None:
        return ControlStatus.UNKNOWN
    return ControlStatus.PASS if value.lower() in expected else ControlStatus.FAIL


def minimum_int_status(value: object, *, minimum: int) -> ControlStatus:
    if value is MISSING:
        return ControlStatus.UNKNOWN
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return ControlStatus.UNKNOWN
    try:
        observed = int(value)
    except ValueError:
        return ControlStatus.UNKNOWN
    return ControlStatus.PASS if observed >= minimum else ControlStatus.WARNING


def tls_status(value: str | None) -> ControlStatus:
    if value is None:
        return ControlStatus.UNKNOWN
    normalized = {item.strip().lower() for item in value.split(",")}
    weak = {"tlsv1", "tlsv1.0", "tlsv1.1"}
    strong = {"tlsv1.2", "tlsv1.3"}
    if strong <= normalized and not weak & normalized:
        return ControlStatus.PASS
    return ControlStatus.FAIL


def private_mysql_status(
    network: Mapping[str, Any], properties: Mapping[str, Any]
) -> ControlStatus:
    values = (
        lookup(network, "delegatedSubnetResourceId"),
        lookup(network, "privateDnsZoneResourceId"),
        lookup(properties, "privateEndpointConnections"),
    )
    if all(value is MISSING for value in values):
        return ControlStatus.UNKNOWN
    present = any(value not in (MISSING, None, "", (), []) for value in values)
    return ControlStatus.PASS if present else ControlStatus.FAIL


def private_mysql_value(network: Mapping[str, Any], properties: Mapping[str, Any]) -> str:
    if lookup(network, "delegatedSubnetResourceId") not in (MISSING, None, ""):
        return "delegated-subnet"
    connections = lookup(properties, "privateEndpointConnections")
    if (
        isinstance(connections, Sequence)
        and not isinstance(connections, (str, bytes))
        and connections
    ):
        return "private-endpoint"
    return "none" if connections is not MISSING else "unavailable"


def cve_status(cves: Sequence[AzureCveEvidence]) -> tuple[ControlStatus, str]:
    if not cves:
        return (ControlStatus.UNKNOWN, "not_assessed")
    if any(item.applicability == "applicable" and item.patch_status == "affected" for item in cves):
        return (ControlStatus.FAIL, "affected")
    if all(item.patch_status in {"patched", "not_affected"} for item in cves):
        return (ControlStatus.PASS, "patched_or_not_affected")
    return (ControlStatus.WARNING, "partially_assessed")


def combined_applicability(cves: Sequence[AzureCveEvidence]) -> str:
    if not cves:
        return "unknown"
    if any(item.applicability == "applicable" for item in cves):
        return "applicable"
    if all(item.applicability == "not_applicable" for item in cves):
        return "not_applicable"
    return "unknown"


__all__ = [
    "MISSING",
    "bool_status",
    "combined_applicability",
    "control",
    "cve_status",
    "disabled_string_status",
    "display",
    "enabled_string_status",
    "lookup",
    "mapping",
    "minimum_int_status",
    "optional_bool_status",
    "parameter_status",
    "presence_status",
    "private_mysql_status",
    "private_mysql_value",
    "tls_status",
]
