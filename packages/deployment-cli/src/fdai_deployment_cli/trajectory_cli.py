"""Offline trajectory dataset and manifest validation for fdaictl."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from fdai_deployment_cli.cli_help import command, command_group

TRAJECTORY_SCHEMA_VERSION = "1.0"
SUPPORTED_REDACTION_POLICIES = frozenset({"1.0"})
_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
_DIGEST_CHARS = frozenset("0123456789abcdef")
_ALLOWED_OUTCOMES = frozenset(
    {
        "completed",
        "failed",
        "cancelled",
        "timed_out",
        "abstained",
        "ambiguous",
    }
)
_ALLOWED_STEP_KINDS = frozenset(
    {
        "normalized_input_reference",
        "routing_decision",
        "assistant_output",
        "tool_request",
        "tool_receipt",
        "action_request",
        "action_receipt",
        "verifier_result",
        "risk_result",
        "approval",
        "terminal_outcome",
        "rollback_state",
    }
)
_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "auth_header",
        "authorization",
        "chain_of_thought",
        "credential",
        "credentials",
        "hidden_reasoning",
        "prompt",
        "raw_attachment",
        "raw_cloud_payload",
        "raw_output",
        "raw_prompt",
        "token",
        "tokens",
    }
)


def canonical_json_bytes(value: object) -> bytes:
    """Serialize JSON with sorted keys and compact ASCII separators."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def register_trajectory_commands(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register offline trajectory dataset validation commands."""
    group = command(
        commands,
        "trajectory",
        "Validate offline governed trajectory dataset and manifest artifacts",
        epilog=(
            "Offline validation only: fdaictl trajectory validate --help\n"
            "Validation grants no training, promotion, or execution authority."
        ),
    )
    operations = command_group(group)
    validate = command(
        operations,
        "validate",
        "Verify dataset JSONL checksums, manifest integrity, purpose, access scope, and replay order",
    )
    validate.add_argument(
        "--dataset",
        type=Path,
        required=True,
        help="Path to the exported .trajectory.jsonl artifact",
    )
    validate.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to the exported .manifest.json artifact",
    )
    validate.add_argument(
        "--purpose",
        required=True,
        help="Expected governance purpose bound to the export",
    )
    validate.add_argument(
        "--access-scope",
        required=True,
        dest="access_scope",
        help="Expected 64-hex principal_scope_digest bound to the export",
    )
    validate.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Result format (default: text)",
    )
    validate.set_defaults(handler=validate_trajectory_command)


