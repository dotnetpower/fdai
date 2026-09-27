"""Bounded frozen evidence input for the deployed catalog-review trigger."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fdai.core.case_history import (
    CaseKind,
    FailureFingerprint,
    OperationalCaseInput,
    OperationalEvidenceSourceKind,
    OperationalOutcomeClass,
    OperationalReceiptFact,
    OperationalReceiptType,
)

_MAX_MANIFEST_BYTES = 64 * 1024
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "scenario_id",
        "fdai_revision",
        "scenario_set_version",
        "reviewed_at",
        "action_type",
        "resource_type",
        "failure_mechanism",
        "expected",
    }
)


def load_frozen_review_manifest(path: Path) -> tuple[dict[str, object], str]:
    """Read one no-follow frozen manifest and return its exact content digest."""

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError("catalog review frozen manifest is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_MANIFEST_BYTES:
            raise RuntimeError("catalog review frozen manifest is invalid")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            content = stream.read(_MAX_MANIFEST_BYTES + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(content) > _MAX_MANIFEST_BYTES:
        raise RuntimeError("catalog review frozen manifest exceeds its byte limit")
    try:
        value = json.loads(content, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("catalog review frozen manifest is not canonical JSON") from exc
    if not isinstance(value, dict) or set(value) != _MANIFEST_FIELDS:
        raise RuntimeError("catalog review frozen manifest schema is invalid")
    _validate_manifest(value)
    return (
        {str(key): item for key, item in value.items()},
        hashlib.sha256(content).hexdigest(),
    )


def build_frozen_operational_cases(
    manifest: Mapping[str, object],
    *,
    manifest_digest: str,
    source_revision: str,
) -> tuple[OperationalCaseInput, ...]:
    """Build two immutable frozen cases for Huginn and Muninn to materialize."""

    if _REVISION.fullmatch(source_revision) is None:
        raise RuntimeError("catalog review trigger source revision is invalid")
    reviewed_at = datetime.fromisoformat(
        str(manifest["reviewed_at"]).replace("Z", "+00:00")
    ).astimezone(UTC)
    fingerprint = FailureFingerprint(
        resource_type=str(manifest["resource_type"]),
        failure_mechanism=str(manifest["failure_mechanism"]),
        symptom_codes=("frozen-review",),
        topology_roles=("candidate", "target"),
        ownership_shape=("review-only",),
    )
    cases: list[OperationalCaseInput] = []
    for outcome in (OperationalOutcomeClass.SUCCESS, OperationalOutcomeClass.ROLLBACK):
        identity = hashlib.sha256(
            f"{manifest_digest}:{source_revision}:{outcome.value}".encode()
        ).hexdigest()
        response_status = "verified" if outcome is OperationalOutcomeClass.SUCCESS else "mismatch"
        receipts = (
            _receipt(
                OperationalReceiptType.AUDIT,
                identity,
                "audit",
                reviewed_at,
                (("event_type", "catalog.review"), ("decision", "hil"), ("mode", "enforce")),
            ),
            _receipt(
                OperationalReceiptType.ACTION,
                identity,
                "action",
                reviewed_at,
                (
                    ("action_type", str(manifest["action_type"])),
                    ("execution_outcome", outcome.value),
                    ("dry_run_digest", manifest_digest),
                    ("terminal_receipt_digest", identity),
                ),
            ),
            _receipt(
                OperationalReceiptType.RESPONSE_OUTCOME,
                identity,
                "response",
                reviewed_at,
                (
                    ("label", response_status),
                    ("verification_status", response_status),
                    ("execution_outcome", outcome.value),
                    ("rollback_succeeded", outcome is OperationalOutcomeClass.ROLLBACK),
                    ("recurrence", False),
                ),
            ),
        )
        cases.append(
            OperationalCaseInput(
                case_identity_digest=identity,
                kind=CaseKind.ACTION,
                correlation_digest=fingerprint.digest,
                purpose="catalog-review",
                access_scope_digest=hashlib.sha256(
                    f"{manifest_digest}:catalog-review".encode()
                ).hexdigest(),
                redaction_policy_version="1.0.0",
                event_time_cutoff=reviewed_at,
                failure_fingerprint=fingerprint,
                action_type=str(manifest["action_type"]),
                outcome_class=outcome,
                evidence_refs=(manifest_digest, identity),
                receipts=receipts,
                fdai_revision=source_revision,
                scenario_set_version=str(manifest["scenario_set_version"]),
                source_kind=OperationalEvidenceSourceKind.FROZEN_BENCHMARK,
                source_identity_digest=manifest_digest,
                source_synthetic=True,
                evidence_complete=True,
                conflict_digests=(),
            )
        )
    return tuple(cases)


def _receipt(
    receipt_type: OperationalReceiptType,
    identity: str,
    suffix: str,
    occurred_at: datetime,
    facts: tuple[tuple[str, str | bool | int], ...],
) -> OperationalReceiptFact:
    return OperationalReceiptFact(
        receipt_type=receipt_type,
        receipt_digest=hashlib.sha256(f"{identity}:{suffix}".encode()).hexdigest(),
        occurred_at=occurred_at,
        facts=facts,
    )


def _validate_manifest(value: Mapping[str, object]) -> None:
    if value.get("schema_version") != "1.0.0":
        raise RuntimeError("catalog review frozen manifest version is unsupported")
    for key in ("scenario_id", "scenario_set_version", "action_type", "resource_type"):
        item = value.get(key)
        if not isinstance(item, str) or _IDENTIFIER.fullmatch(item) is None:
            raise RuntimeError("catalog review frozen manifest identity is invalid")
    prior_revision = value.get("fdai_revision")
    if not isinstance(prior_revision, str) or _REVISION.fullmatch(prior_revision) is None:
        raise RuntimeError("catalog review frozen manifest revision is invalid")
    mechanism = value.get("failure_mechanism")
    if not isinstance(mechanism, str) or not mechanism or len(mechanism) > 256:
        raise RuntimeError("catalog review frozen failure mechanism is invalid")
    reviewed_at = value.get("reviewed_at")
    if not isinstance(reviewed_at, str):
        raise RuntimeError("catalog review frozen review time is invalid")
    try:
        parsed = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("catalog review frozen review time is invalid") from exc
    if parsed.tzinfo is None:
        raise RuntimeError("catalog review frozen review time is invalid")
    expected = value.get("expected")
    if (
        not isinstance(expected, Mapping)
        or expected.get("immutable_cases") != 2
        or expected.get("catalog_reviews") != 1
        or expected.get("mode_before_review") != "shadow"
    ):
        raise RuntimeError("catalog review frozen expectations are invalid")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise RuntimeError("catalog review frozen manifest contains duplicate keys")
        value[key] = item
    return value


__all__ = ["build_frozen_operational_cases", "load_frozen_review_manifest"]
