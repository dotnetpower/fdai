"""Evaluate archive restore samples, retention holds, and history coverage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from fdai.core.ontology_platform.archive_manifest import (
    ArchiveManifest,
    ArchiveVerificationReceipt,
)


class RetentionHoldKind(StrEnum):
    """Distinguish policy retention from legal holds."""

    RETENTION = "retention"
    LEGAL = "legal"


class ArchiveHistoryStatus(StrEnum):
    """Distinguish archived history from proven absence and unknown coverage."""

    ARCHIVED = "archived"
    ABSENT = "absent"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ArchiveRestoreReceipt:
    """Record one bounded restore sample and its exact manifest lineage."""

    manifest_digest: str
    verification_receipt_digest: str
    sampled_partition_digests: tuple[str, ...]
    restored_object_count: int
    restored_relationship_count: int
    passed: bool
    reason_codes: tuple[str, ...]
    sampled_at: datetime
    digest: str


@dataclass(frozen=True, slots=True)
class RetentionHold:
    """Block source deletion for one exact archive manifest."""

    hold_id: str
    manifest_digest: str
    kind: RetentionHoldKind
    starts_at: datetime
    ends_at: datetime | None

    def __post_init__(self) -> None:
        if not self.hold_id or len(self.hold_id) > 256:
            raise ValueError("retention hold_id MUST be bounded and non-empty")
        _digest(self.manifest_digest, "retention hold manifest digest")
        _aware(self.starts_at, "retention hold starts_at")
        if self.ends_at is not None:
            _aware(self.ends_at, "retention hold ends_at")
            if self.ends_at <= self.starts_at:
                raise ValueError("retention hold interval MUST be positive")
        if self.kind is RetentionHoldKind.LEGAL and self.ends_at is not None:
            raise ValueError("legal hold MUST remain open until explicitly released")


@dataclass(frozen=True, slots=True)
class RetentionEvaluationReceipt:
    """Record all active deletion holds at one trusted time."""

    manifest_digest: str
    evaluated_at: datetime
    blocking_hold_ids: tuple[str, ...]
    permitted: bool
    digest: str


@dataclass(frozen=True, slots=True)
class ArchiveIndexEntry:
    """Index one verified archive interval without restoring its content."""

    manifest_digest: str
    interval_start: datetime
    interval_end: datetime

    def __post_init__(self) -> None:
        _digest(self.manifest_digest, "archive index manifest digest")
        _aware(self.interval_start, "archive index interval_start")
        _aware(self.interval_end, "archive index interval_end")
        if self.interval_end <= self.interval_start:
            raise ValueError("archive index interval MUST be positive")


@dataclass(frozen=True, slots=True)
class ArchiveCoverageIndex:
    """State whether an indexed time range can prove archive absence."""

    coverage_start: datetime
    coverage_end: datetime
    complete: bool
    entries: tuple[ArchiveIndexEntry, ...]

    def __post_init__(self) -> None:
        _aware(self.coverage_start, "archive coverage_start")
        _aware(self.coverage_end, "archive coverage_end")
        if self.coverage_end <= self.coverage_start:
            raise ValueError("archive coverage interval MUST be positive")
        if any(
            entry.interval_start < self.coverage_start or entry.interval_end > self.coverage_end
            for entry in self.entries
        ):
            raise ValueError("archive index entry MUST be contained by coverage")


@dataclass(frozen=True, slots=True)
class ArchiveCoverageReceipt:
    """Persist one content-addressed archive index coverage summary."""

    index: ArchiveCoverageIndex
    recorded_at: datetime
    digest: str


def evaluate_restore_sample(
    manifest: ArchiveManifest,
    verification: ArchiveVerificationReceipt,
    *,
    sampled_partition_digests: tuple[str, ...],
    observed_partition_digests: tuple[str, ...],
    restored_object_count: int,
    restored_relationship_count: int,
    failure_code: str | None,
    sampled_at: datetime,
) -> ArchiveRestoreReceipt:
    """Evaluate a bounded sample without converting a failed restore to coverage."""

    _aware(sampled_at, "archive restore sampled_at")
    if not sampled_partition_digests:
        raise ValueError("archive restore sample MUST select at least one partition")
    if restored_object_count < 0 or restored_relationship_count < 0:
        raise ValueError("archive restore counts MUST NOT be negative")
    expected = {item.content_digest: item for item in manifest.source_partitions}
    reasons: list[str] = []
    if not verification.verified or verification.manifest_digest != manifest.digest:
        reasons.append("manifest_unverified")
    if any(value not in expected for value in sampled_partition_digests):
        reasons.append("sample_partition_unknown")
    if tuple(sorted(observed_partition_digests)) != tuple(sorted(sampled_partition_digests)):
        reasons.append("restored_partition_digest_mismatch")
    expected_objects = sum(
        expected[value].object_count for value in sampled_partition_digests if value in expected
    )
    expected_relationships = sum(
        expected[value].relationship_count
        for value in sampled_partition_digests
        if value in expected
    )
    if (
        restored_object_count != expected_objects
        or restored_relationship_count != expected_relationships
    ):
        reasons.append("restored_count_mismatch")
    if failure_code is not None:
        reasons.append("restore_failed")
    body = {
        "manifest_digest": manifest.digest,
        "verification_receipt_digest": verification.digest,
        "sampled_partition_digests": sorted(sampled_partition_digests),
        "restored_object_count": restored_object_count,
        "restored_relationship_count": restored_relationship_count,
        "passed": not reasons,
        "reason_codes": reasons,
        "sampled_at": sampled_at.astimezone(UTC).isoformat(),
    }
    return ArchiveRestoreReceipt(
        manifest_digest=manifest.digest,
        verification_receipt_digest=verification.digest,
        sampled_partition_digests=tuple(sorted(sampled_partition_digests)),
        restored_object_count=restored_object_count,
        restored_relationship_count=restored_relationship_count,
        passed=not reasons,
        reason_codes=tuple(reasons),
        sampled_at=sampled_at,
        digest=_sha256(body),
    )


def evaluate_retention_holds(
    manifest: ArchiveManifest,
    holds: tuple[RetentionHold, ...],
    *,
    evaluated_at: datetime,
) -> RetentionEvaluationReceipt:
    """Fail deletion closed while any retention or legal hold is active."""

    _aware(evaluated_at, "retention evaluation time")
    blocking = tuple(
        sorted(
            hold.hold_id
            for hold in holds
            if hold.manifest_digest == manifest.digest
            and hold.starts_at <= evaluated_at
            and (hold.ends_at is None or evaluated_at < hold.ends_at)
        )
    )
    body = {
        "manifest_digest": manifest.digest,
        "evaluated_at": evaluated_at.astimezone(UTC).isoformat(),
        "blocking_hold_ids": blocking,
        "permitted": not blocking,
    }
    return RetentionEvaluationReceipt(
        manifest_digest=manifest.digest,
        evaluated_at=evaluated_at,
        blocking_hold_ids=blocking,
        permitted=not blocking,
        digest=_sha256(body),
    )


def locate_archive_history(
    index: ArchiveCoverageIndex,
    *,
    interval_start: datetime,
    interval_end: datetime,
) -> ArchiveHistoryStatus:
    """Return archived, absent, or unavailable without inferring false absence."""

    _aware(interval_start, "archive query interval_start")
    _aware(interval_end, "archive query interval_end")
    if interval_end <= interval_start:
        raise ValueError("archive query interval MUST be positive")
    if any(
        entry.interval_start <= interval_start and entry.interval_end >= interval_end
        for entry in index.entries
    ):
        return ArchiveHistoryStatus.ARCHIVED
    if (
        index.complete
        and index.coverage_start <= interval_start
        and index.coverage_end >= interval_end
    ):
        return ArchiveHistoryStatus.ABSENT
    return ArchiveHistoryStatus.UNAVAILABLE


def build_archive_coverage_receipt(
    index: ArchiveCoverageIndex,
    *,
    recorded_at: datetime,
) -> ArchiveCoverageReceipt:
    """Content-address one archive index snapshot for durable replay."""

    _aware(recorded_at, "archive coverage recorded_at")
    body = {
        "coverage_start": index.coverage_start.astimezone(UTC).isoformat(),
        "coverage_end": index.coverage_end.astimezone(UTC).isoformat(),
        "complete": index.complete,
        "entries": [
            {
                "manifest_digest": item.manifest_digest,
                "interval_start": item.interval_start.astimezone(UTC).isoformat(),
                "interval_end": item.interval_end.astimezone(UTC).isoformat(),
            }
            for item in index.entries
        ],
        "recorded_at": recorded_at.astimezone(UTC).isoformat(),
    }
    return ArchiveCoverageReceipt(
        index=index,
        recorded_at=recorded_at,
        digest=_sha256(body),
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _digest(value: str, name: str) -> None:
    if (
        len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{name} MUST be a canonical SHA-256 digest")


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} MUST be timezone-aware")


__all__ = [
    "ArchiveCoverageIndex",
    "ArchiveCoverageReceipt",
    "ArchiveHistoryStatus",
    "ArchiveIndexEntry",
    "ArchiveRestoreReceipt",
    "RetentionEvaluationReceipt",
    "RetentionHold",
    "RetentionHoldKind",
    "build_archive_coverage_receipt",
    "evaluate_restore_sample",
    "evaluate_retention_holds",
    "locate_archive_history",
]