def validate_trajectory_artifacts(
    *,
    dataset_path: Path,
    manifest_path: Path,
    purpose: str,
    access_scope: str,
) -> dict[str, object]:
    """Validate trajectory JSONL and manifest artifacts offline and fail closed."""
    expected_purpose = purpose.strip()
    expected_scope = access_scope.strip()
    if not expected_purpose:
        raise ValueError("trajectory purpose must not be empty")
    if not _is_sha256_hex(expected_scope):
        raise ValueError("trajectory access-scope must be a 64-character lowercase hex digest")
    if dataset_path.is_symlink() or manifest_path.is_symlink():
        raise ValueError("trajectory dataset and manifest paths must not be symlinks")

    try:
        manifest_stat = manifest_path.stat()
        dataset_stat = dataset_path.stat()
    except OSError as exc:
        raise ValueError("trajectory export is incomplete or unreadable") from exc
    if manifest_stat.st_size > _MAX_ARTIFACT_BYTES or dataset_stat.st_size > _MAX_ARTIFACT_BYTES:
        raise ValueError("trajectory artifact exceeds 64 MiB limit")

    try:
        manifest_raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        lines = [
            line for line in dataset_path.read_bytes().splitlines(keepends=True) if line.strip()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("trajectory export is incomplete or unreadable") from exc

    manifest = _mapping(manifest_raw, "manifest")
    if _text(manifest, "schema_version") != TRAJECTORY_SCHEMA_VERSION:
        raise ValueError("trajectory manifest schema_version is not supported")

    manifest_purpose = _text(manifest, "purpose")
    if manifest_purpose != expected_purpose:
        raise ValueError("trajectory manifest purpose does not match requested purpose")

    manifest_scope = _text(manifest, "principal_scope_digest")
    if manifest_scope != expected_scope:
        raise ValueError("trajectory manifest access_scope does not match requested access-scope")

    _verify_manifest_checksum(manifest)
    if not lines:
        raise ValueError("trajectory export contains no records")

    dataset_hasher = hashlib.sha256()
    outcomes: Counter[str] = Counter()
    replay_keys: list[tuple[str, str]] = []
    record_count = 0

    for line in lines:
        dataset_hasher.update(line)
        try:
            wrapper = _mapping(json.loads(line), "record wrapper")
            record_raw = _mapping(wrapper.get("record"), "record")
            checksum = _text(wrapper, "checksum")
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise ValueError("trajectory JSONL record is malformed") from exc

        computed = hashlib.sha256(canonical_json_bytes(record_raw)).hexdigest()
        if computed != checksum:
            raise ValueError("trajectory record checksum mismatch")

        key, outcome = _validate_record(
            record_raw,
            expected_purpose=expected_purpose,
            expected_scope=expected_scope,
        )
        replay_keys.append(key)
        outcomes[outcome] += 1
        record_count += 1

    if record_count != _int_field(manifest, "record_count"):
        raise ValueError("trajectory manifest record count mismatch")
    if dataset_hasher.hexdigest() != _text(manifest, "dataset_checksum"):
        raise ValueError("trajectory dataset checksum mismatch")
    if dict(outcomes) != dict(_mapping(manifest.get("outcome_counts"), "outcome_counts")):
        raise ValueError("trajectory manifest outcome counts mismatch")
    if tuple(replay_keys) != tuple(sorted(replay_keys)) or len(replay_keys) != len(
        set(replay_keys)
    ):
        raise ValueError("trajectory dataset order or identity is invalid")

    return {
        "schema_version": "fdai.trajectory-validation.v1",
        "dataset_id": _text(manifest, "dataset_id"),
        "purpose": manifest_purpose,
        "principal_scope_digest": manifest_scope,
        "record_count": record_count,
        "outcome_counts": dict(sorted(outcomes.items())),
        "dataset_checksum": _text(manifest, "dataset_checksum"),
        "manifest_checksum": _text(manifest, "manifest_checksum"),
        "replay_verified": True,
        "training_authority": "none",
        "promotion_authority": "none",
    }


def validate_trajectory_command(args: argparse.Namespace) -> int:
    """CLI handler for `fdaictl trajectory validate`."""
    summary = validate_trajectory_artifacts(
        dataset_path=Path(args.dataset),
        manifest_path=Path(args.manifest),
        purpose=str(args.purpose),
        access_scope=str(args.access_scope),
    )
    if getattr(args, "output", "text") == "json":
        print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    else:
        print(
            f"trajectory valid: dataset_id={summary['dataset_id']} "
            f"records={summary['record_count']} "
            f"purpose={summary['purpose']} "
            f"replay_verified=true"
        )
    return 0


def _validate_record(
    record: Mapping[str, Any],
    *,
    expected_purpose: str,
    expected_scope: str,
) -> tuple[tuple[str, str], str]:
    if _text(record, "schema_version") != TRAJECTORY_SCHEMA_VERSION:
        raise ValueError("trajectory record schema_version is not supported")
    if _text(record, "redaction_policy_version") not in SUPPORTED_REDACTION_POLICIES:
        raise ValueError("trajectory record redaction policy is not supported")
    if _text(record, "principal_scope_digest") != expected_scope:
        raise ValueError("trajectory record access_scope does not match requested access-scope")

    governance = _mapping(record.get("governance"), "governance")
    if _text(governance, "purpose") != expected_purpose:
        raise ValueError("trajectory record purpose does not match requested purpose")
    retention_until = _timestamp(governance, "retention_until")
    deletion_due_at = _timestamp(governance, "deletion_due_at")
    if deletion_due_at < retention_until:
        raise ValueError("trajectory deletion_due_at must be >= retention_until")
    started_at = _timestamp(record, "started_at")
    completed_at = _timestamp(record, "completed_at")
    if completed_at < started_at:
        raise ValueError("trajectory completed_at must be >= started_at")

    outcome = _text(record, "completion_status")
    if outcome not in _ALLOWED_OUTCOMES:
        raise ValueError("trajectory record completion_status is invalid")

    trace_id = _text(record, "trace_id")
    correlation_id = _text(record, "correlation_id")
    _text(record, "trajectory_id")

    sources_raw = _list_field(record, "source_records")
    if not sources_raw:
        raise ValueError("trajectory record must declare source_records")
    sources: set[tuple[str, str, str]] = set()
    for item in sources_raw:
        src = _mapping(item, "source_record")
        digest = _text(src, "sha256")
        if not _is_sha256_hex(digest):
            raise ValueError("trajectory source_record sha256 is invalid")
        sources.add((_text(src, "record_type"), _text(src, "record_id"), digest))

    steps_raw = _list_field(record, "steps")
    if not steps_raw:
        raise ValueError("trajectory record must contain at least one step")
    sequences: list[int] = []
    for item in steps_raw:
        step = _mapping(item, "step")
        seq = _int_field(step, "sequence")
        sequences.append(seq)
        _timestamp(step, "occurred_at")
        if _text(step, "kind") not in _ALLOWED_STEP_KINDS:
            raise ValueError("trajectory step kind is invalid")
        step_src = _mapping(step.get("source"), "step.source")
        src_tuple = (
            _text(step_src, "record_type"),
            _text(step_src, "record_id"),
            _text(step_src, "sha256"),
        )
        if src_tuple not in sources:
            raise ValueError("trajectory step source mapping is broken")
        payload = _mapping(step.get("payload"), "step.payload")
        _reject_forbidden_keys(payload)
    if sequences != list(range(len(sequences))):
        raise ValueError("trajectory step sequences must be contiguous from 0")

    return (trace_id, correlation_id), outcome


def _reject_forbidden_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in _FORBIDDEN_PAYLOAD_KEYS:
                raise ValueError("trajectory step payload contains forbidden key")
            _reject_forbidden_keys(child)
    elif isinstance(value, list):
        for item in value:
            _reject_forbidden_keys(item)


def _verify_manifest_checksum(manifest: Mapping[str, Any]) -> None:
    expected = _text(manifest, "manifest_checksum")
    material = {key: value for key, value in manifest.items() if key != "manifest_checksum"}
    if hashlib.sha256(canonical_json_bytes(material)).hexdigest() != expected:
        raise ValueError("trajectory manifest checksum mismatch")


def _is_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(ch in _DIGEST_CHARS for ch in value)


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _list_field(mapping: Mapping[str, Any], key: str) -> list[object]:
    value = mapping.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a JSON array")
    return value


def _text(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _int_field(mapping: Mapping[str, Any], key: str) -> int:
    value = mapping.get(key)
    if type(value) is not int:
        raise ValueError(f"{key} must be an integer")
    return value


def _timestamp(mapping: Mapping[str, Any], key: str) -> datetime:
    raw = _text(mapping, key)
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{key} must include timezone offset")
    return parsed


__all__ = [
    "register_trajectory_commands",
    "validate_trajectory_artifacts",
    "validate_trajectory_command",
]
