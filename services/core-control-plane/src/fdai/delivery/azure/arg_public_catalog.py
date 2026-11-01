"""Load and resolve the complete 50-table Azure Resource Graph (ARG) public catalog.

Covers all 50 public ARG tables and 1,908 ARG-supported ARM resource types published
by Microsoft Learn, plus deterministic table resolution for all 3,405 ARM provider
schema types in ``provider-schema-catalog/azure``. Read-only metadata only; never
grants execution or mutation authority.
"""

from __future__ import annotations

import functools
import gzip
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from fdai.delivery.repo_assets import repo_asset_root

_ARG_CATALOG_REL_PATH: Final[Path] = Path("rule-catalog/collected/azure-arg/tables.json")
_ARM_SNAPSHOT_GLOB: Final[str] = "provider-schema-catalog/azure/snapshots/*.json.gz"
_VALID_OWNERS: Final[frozenset[str]] = frozenset({"Huginn", "Heimdall", "Njord", "Vidar"})
_ARG_HUGINN_TABLES = (
    "aksresources",
    "appserviceresources",
    "authorizationresources",
    "awsresources",
    "azuredevopsplatformresources",
    "batchresources",
    "capabilityresources",
    "communitygalleryresources",
    "computeresources",
    "deploymentresources",
    "desktopvirtualizationresources",
    "edgeorderresources",
    "elasticsanresources",
    "extendedlocationresources",
    "extensibilityresourcechanges",
    "featureresources",
    "kubernetesconfigurationresources",
    "kustoresources",
    "managedserviceresources",
    "mirgateresources",
    "networkresourcechanges",
    "orbitalresources",
    "policyresources",
    "resourcechanges",
    "resourcecontainerchanges",
    "resourcecontainers",
    "resources",
    "servicefabricresources",
    "tagresources",
)
_ARG_HEIMDALL_TABLES = (
    "alertsmanagementresources",
    "chaosresources",
    "dnsresources",
    "guestconfigurationresources",
    "healthresourcechanges",
    "healthresources",
    "impactreportresources",
    "insightresources",
    "iotsecurityresources",
    "networkresources",
    "patchassessmentresources",
    "securityresources",
    "servicehealthresources",
)
_ARG_NJORD_TABLES = ("advisorresources", "quotaresourcechanges", "sportresources")
_ARG_VIDAR_TABLES = (
    "azurebusinesscontinuityresources",
    "maintenanceresourcechanges",
    "maintenanceresources",
    "patchinstallationresources",
    "recoveryservicesresources",
)
ARG_OBSERVATION_OWNER_BY_SOURCE: Final[dict[str, Any]] = {
    **{f"arg-{t}": "Huginn" for t in _ARG_HUGINN_TABLES},
    **{f"arg-{t}": "Heimdall" for t in _ARG_HEIMDALL_TABLES},
    **{f"arg-{t}": "Njord" for t in _ARG_NJORD_TABLES},
    **{f"arg-{t}": "Vidar" for t in _ARG_VIDAR_TABLES},
}


@dataclass(frozen=True, slots=True)
class ArgTableSpec:
    """Metadata and schema contract for one public Azure Resource Graph table."""

    table_name: str
    owner_agent: str
    domain: str
    primary_key_column: str
    scope_columns: tuple[str, ...]
    allowed_columns: tuple[str, ...]
    resource_types: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.table_name.strip() or not self.table_name.islower():
            raise ValueError("ArgTableSpec.table_name MUST be a non-empty lowercase identifier")
        if self.owner_agent not in _VALID_OWNERS:
            raise ValueError(f"ArgTableSpec.owner_agent MUST be one of {sorted(_VALID_OWNERS)}")
        if not self.domain.strip() or not self.primary_key_column.strip():
            raise ValueError("ArgTableSpec domain and primary_key_column MUST be non-empty")
        if not self.scope_columns or any(not col.strip() for col in self.scope_columns):
            raise ValueError("ArgTableSpec.scope_columns MUST be non-empty")
        if not self.allowed_columns or any(not col.strip() for col in self.allowed_columns):
            raise ValueError("ArgTableSpec.allowed_columns MUST be non-empty")
        if not self.resource_types or any(not rt.strip() for rt in self.resource_types):
            raise ValueError("ArgTableSpec.resource_types MUST be non-empty")

    @property
    def resource_type_count(self) -> int:
        return len(self.resource_types)


