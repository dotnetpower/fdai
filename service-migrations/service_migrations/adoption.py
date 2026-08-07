"""Validate explicit baseline-stamp adoption records for service branches."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from service_migrations.inventory import LegacyInventory


@dataclass(frozen=True)
class AdoptionManifest:
    """One service's verified bridge from the legacy lineage to its baseline."""

    service_id: str
    baseline_revision: str
    service_version_table: str
    legacy_version_table: str
    required_legacy_head: str
    legacy_revision_count: int
    rollback_strategy: str


def load_adoption_manifest(
    path: Path,
    *,
    service_id: str,
    inventory: LegacyInventory,
) -> AdoptionManifest:
    """Load one adoption record and reject stale or incomplete rollback metadata."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("service_id") != service_id:
        raise ValueError(f"{path}: adoption service_id must be {service_id}")
    if raw.get("adoption_method") != "verify-legacy-head-then-stamp":
        raise ValueError(f"{path}: unsupported adoption method")
    legacy = raw.get("legacy")
    rollback = raw.get("rollback")
    if not isinstance(legacy, dict) or not isinstance(rollback, dict):
        raise ValueError(f"{path}: legacy and rollback objects are required")
    required_head = legacy.get("required_head")
    revision_count = legacy.get("revision_count")
    if required_head != inventory.heads[0] or revision_count != len(inventory.down_revisions):
        raise ValueError(f"{path}: adoption legacy inventory is stale")
    required_rollback = {
        "required": True,
        "strategy": "delete-service-version-row",
        "preserves_legacy_schema": True,
        "requires_reference": True,
    }
    if rollback != required_rollback:
        raise ValueError(f"{path}: exact rollback metadata is required")
    string_fields = {
        "baseline_revision": raw.get("baseline_revision"),
        "service_version_table": raw.get("service_version_table"),
        "legacy_version_table": legacy.get("version_table"),
    }
    if not all(isinstance(value, str) and value for value in string_fields.values()):
        raise ValueError(f"{path}: adoption revision and version tables must be non-empty")
    return AdoptionManifest(
        service_id=service_id,
        baseline_revision=cast(str, string_fields["baseline_revision"]),
        service_version_table=cast(str, string_fields["service_version_table"]),
        legacy_version_table=cast(str, string_fields["legacy_version_table"]),
        required_legacy_head=cast(str, required_head),
        legacy_revision_count=cast(int, revision_count),
        rollback_strategy=cast(str, rollback["strategy"]),
    )
