"""Load and compile the 24 causal telemetry mechanisms and 50 active diagnostic probes.

Covers all 24 causal telemetry mechanisms (expanding the 8 base mechanisms with 16
network, database, storage, security, policy, and recovery mechanisms) and all 50
active diagnostic probe contracts. Read-only metadata and KQL compilation only.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from fdai.delivery.repo_assets import repo_asset_root

_MECH_PROBES_REL_PATH: Final[Path] = Path(
    "rule-catalog/collected/azure-monitor/causal-mechanisms-and-probes.json"
)
_VALID_OWNERS: Final[frozenset[str]] = frozenset({"Huginn", "Heimdall", "Njord", "Vidar"})


class CatalogTelemetryMechanism(StrEnum):
    """Complete 24-member causal telemetry mechanism vocabulary."""

    FAILED_REQUESTS = "failed_requests"
    ERROR_TIMELINE = "error_timeline"
    DEPENDENCY_LATENCY = "dependency_latency"
    SLOW_TRACES = "slow_traces"
    GUEST_SHUTDOWN = "guest_shutdown"
    CONTAINER_RESTARTS = "container_restarts"
    THROTTLING = "throttling"
    RESOURCE_SATURATION = "resource_saturation"
    NETWORK_FLOW_DROP = "network_flow_drop"
    FIREWALL_DENY = "firewall_deny"
    DNS_RESOLUTION_FAILURE = "dns_resolution_failure"
    TLS_HANDSHAKE_FAILURE = "tls_handshake_failure"
    CERTIFICATE_EXPIRY = "certificate_expiry"
    SQL_DEADLOCK = "sql_deadlock"
    SQL_BLOCKING_SESSION = "sql_blocking_session"
    STORAGE_IOPS_SATURATION = "storage_iops_saturation"
    DISK_QUEUE_SATURATION = "disk_queue_saturation"
    MEMORY_OOM_PRESSURE = "memory_oom_pressure"
    AUTOSCALE_FLAPPING = "autoscale_flapping"
    DEPLOYMENT_OPERATION_FAILURE = "deployment_operation_failure"
    POLICY_NON_COMPLIANCE_EVENT = "policy_non_compliance_event"
    SECURITY_ALERT_TRIGGERED = "security_alert_triggered"
    BACKUP_JOB_FAILURE = "backup_job_failure"
    REPLICATION_LAG_BREACH = "replication_lag_breach"


@dataclass(frozen=True, slots=True)
class CausalMechanismRecipe:
    """Declarative KQL recipe for one of the 24 causal telemetry mechanisms."""

    mechanism: CatalogTelemetryMechanism
    log_table: str
    predicate: str
    owner_agent: str
    kql: str

    def __post_init__(self) -> None:
        if not self.log_table.strip() or not self.predicate.strip() or not self.kql.strip():
            raise ValueError("CausalMechanismRecipe fields MUST be non-empty")
        if self.owner_agent not in _VALID_OWNERS:
            raise ValueError(f"Unsupported owner_agent: {self.owner_agent!r}")


@dataclass(frozen=True, slots=True)
class DiagnosticProbeRecipe:
    """Declarative specification for one of the 50 active diagnostic probes."""

    probe_id: str
    source_kind: str
    target_table: str
    owner_agent: str
    timeout_seconds: int
    max_rows: int

    def __post_init__(self) -> None:
        if not self.probe_id.strip() or not self.target_table.strip():
            raise ValueError("DiagnosticProbeRecipe probe_id and target_table MUST be non-empty")
        if self.source_kind not in {"arg", "monitor"}:
            raise ValueError("DiagnosticProbeRecipe.source_kind MUST be 'arg' or 'monitor'")
        if self.owner_agent not in _VALID_OWNERS:
            raise ValueError(f"Unsupported owner_agent: {self.owner_agent!r}")
        if (
            type(self.timeout_seconds) is not int
            or type(self.max_rows) is not int
            or not 1 <= self.timeout_seconds <= 60
            or not 1 <= self.max_rows <= 1000
        ):
            raise ValueError("DiagnosticProbeRecipe timeout_seconds and max_rows out of bounds")


@dataclass(frozen=True, slots=True)
class CausalMechanismAndProbeCatalog:
    """In-memory catalog of all 24 causal telemetry mechanisms and 50 diagnostic probes."""

    mechanisms: Mapping[CatalogTelemetryMechanism, CausalMechanismRecipe]
    probes: Mapping[str, DiagnosticProbeRecipe]

    @property
    def total_mechanisms(self) -> int:
        return len(self.mechanisms)

    @property
    def total_probes(self) -> int:
        return len(self.probes)

    def get_mechanism(self, mechanism: CatalogTelemetryMechanism | str) -> CausalMechanismRecipe:
        key = (
            mechanism
            if isinstance(mechanism, CatalogTelemetryMechanism)
            else CatalogTelemetryMechanism(mechanism.strip().lower())
        )
        return self.mechanisms[key]

    def get_probe(self, probe_id: str) -> DiagnosticProbeRecipe:
        clean = probe_id.strip() if isinstance(probe_id, str) else ""
        if clean not in self.probes:
            raise KeyError(f"Unknown diagnostic probe_id: {probe_id!r}")
        return self.probes[clean]


@functools.lru_cache(maxsize=2)
def load_causal_mechanism_and_probe_catalog(
    repo_root: Path | None = None,
) -> CausalMechanismAndProbeCatalog:
    """Load and validate all 24 causal telemetry mechanisms and 50 diagnostic probes."""
    root = repo_root or repo_asset_root()
    raw: dict[str, Any] = json.loads((root / _MECH_PROBES_REL_PATH).read_text(encoding="utf-8"))
    mechs: dict[CatalogTelemetryMechanism, CausalMechanismRecipe] = {}
    for entry in raw.get("mechanisms", ()):
        enum_key = CatalogTelemetryMechanism(str(entry["mechanism_id"]))
        mechs[enum_key] = CausalMechanismRecipe(
            mechanism=enum_key,
            log_table=str(entry["log_table"]),
            predicate=str(entry["predicate"]),
            owner_agent=str(entry["owner_agent"]),
            kql=str(entry["kql"]),
        )
    probes: dict[str, DiagnosticProbeRecipe] = {}
    for item in raw.get("probes", ()):
        probe = DiagnosticProbeRecipe(
            probe_id=str(item["probe_id"]),
            source_kind=str(item["source_kind"]),
            target_table=str(item["target_table"]),
            owner_agent=str(item["owner_agent"]),
            timeout_seconds=int(item["timeout_seconds"]),
            max_rows=int(item["max_rows"]),
        )
        probes[probe.probe_id] = probe
    return CausalMechanismAndProbeCatalog(
        mechanisms=MappingProxyType(mechs),
        probes=MappingProxyType(probes),
    )


__all__ = [
    "CatalogTelemetryMechanism",
    "CausalMechanismAndProbeCatalog",
    "CausalMechanismRecipe",
    "DiagnosticProbeRecipe",
    "load_causal_mechanism_and_probe_catalog",
]