@dataclass(frozen=True, slots=True)
class ArgPublicCatalog:
    """In-memory index over all 50 public ARG tables and 1,908 / 3,405 ARM resource types."""

    schema_version: str
    source: str
    tables: Mapping[str, ArgTableSpec]
    tables_by_resource_type: Mapping[str, tuple[str, ...]]
    arm_schema_types: frozenset[str]

    @property
    def total_tables(self) -> int:
        return len(self.tables)

    @property
    def total_arg_resource_types(self) -> int:
        return sum(spec.resource_type_count for spec in self.tables.values())

    @property
    def total_arm_schema_types(self) -> int:
        return len(self.arm_schema_types)

    def get_table(self, table_name: str) -> ArgTableSpec:
        """Return the exact table spec by case-insensitive name, or raise KeyError."""
        if not isinstance(table_name, str) or not table_name.strip():
            raise KeyError("ARG table_name MUST be non-empty")
        key = table_name.strip().lower()
        if key not in self.tables:
            raise KeyError(f"Unknown Azure Resource Graph table: {table_name!r}")
        return self.tables[key]

    def resolve_tables_for_arm_type(self, arm_resource_type: str) -> tuple[str, ...]:
        """Resolve an ARM resource type (across all 1,908 ARG and 3,405 ARM types) to ARG tables."""
        if not isinstance(arm_resource_type, str) or not arm_resource_type.strip():
            raise ValueError("arm_resource_type MUST be a non-empty string")
        normalized = arm_resource_type.strip().lower()
        exact = self.tables_by_resource_type.get(normalized)
        if exact:
            return exact
        if normalized.startswith("microsoft.Authorization/".lower()):
            return ("authorizationresources", "resources")
        if normalized.startswith("microsoft.policyinsights/"):
            return ("policyresources",)
        if normalized.startswith("microsoft.security/"):
            return ("securityresources", "resources")
        if normalized.startswith("microsoft.advisor/"):
            return ("advisorresources",)
        if normalized.startswith("microsoft.resourcehealth/"):
            return ("healthresources", "servicehealthresources")
        if normalized.startswith("microsoft.alertsmanagement/"):
            return ("alertsmanagementresources",)
        if normalized.startswith("microsoft.maintenance/"):
            return ("maintenanceresources",)
        if normalized.startswith(("microsoft.recoveryservices/", "microsoft.dataprotection/")):
            return ("recoveryservicesresources", "resources")
        if normalized in {
            "microsoft.resources/subscriptions",
            "microsoft.resources/subscriptions/resourcegroups",
            "microsoft.management/managementgroups",
        }:
            return ("resourcecontainers",)
        return ("resources",)

    def tables_for_owner(self, owner_agent: str) -> tuple[ArgTableSpec, ...]:
        """Return all ARG tables owned by the given Pantheon agent in deterministic order."""
        clean = owner_agent.strip() if isinstance(owner_agent, str) else ""
        return tuple(spec for _, spec in sorted(self.tables.items()) if spec.owner_agent == clean)


@functools.lru_cache(maxsize=2)
def load_arg_public_catalog(repo_root: Path | None = None) -> ArgPublicCatalog:
    """Load and validate the 50-table ARG public catalog and 3,405 ARM schema types."""
    root = repo_root or repo_asset_root()
    catalog_path = root / _ARG_CATALOG_REL_PATH
    raw: dict[str, Any] = json.loads(catalog_path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "1.0.0":
        raise ValueError("Unsupported ARG public catalog schema_version")
    tables_dict: dict[str, ArgTableSpec] = {}
    by_rtype: dict[str, list[str]] = {}
    for entry in raw.get("tables", ()):
        spec = ArgTableSpec(
            table_name=str(entry["table_name"]),
            owner_agent=str(entry["owner_agent"]),
            domain=str(entry["domain"]),
            primary_key_column=str(entry["primary_key_column"]),
            scope_columns=tuple(str(c) for c in entry["scope_columns"]),
            allowed_columns=tuple(str(c) for c in entry["allowed_columns"]),
            resource_types=tuple(str(rt) for rt in entry["resource_types"]),
        )
        tables_dict[spec.table_name] = spec
        for rt in spec.resource_types:
            bucket = by_rtype.setdefault(rt, [])
            if spec.table_name not in bucket:
                bucket.append(spec.table_name)
    snap_files = sorted(root.glob(_ARM_SNAPSHOT_GLOB))
    arm_types: set[str] = set()
    if snap_files:
        with gzip.open(snap_files[0], "rt", encoding="utf-8") as handle:
            snap = json.load(handle)
        for item in snap.get("types", ()):
            rt_val = item.get("resource_type")
            if isinstance(rt_val, str) and rt_val.strip():
                arm_types.add(rt_val.strip().lower())
    return ArgPublicCatalog(
        schema_version=str(raw["schema_version"]),
        source=str(raw["source"]),
        tables=tables_dict,
        tables_by_resource_type={k: tuple(v) for k, v in by_rtype.items()},
        arm_schema_types=frozenset(arm_types),
    )


__all__ = [
    "ARG_OBSERVATION_OWNER_BY_SOURCE",
    "ArgPublicCatalog",
    "ArgTableSpec",
    "load_arg_public_catalog",
]
