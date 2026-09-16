"""Strict serialization and filesystem boundary for ontology shadow evidence."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fdai.rule_catalog.pipeline.distill.ontology_evaluation import (
    ChangeRiskClass,
    ShadowReviewEvidenceBatch,
    ShadowReviewOutcome,
)

MAX_MANIFEST_BYTES = 1024 * 1024
MAX_BATCH_BYTES = 16 * 1024 * 1024


def encode_batch(batch: ShadowReviewEvidenceBatch) -> bytes:
    return json.dumps(
        {
            "schema_version": "1.0.0",
            "fdai_revision": batch.fdai_revision,
            "ontology_release": batch.ontology_release,
            "binding_digest": batch.binding_digest,
            "policy_digest": batch.policy_digest,
            "sealed_at": batch.sealed_at.astimezone(UTC).isoformat(),
            "source_receipt_digest": batch.source_receipt_digest,
            "outcomes": [
                _outcome_mapping(item)
                for item in sorted(batch.outcomes, key=lambda value: value.outcome_id)
            ],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def manifest_mapping(batch: ShadowReviewEvidenceBatch, batch_name: str) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "batch": {
            "path": batch_name,
            "content_digest": batch.content_digest,
            "fdai_revision": batch.fdai_revision,
            "ontology_release": batch.ontology_release,
            "binding_digest": batch.binding_digest,
            "policy_digest": batch.policy_digest,
        },
        "source_receipt_digest": batch.source_receipt_digest,
        "review_receipt_digests": sorted(item.review_receipt_digest for item in batch.outcomes),
    }


def decode_batch(text: str) -> ShadowReviewEvidenceBatch:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("ontology shadow evidence batch is not valid JSON") from exc
    raw = object_value(value, "batch")
    exact_fields(
        raw,
        {
            "schema_version",
            "fdai_revision",
            "ontology_release",
            "binding_digest",
            "policy_digest",
            "sealed_at",
            "source_receipt_digest",
            "outcomes",
        },
        "batch",
    )
    if raw["schema_version"] != "1.0.0":
        raise ValueError("unsupported ontology shadow evidence batch")
    return ShadowReviewEvidenceBatch(
        fdai_revision=revision_text(raw, "fdai_revision"),
        ontology_release=digest_text(raw, "ontology_release"),
        binding_digest=digest_text(raw, "binding_digest"),
        policy_digest=digest_text(raw, "policy_digest"),
        sealed_at=timestamp(raw, "sealed_at"),
        source_receipt_digest=digest_text(raw, "source_receipt_digest"),
        outcomes=tuple(_decode_outcome(item) for item in object_list(raw, "outcomes")),
    )


def publish_exclusive(path: Path, content: bytes, *, kind: str) -> None:
    """Atomically publish content-addressed evidence, allowing identical retries."""
    if path.exists():
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"ontology shadow evidence {kind} path is not a plain file")
        if path.read_bytes() == content:
            return
        raise ValueError(f"ontology shadow evidence {kind} digest path has different content")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_bounded_regular_file(path: Path, max_bytes: int) -> str:
    """Read one regular non-symlink evidence file under an exact byte ceiling."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("ontology shadow evidence MUST be a regular file") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("ontology shadow evidence MUST be a regular file")
        if metadata.st_size > max_bytes:
            raise ValueError("ontology shadow evidence exceeds its byte limit")
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            descriptor = -1
            text = stream.read(max_bytes + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(text.encode("utf-8")) > max_bytes:
        raise ValueError("ontology shadow evidence exceeds its byte limit")
    return text


def bounded_batch_path(base: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError("ontology shadow batch path MUST be relative to its manifest")
    resolved = (base / candidate).resolve(strict=True)
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError("ontology shadow batch path escapes its manifest directory") from exc
    return resolved


def object_value(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"ontology shadow evidence {name} MUST be an object")
    return value


def exact_fields(raw: Mapping[str, Any], expected: set[str], name: str) -> None:
    if set(raw) != expected:
        raise ValueError(f"ontology shadow evidence {name} fields do not match schema")


def text_value(raw: Mapping[str, Any], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"ontology shadow evidence {name} MUST be non-empty text")
    return value


def revision_text(raw: Mapping[str, Any], name: str) -> str:
    value = text_value(raw, name)
    invalid_character = any(character not in "0123456789abcdef" for character in value)
    if len(value) not in {40, 64} or invalid_character:
        raise ValueError(f"ontology shadow evidence {name} MUST be an immutable revision")
    return value


def digest_text(raw: Mapping[str, Any], name: str) -> str:
    return digest_value(text_value(raw, name))


def digest_value(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("ontology shadow evidence digest MUST be lowercase SHA-256")
    return value


def timestamp(raw: Mapping[str, Any], name: str) -> datetime:
    value = text_value(raw, name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"ontology shadow evidence {name} MUST be RFC 3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"ontology shadow evidence {name} MUST be timezone-aware")
    return parsed.astimezone(UTC)


def object_list(raw: Mapping[str, Any], name: str) -> tuple[dict[str, Any], ...]:
    value = raw.get(name)
    if not isinstance(value, list):
        raise ValueError(f"ontology shadow evidence {name} MUST be an array")
    return tuple(object_value(item, name) for item in value)


def aware_now(clock: object) -> datetime:
    value = clock()  # type: ignore[operator]
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("ontology shadow evidence clock MUST return an aware datetime")
    return value.astimezone(UTC)


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _outcome_mapping(outcome: ShadowReviewOutcome) -> dict[str, object]:
    return {
        "outcome_id": outcome.outcome_id,
        "proposal_digest": outcome.proposal_digest,
        "observed_at": outcome.observed_at.astimezone(UTC).isoformat(),
        "audit_sequence": outcome.audit_sequence,
        "review_receipt_digest": outcome.review_receipt_digest,
        "reviewer_id": outcome.reviewer_id,
        "requester_id": outcome.requester_id,
        "fdai_revision": outcome.fdai_revision,
        "ontology_release": outcome.ontology_release,
        "binding_digest": outcome.binding_digest,
        "reviewed": outcome.reviewed,
        "risk_class": outcome.risk_class.value,
        "correct": outcome.correct,
        "authority_violation": outcome.authority_violation,
        "policy_escape": outcome.policy_escape,
        "wrong_target": outcome.wrong_target,
        "unverified_truth": outcome.unverified_truth,
    }


def _decode_outcome(value: object) -> ShadowReviewOutcome:
    raw = object_value(value, "outcome")
    exact_fields(
        raw,
        {
            "outcome_id",
            "proposal_digest",
            "observed_at",
            "audit_sequence",
            "review_receipt_digest",
            "reviewer_id",
            "requester_id",
            "fdai_revision",
            "ontology_release",
            "binding_digest",
            "reviewed",
            "risk_class",
            "correct",
            "authority_violation",
            "policy_escape",
            "wrong_target",
            "unverified_truth",
        },
        "outcome",
    )
    return ShadowReviewOutcome(
        outcome_id=digest_text(raw, "outcome_id"),
        proposal_digest=digest_text(raw, "proposal_digest"),
        observed_at=timestamp(raw, "observed_at"),
        audit_sequence=_integer(raw, "audit_sequence"),
        review_receipt_digest=digest_text(raw, "review_receipt_digest"),
        reviewer_id=text_value(raw, "reviewer_id"),
        requester_id=text_value(raw, "requester_id"),
        fdai_revision=revision_text(raw, "fdai_revision"),
        ontology_release=digest_text(raw, "ontology_release"),
        binding_digest=digest_text(raw, "binding_digest"),
        reviewed=_boolean(raw, "reviewed"),
        risk_class=ChangeRiskClass(text_value(raw, "risk_class")),
        correct=_boolean(raw, "correct"),
        authority_violation=_boolean(raw, "authority_violation"),
        policy_escape=_boolean(raw, "policy_escape"),
        wrong_target=_boolean(raw, "wrong_target"),
        unverified_truth=_boolean(raw, "unverified_truth"),
    )


def _integer(raw: Mapping[str, Any], name: str) -> int:
    value = raw.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"ontology shadow evidence {name} MUST be an integer")
    return value


def _boolean(raw: Mapping[str, Any], name: str) -> bool:
    value = raw.get(name)
    if not isinstance(value, bool):
        raise ValueError(f"ontology shadow evidence {name} MUST be boolean")
    return value


__all__ = [
    "MAX_BATCH_BYTES",
    "MAX_MANIFEST_BYTES",
    "aware_now",
    "bounded_batch_path",
    "decode_batch",
    "digest_text",
    "digest_value",
    "encode_batch",
    "exact_fields",
    "manifest_mapping",
    "object_list",
    "object_value",
    "publish_exclusive",
    "read_bounded_regular_file",
    "revision_text",
    "sha256",
    "text_value",
]
