"""MySQL Flexible Server controls for the Azure security posture analyzer."""

from __future__ import annotations

from datetime import datetime
from typing import Final

from fdai.core.security import ControlStatus, SecurityControlObservation
from fdai.delivery.azure.security_posture_helpers import (
    MISSING,
    combined_applicability,
    control,
    cve_status,
    disabled_string_status,
    display,
    enabled_string_status,
    lookup,
    mapping,
    minimum_int_status,
    optional_bool_status,
    parameter_status,
    presence_status,
    private_mysql_status,
    private_mysql_value,
    tls_status,
)
from fdai.delivery.azure.security_posture_models import AzureResourceSecurityEvidence
from fdai.shared.providers.inventory import ResourceRecord

_MYSQL_GUIDANCE: Final[str] = "https://learn.microsoft.com/azure/mysql/flexible-server/"


def mysql_controls(
    record: ResourceRecord,
    *,
    extra: AzureResourceSecurityEvidence,
    assessed_at: datetime,
) -> tuple[SecurityControlObservation, ...]:
    """Evaluate Resource Graph and supplemental MySQL evidence."""

    props = mapping(record.props.get("properties"))
    sku = mapping(record.props.get("sku"))
    network = mapping(props.get("network"))
    backup = mapping(props.get("backup"))
    high_availability = mapping(props.get("highAvailability"))
    version_status, patch_status = cve_status(extra.cves)
    source_urls = tuple(item.source_url for item in extra.cves if item.source_url)
    managed_note = " ".join(
        dict.fromkeys(item.managed_service_note for item in extra.cves if item.managed_service_note)
    )
    parameters = {key.lower(): value for key, value in extra.server_parameters.items()}

    return (
        control(
            record,
            assessed_at,
            "mysql-version",
            "MySQL patch line",
            "patching",
            version_status,
            "high",
            display(lookup(props, "version", "fullVersion")),
            "supported-current",
            "security-advisory",
            "Version and provider backport evidence determine vulnerability applicability.",
            remediation=(
                "Review the managed patch line and schedule a supported minor-version upgrade."
            ),
            validation="Re-read fullVersion and advisory patch status after maintenance.",
            priority="critical",
            due_days=1,
            cves=tuple(item.cve_id for item in extra.cves),
            applicability=combined_applicability(extra.cves),
            patch_status=patch_status,
            managed_note=managed_note,
            source_urls=source_urls or (_MYSQL_GUIDANCE,),
        ),
        control(
            record,
            assessed_at,
            "mysql-secure-transport",
            "Secure transport required",
            "encryption",
            parameter_status(
                parameters,
                "require_secure_transport",
                expected=("on", "true", "1"),
            ),
            "high",
            parameters.get("require_secure_transport", "unavailable"),
            "ON",
            "mysql-server-parameters",
            "Secure transport prevents plaintext database sessions.",
            remediation="Enable require_secure_transport.",
            validation="Verify a plaintext connection is rejected.",
            priority="critical",
            due_days=1,
            compliance=("CIS-MYSQL-3.2",),
            source_url=_MYSQL_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "mysql-tls",
            "Minimum TLS version",
            "encryption",
            tls_status(parameters.get("tls_version")),
            "high",
            parameters.get("tls_version", "unavailable"),
            "TLSv1.2,TLSv1.3",
            "mysql-server-parameters",
            "Modern TLS protects database traffic in transit.",
            remediation="Restrict tls_version to TLSv1.2 and TLSv1.3.",
            validation="Negotiate supported and rejected TLS versions.",
            priority="critical",
            due_days=1,
            compliance=("MCSB-DP-3",),
            source_url=_MYSQL_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "mysql-public-access",
            "Public network access disabled",
            "network",
            disabled_string_status(lookup(network, "publicNetworkAccess")),
            "high",
            display(lookup(network, "publicNetworkAccess")),
            "disabled",
            "azure-resource-graph",
            "Private access reduces the database network attack surface.",
            remediation="Disable public network access and validate private DNS.",
            validation="Verify the public endpoint cannot be reached.",
            priority="critical",
            due_days=1,
            compliance=("MCSB-NS-2",),
            source_url=_MYSQL_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "mysql-private-network",
            "Private network integration",
            "network",
            private_mysql_status(network, props),
            "high",
            private_mysql_value(network, props),
            "delegated-subnet-or-private-endpoint",
            "azure-resource-graph",
            "Private network integration limits database reachability.",
            remediation="Configure delegated-subnet or private-endpoint access.",
            validation="Resolve and connect through the private path.",
            priority="high",
            due_days=7,
            source_url=_MYSQL_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "mysql-backup-retention",
            "Backup retention",
            "resilience",
            minimum_int_status(lookup(backup, "backupRetentionDays"), minimum=14),
            "medium",
            display(lookup(backup, "backupRetentionDays")),
            "14-or-more-days",
            "azure-resource-graph",
            "Longer retention expands the recoverable incident window.",
            remediation="Increase backup retention to the approved recovery baseline.",
            validation="Verify backupRetentionDays after the update.",
            priority="high",
            due_days=7,
            source_url=_MYSQL_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "mysql-geo-backup",
            "Geo-redundant backup",
            "resilience",
            enabled_string_status(
                lookup(backup, "geoRedundantBackup"),
                disabled=("", "disabled", "none"),
            ),
            "medium",
            display(lookup(backup, "geoRedundantBackup")),
            "enabled",
            "azure-resource-graph",
            "Geo-redundant backup supports regional recovery.",
            remediation="Plan a supported geo-redundant backup configuration.",
            validation="Verify restore capability in the paired region.",
            priority="medium",
            due_days=30,
            source_url=_MYSQL_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "mysql-ha",
            "Zone-redundant high availability",
            "resilience",
            enabled_string_status(
                lookup(high_availability, "mode"),
                disabled=("", "disabled", "none"),
            ),
            "high",
            display(lookup(high_availability, "mode")),
            "zone-redundant",
            "azure-resource-graph",
            "High availability limits single-instance failure impact.",
            remediation="Enable zone-redundant high availability where supported.",
            validation="Verify primary and standby zones and run a controlled failover.",
            priority="high",
            due_days=7,
            source_url=_MYSQL_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "mysql-cmk",
            "Customer-managed encryption key",
            "encryption",
            presence_status(lookup(props, "dataEncryption")),
            "medium",
            display(lookup(props, "dataEncryption")),
            "approved-key-policy",
            "azure-resource-graph",
            "An approved key policy can add separation and rotation controls.",
            remediation="Evaluate and configure the approved encryption-key policy.",
            validation="Verify key identity, rotation, and recovery access.",
            priority="medium",
            due_days=30,
            source_url=_MYSQL_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "mysql-audit-log",
            "Database audit logging",
            "monitoring",
            parameter_status(
                parameters,
                "audit_log_enabled",
                expected=("on", "true", "1"),
            ),
            "high",
            parameters.get("audit_log_enabled", "unavailable"),
            "ON",
            "mysql-server-parameters",
            "Audit logging records privileged and security-relevant database activity.",
            remediation="Enable audit logging and route records to the monitored destination.",
            validation="Generate a test event and verify its immutable log record.",
            priority="critical",
            due_days=1,
            compliance=("CIS-MYSQL-6.1", "MCSB-LT-3"),
            source_url=_MYSQL_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "mysql-diagnostics",
            "Platform diagnostic settings",
            "monitoring",
            optional_bool_status(extra.diagnostic_settings_enabled),
            "high",
            display(extra.diagnostic_settings_enabled),
            "true",
            "azure-monitor-diagnostic-settings",
            "Platform diagnostics preserve service health and audit evidence.",
            remediation="Enable approved logs and metrics to the evidence store.",
            validation="Generate a connection event and verify its retained record.",
            priority="high",
            due_days=7,
            compliance=("MCSB-LT-3",),
            source_url=_MYSQL_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "mysql-service-tier",
            "Production database tier",
            "resilience",
            _tier_status(lookup(sku, "tier")),
            "medium",
            display(lookup(sku, "tier")),
            "general-purpose-or-higher",
            "azure-resource-graph",
            "Burstable tiers can exhaust credits under sustained production load.",
            remediation="Use a production tier when the measured workload requires it.",
            validation="Verify the tier and sustained-load capacity evidence.",
            priority="medium",
            due_days=30,
            source_url=_MYSQL_GUIDANCE,
        ),
    )


def _tier_status(value: object) -> ControlStatus:
    if value is MISSING:
        return ControlStatus.UNKNOWN
    if str(value).lower() == "burstable":
        return ControlStatus.WARNING
    return ControlStatus.PASS


__all__ = ["mysql_controls"]
