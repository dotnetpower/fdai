"""Aggregate evidence contract for subscription genesis readiness."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.progress import InventoryClosure

REQUIRED_READINESS_EVIDENCE = frozenset(
    {
        "foundation_plan",
        "foundation_apply",
        "foundation_readback",
        "application_plan",
        "application_apply",
        "application_readback",
        "migration_readback",
        "semantic_readback",
        "model_readback",
        "inventory_readback",
        "rollback_rehearsal",
        "second_run_no_change",
        "system_verification",
    }
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_TERRAFORM_ROOTS = frozenset(
    {
        "bootstrap",
        "platform",
        "service.core-control-plane",
        "service.document-ingestion-api",
        "service.document-processing-worker",
        "service.isolated-executor",
        "service.operator-service",
    }
)
REQUIRED_SERVICE_MIGRATIONS = frozenset(
    {
        "core-control-plane",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
        "operator-service",
    }
)
REQUIRED_POSTGRES_EXTENSIONS = frozenset({"pg_trgm", "plpgsql", "vector"})


@dataclass(frozen=True, slots=True)
class NoChangeReadback:
    """Terraform change totals from the complete second genesis run."""

    root_changes: Mapping[str, tuple[int, int, int]]

    def __post_init__(self) -> None:
        root_changes = dict(self.root_changes)
        if set(root_changes) != REQUIRED_TERRAFORM_ROOTS:
            raise ValueError("second-run readback MUST verify every Terraform root")
        for values in root_changes.values():
            if (
                not isinstance(values, tuple)
                or len(values) != 3
                or any(
                    isinstance(value, bool) or not isinstance(value, int) or value < 0
                    for value in values
                )
            ):
                raise ValueError("second-run change counts MUST be non-negative integer triples")
            if values != (0, 0, 0):
                raise ValueError("every Terraform root in the second genesis run MUST be no-change")
        object.__setattr__(self, "root_changes", MappingProxyType(root_changes))

    def to_mapping(self) -> dict[str, object]:
        """Return canonical no-change counts."""

        return {
            "roots_total": len(self.root_changes),
            "roots": {
                root: {"add": values[0], "change": values[1], "destroy": values[2]}
                for root, values in sorted(self.root_changes.items())
            },
        }


@dataclass(frozen=True, slots=True)
class DatabaseSemanticReadback:
    """Independent database and semantic gates required before runtime readiness."""

    expected_legacy_head: str
    legacy_head: str
    expected_service_heads: Mapping[str, str]
    service_heads: Mapping[str, str]
    extensions: tuple[str, ...]
    expected_runtime_role_checks: tuple[str, ...]
    runtime_role_checks: Mapping[str, bool]
    ontology_release_digest: str
    catalog_digest: str
    defaults_digest: str
    role_manifest_digest: str
    expected_ontology_release_digest: str
    expected_catalog_digest: str
    expected_defaults_digest: str
    expected_role_manifest_digest: str
    shadow_only: bool
    observer_distinct: bool

    def __post_init__(self) -> None:
        if (
            not self.expected_legacy_head
            or len(self.expected_legacy_head) > 128
            or self.legacy_head != self.expected_legacy_head
        ):
            raise ValueError("legacy migration head is invalid")
        expected_service_heads = dict(self.expected_service_heads)
        service_heads = dict(self.service_heads)
        if (
            set(expected_service_heads) != REQUIRED_SERVICE_MIGRATIONS
            or service_heads != expected_service_heads
        ):
            raise ValueError("database readback MUST contain every service migration head")
        if any(not value or len(value) > 128 for value in service_heads.values()):
            raise ValueError("service migration head is invalid")
        object.__setattr__(
            self,
            "expected_service_heads",
            MappingProxyType(expected_service_heads),
        )
        object.__setattr__(self, "service_heads", MappingProxyType(service_heads))
        extensions = tuple(sorted(set(self.extensions)))
        if not REQUIRED_POSTGRES_EXTENSIONS <= set(extensions):
            raise ValueError("database readback is missing required PostgreSQL extensions")
        object.__setattr__(self, "extensions", extensions)
        role_checks = dict(self.runtime_role_checks)
        expected_role_checks = tuple(sorted(set(self.expected_runtime_role_checks)))
        if (
            not expected_role_checks
            or set(role_checks) != set(expected_role_checks)
            or not all(
                isinstance(name, str) and 0 < len(name) <= 128 and isinstance(value, bool) and value
                for name, value in role_checks.items()
            )
        ):
            raise ValueError("runtime role readback MUST contain only passing checks")
        object.__setattr__(self, "expected_runtime_role_checks", expected_role_checks)
        object.__setattr__(self, "runtime_role_checks", MappingProxyType(role_checks))
        for label, value in (
            ("ontology_release_digest", self.ontology_release_digest),
            ("catalog_digest", self.catalog_digest),
            ("defaults_digest", self.defaults_digest),
            ("role_manifest_digest", self.role_manifest_digest),
        ):
            if _SHA256.fullmatch(value) is None:
                raise ValueError(f"{label} MUST be a lowercase SHA-256")
        expected_digests = (
            self.expected_ontology_release_digest,
            self.expected_catalog_digest,
            self.expected_defaults_digest,
            self.expected_role_manifest_digest,
        )
        if any(_SHA256.fullmatch(value) is None for value in expected_digests):
            raise ValueError("expected semantic digests MUST be lowercase SHA-256 values")
        if expected_digests != (
            self.ontology_release_digest,
            self.catalog_digest,
            self.defaults_digest,
            self.role_manifest_digest,
        ):
            raise ValueError("database semantic readback does not match the sealed manifest")
        if not self.shadow_only:
            raise ValueError("subscription genesis semantic defaults MUST remain shadow-only")
        if not self.observer_distinct:
            raise ValueError("database semantic readback observer MUST be independent")

    def to_mapping(self) -> dict[str, object]:
        """Return sanitized database and semantic readiness evidence."""

        return {
            "expected_manifest_digest": canonical_digest(
                {
                    "legacy_head": self.expected_legacy_head,
                    "service_heads": dict(sorted(self.expected_service_heads.items())),
                    "runtime_role_checks": list(self.expected_runtime_role_checks),
                    "ontology_release_digest": self.expected_ontology_release_digest,
                    "catalog_digest": self.expected_catalog_digest,
                    "defaults_digest": self.expected_defaults_digest,
                    "role_manifest_digest": self.expected_role_manifest_digest,
                }
            ),
            "legacy_head": self.legacy_head,
            "service_heads": dict(sorted(self.service_heads.items())),
            "extensions": list(self.extensions),
            "runtime_role_checks": dict(sorted(self.runtime_role_checks.items())),
            "ontology_release_digest": self.ontology_release_digest,
            "catalog_digest": self.catalog_digest,
            "defaults_digest": self.defaults_digest,
            "role_manifest_digest": self.role_manifest_digest,
            "shadow_only": self.shadow_only,
            "observer_distinct": self.observer_distinct,
        }


@dataclass(frozen=True, slots=True)
class GenesisReadinessReceipt:
    """Sanitized proof set required before a run can transition to ready."""

    source_commit: str
    manifest_digest: str
    target_binding: str
    generated_at: str
    evidence_digests: Mapping[str, str]
    database_semantic: DatabaseSemanticReadback
    inventory_closure: InventoryClosure
    second_run: NoChangeReadback

    def __post_init__(self) -> None:
        if _COMMIT.fullmatch(self.source_commit) is None:
            raise ValueError("readiness source_commit MUST be a lowercase commit SHA")
        for label, value in (
            ("manifest_digest", self.manifest_digest),
            ("target_binding", self.target_binding),
        ):
            if _SHA256.fullmatch(value) is None:
                raise ValueError(f"readiness {label} MUST be a lowercase SHA-256")
        evidence_digests = dict(self.evidence_digests)
        if set(evidence_digests) != REQUIRED_READINESS_EVIDENCE:
            raise ValueError("readiness receipt evidence set is incomplete")
        if any(
            not isinstance(value, str) or _SHA256.fullmatch(value) is None
            for value in evidence_digests.values()
        ):
            raise ValueError("readiness evidence digests MUST be lowercase SHA-256 values")
        object.__setattr__(self, "evidence_digests", MappingProxyType(evidence_digests))
        if not isinstance(self.generated_at, str):
            raise ValueError("readiness generated_at MUST be ISO 8601")
        try:
            moment = datetime.fromisoformat(self.generated_at)
        except ValueError as exc:
            raise ValueError("readiness generated_at MUST be ISO 8601") from exc
        if moment.tzinfo is None:
            raise ValueError("readiness generated_at MUST be timezone-aware")
        if moment.utcoffset() != timedelta(0):
            raise ValueError("readiness generated_at MUST use UTC")
        if not self.inventory_closure.complete:
            raise ValueError(
                "readiness inventory closure is incomplete: "
                + ",".join(self.inventory_closure.blockers())
            )

    @property
    def digest(self) -> str:
        """Return the digest bound to the terminal provision event."""

        return canonical_digest(self.to_mapping())

    def to_mapping(self) -> dict[str, object]:
        """Return stable receipt content without tenant or resource identifiers."""

        return {
            "schema_version": "fdai.genesis-readiness-receipt.v1",
            "source_commit": self.source_commit,
            "manifest_digest": self.manifest_digest,
            "target_binding": self.target_binding,
            "generated_at": self.generated_at,
            "evidence_digests": dict(sorted(self.evidence_digests.items())),
            "database_semantic": self.database_semantic.to_mapping(),
            "inventory_closure": {
                "subscription_root": self.inventory_closure.subscription_root,
                "resource_type_filter": self.inventory_closure.resource_type_filter,
                "final_fence": self.inventory_closure.final_fence,
                "provider_coverage_complete": (self.inventory_closure.provider_coverage_complete),
                "truncated": self.inventory_closure.truncated,
                "active_generation_matches": self.inventory_closure.active_generation_matches,
                "overlay_open": self.inventory_closure.overlay_open,
                "child_sources_complete": self.inventory_closure.child_sources_complete,
                "observer_distinct": self.inventory_closure.observer_distinct,
            },
            "second_run": self.second_run.to_mapping(),
            "status": "verified",
        }
