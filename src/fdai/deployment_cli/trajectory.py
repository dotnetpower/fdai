"""Offline trajectory dataset validation for deployment administrators."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from fdai.core.trajectory import (
    TrajectoryValidationError,
    trajectory_scope_digest,
    validate_export,
)


@dataclass(frozen=True, slots=True)
class TrajectoryValidationReport:
    dataset_id: str
    record_count: int
    dataset_checksum: str
    manifest_checksum: str
    valid: bool = True

    def to_json(self) -> str:
        return json.dumps(
            {
                "dataset_checksum": self.dataset_checksum,
                "dataset_id": self.dataset_id,
                "manifest_checksum": self.manifest_checksum,
                "record_count": self.record_count,
                "valid": self.valid,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


def validate_trajectory_dataset(
    *,
    dataset_path: Path,
    manifest_path: Path,
    purpose: str,
    access_scope: str,
) -> TrajectoryValidationReport:
    if not purpose.strip() or not access_scope.strip():
        raise TrajectoryValidationError("purpose and access_scope are required")
    validated = validate_export(dataset_path, manifest_path)
    if validated.manifest.get("purpose") != purpose:
        raise TrajectoryValidationError("trajectory manifest purpose mismatch")
    expected_scope_digest = trajectory_scope_digest(access_scope)
    if validated.manifest.get("principal_scope_digest") != expected_scope_digest:
        raise TrajectoryValidationError("trajectory manifest access scope mismatch")
    return TrajectoryValidationReport(
        dataset_id=str(validated.manifest["dataset_id"]),
        record_count=_manifest_count(validated.manifest.get("record_count")),
        dataset_checksum=str(validated.manifest["dataset_checksum"]),
        manifest_checksum=str(validated.manifest["manifest_checksum"]),
    )


def _manifest_count(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TrajectoryValidationError("trajectory manifest record_count is invalid")
    return value


__all__ = ["TrajectoryValidationReport", "validate_trajectory_dataset"]
