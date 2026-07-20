"""Canonical JSON mappings for trajectory records and manifests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
from typing import Any, Final

from fdai.core.trajectory.models import (
    DatasetGovernance,
    SourceRecordDigest,
    ToolStatistic,
    TrajectoryEnvelope,
    TrajectoryStep,
    TrajectoryStepKind,
    TrajectoryTerminalOutcome,
)

CANONICAL_JSON_SEPARATORS: Final = (",", ":")


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=CANONICAL_JSON_SEPARATORS,
        ensure_ascii=True,
    ).encode()


def envelope_to_mapping(envelope: TrajectoryEnvelope) -> dict[str, object]:
    return {
        "schema_version": envelope.schema_version,
        "trajectory_id": envelope.trajectory_id,
        "trace_id": envelope.trace_id,
        "correlation_id": envelope.correlation_id,
        "started_at": envelope.started_at.isoformat(),
        "completed_at": envelope.completed_at.isoformat(),
        "environment": envelope.environment,
        "evidence_profile": envelope.evidence_profile,
        "principal_scope_digest": envelope.principal_scope_digest,
        "model_capability_id": envelope.model_capability_id,
        "completion_status": envelope.completion_status.value,
        "redaction_policy_version": envelope.redaction_policy_version,
        "governance": {
            "purpose": envelope.governance.purpose,
            "retention_until": envelope.governance.retention_until.isoformat(),
            "deletion_due_at": envelope.governance.deletion_due_at.isoformat(),
            "legal_hold": envelope.governance.legal_hold,
            "legal_hold_ref": envelope.governance.legal_hold_ref,
        },
        "source_records": [asdict(source) for source in envelope.source_records],
        "steps": [
            {
                "sequence": step.sequence,
                "occurred_at": step.occurred_at.isoformat(),
                "kind": step.kind.value,
                "source": asdict(step.source),
                "payload": _json_value(step.payload),
            }
            for step in envelope.steps
        ],
        "tool_statistics": [asdict(item) for item in envelope.tool_statistics],
    }


def envelope_from_mapping(value: Mapping[str, Any]) -> TrajectoryEnvelope:
    governance_raw = _mapping(value, "governance")
    source_records = tuple(
        SourceRecordDigest(**dict(_as_mapping(item, "source_records item")))
        for item in _list(value, "source_records")
    )
    steps = tuple(
        _step_from_mapping(_as_mapping(item, "steps item")) for item in _list(value, "steps")
    )
    tool_statistics = tuple(
        ToolStatistic(**dict(_as_mapping(item, "tool_statistics item")))
        for item in _list(value, "tool_statistics")
    )
    return TrajectoryEnvelope(
        schema_version=_string(value, "schema_version"),
        trajectory_id=_string(value, "trajectory_id"),
        trace_id=_string(value, "trace_id"),
        correlation_id=_string(value, "correlation_id"),
        started_at=_timestamp(value, "started_at"),
        completed_at=_timestamp(value, "completed_at"),
        environment=_string(value, "environment"),
        evidence_profile=_string(value, "evidence_profile"),
        principal_scope_digest=_string(value, "principal_scope_digest"),
        model_capability_id=_string(value, "model_capability_id"),
        completion_status=TrajectoryTerminalOutcome(_string(value, "completion_status")),
        redaction_policy_version=_string(value, "redaction_policy_version"),
        governance=DatasetGovernance(
            purpose=_string(governance_raw, "purpose"),
            retention_until=_timestamp(governance_raw, "retention_until"),
            deletion_due_at=_timestamp(governance_raw, "deletion_due_at"),
            legal_hold=_boolean(governance_raw, "legal_hold"),
            legal_hold_ref=_optional_string(governance_raw, "legal_hold_ref"),
        ),
        source_records=source_records,
        steps=steps,
        tool_statistics=tool_statistics,
    )


def _step_from_mapping(value: Mapping[str, Any]) -> TrajectoryStep:
    source = SourceRecordDigest(**dict(_mapping(value, "source")))
    return TrajectoryStep(
        sequence=_integer(value, "sequence"),
        occurred_at=_timestamp(value, "occurred_at"),
        kind=TrajectoryStepKind(_string(value, "kind")),
        source=source,
        payload=dict(_mapping(value, "payload")),
    )


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return _as_mapping(value.get(key), key)


def _as_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} MUST be an object")
    return value


def _list(value: Mapping[str, Any], key: str) -> list[object]:
    item = value.get(key)
    if not isinstance(item, list):
        raise ValueError(f"{key} MUST be an array")
    return item


def _string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ValueError(f"{key} MUST be a string")
    return item


def _optional_string(value: Mapping[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is not None and not isinstance(item, str):
        raise ValueError(f"{key} MUST be a string or null")
    return item


def _integer(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"{key} MUST be an integer")
    return item


def _boolean(value: Mapping[str, Any], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise ValueError(f"{key} MUST be a boolean")
    return item


def _timestamp(value: Mapping[str, Any], key: str) -> datetime:
    return datetime.fromisoformat(_string(value, key))


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_json_value(child) for child in value]
    return value


__all__ = [
    "CANONICAL_JSON_SEPARATORS",
    "canonical_json_bytes",
    "envelope_from_mapping",
    "envelope_to_mapping",
]
