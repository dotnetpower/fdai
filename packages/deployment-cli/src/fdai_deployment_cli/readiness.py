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
class GenesisReadinessReceipt:
    """Sanitized proof set required before a run can transition to ready."""

    source_commit: str
    manifest_digest: str
    target_binding: str
    generated_at: str
    evidence_digests: Mapping[str, str]
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
