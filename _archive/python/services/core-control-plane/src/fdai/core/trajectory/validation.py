"""Offline integrity validation and judge-only replay checks."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai.core.trajectory.models import TrajectoryEnvelope
from fdai.core.trajectory.serialization import canonical_json_bytes, envelope_from_mapping
from fdai.core.trajectory.versioning import TrajectoryVersionPolicy


class TrajectoryValidationError(ValueError):
    """Raised for incomplete, tampered, incompatible, or unreplayable exports."""


@dataclass(frozen=True, slots=True)
class ValidatedTrajectoryDataset:
    manifest: Mapping[str, object]
    records: tuple[TrajectoryEnvelope, ...]


def validate_export(
    dataset_path: Path,
    manifest_path: Path,
    *,
    version_policy: TrajectoryVersionPolicy | None = None,
    supported_redaction_policies: tuple[str, ...] = ("1.0",),
) -> ValidatedTrajectoryDataset:
    policy = version_policy or TrajectoryVersionPolicy()
    try:
        manifest_raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = _mapping(manifest_raw, "manifest")
        lines = dataset_path.read_bytes().splitlines(keepends=True)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TrajectoryValidationError("trajectory export is incomplete or unreadable") from exc
    policy.require_readable(_string(manifest, "schema_version"))
    if not lines:
        raise TrajectoryValidationError("trajectory export contains no records")
    dataset_hasher = hashlib.sha256()
    records: list[TrajectoryEnvelope] = []
    for line in lines:
        dataset_hasher.update(line)
        try:
            wrapper = _mapping(json.loads(line), "record wrapper")
            record_raw = _mapping(wrapper.get("record"), "record")
            checksum = _string(wrapper, "checksum")
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise TrajectoryValidationError("trajectory JSONL record is malformed") from exc
        if hashlib.sha256(canonical_json_bytes(record_raw)).hexdigest() != checksum:
            raise TrajectoryValidationError("trajectory record checksum mismatch")
        try:
            record = envelope_from_mapping(record_raw)
            policy.require_readable(record.schema_version)
            if record.redaction_policy_version not in supported_redaction_policies:
                raise TrajectoryValidationError(
                    "trajectory record redaction policy is not supported"
                )
            records.append(record)
        except TrajectoryValidationError:
            raise
        except (TypeError, ValueError) as exc:
            raise TrajectoryValidationError("trajectory record violates its schema") from exc
    if len(records) != _integer(manifest, "record_count"):
        raise TrajectoryValidationError("trajectory manifest record count mismatch")
    if dataset_hasher.hexdigest() != _string(manifest, "dataset_checksum"):
        raise TrajectoryValidationError("trajectory dataset checksum mismatch")
    outcomes = dict(Counter(record.completion_status.value for record in records))
    if outcomes != dict(_mapping(manifest.get("outcome_counts"), "outcome_counts")):
        raise TrajectoryValidationError("trajectory manifest outcome counts mismatch")
    _verify_manifest_checksum(manifest)
    replay_check(tuple(records))
    return ValidatedTrajectoryDataset(manifest=manifest, records=tuple(records))


def replay_check(records: tuple[TrajectoryEnvelope, ...]) -> None:
    """Reject broken source mapping and non-canonical dataset ordering."""

    keys = tuple((record.trace_id, record.correlation_id) for record in records)
    if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
        raise TrajectoryValidationError("trajectory dataset order or identity is invalid")
    for record in records:
        sources = set(record.source_records)
        if any(step.source not in sources for step in record.steps):
            raise TrajectoryValidationError("trajectory step source mapping is broken")


def _verify_manifest_checksum(manifest: Mapping[str, Any]) -> None:
    expected = _string(manifest, "manifest_checksum")
    material = {key: value for key, value in manifest.items() if key != "manifest_checksum"}
    if hashlib.sha256(canonical_json_bytes(material)).hexdigest() != expected:
        raise TrajectoryValidationError("trajectory manifest checksum mismatch")


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} MUST be an object")
    return value


def _string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ValueError(f"{key} MUST be a string")
    return item


def _integer(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"{key} MUST be an integer")
    return item


__all__ = [
    "TrajectoryValidationError",
    "ValidatedTrajectoryDataset",
    "replay_check",
    "validate_export",
]
