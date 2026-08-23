"""Build and verify immutable operational-history archive manifests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class ArchiveSourcePartition:
    """Describe one immutable source partition included in an archive."""

    partition_id: str
    content_digest: str
    interval_start: datetime
    interval_end: datetime
    object_count: int
    relationship_count: int
    schema_version: str
    ontology_release_digest: str
    complete: bool
    conflict_count: int = 0

    def __post_init__(self) -> None:
        if not self.partition_id or len(self.partition_id) > 256:
            raise ValueError("archive source partition_id MUST be bounded and non-empty")
        _digest(self.content_digest, "source partition content_digest")
        _digest(self.ontology_release_digest, "source partition ontology release")
        _aware(self.interval_start, "source partition interval_start")
        _aware(self.interval_end, "source partition interval_end")
        if self.interval_end <= self.interval_start:
            raise ValueError("archive source partition interval MUST be positive")
        if self.object_count < 0 or self.relationship_count < 0:
            raise ValueError("archive source partition counts MUST NOT be negative")
        if self.conflict_count < 0:
            raise ValueError("archive source partition conflict_count MUST NOT be negative")
        if not self.schema_version or len(self.schema_version) > 128:
            raise ValueError("archive source partition schema_version MUST be bounded")


@dataclass(frozen=True, slots=True)
class ArchiveManifest:
    """Pin one immutable archive object to exact source coverage and releases."""

    schema_version: str
    source_partitions: tuple[ArchiveSourcePartition, ...]
    covered_start: datetime
    covered_end: datetime
    object_count: int
    relationship_count: int
    source_schema_versions: tuple[str, ...]
    ontology_release_digests: tuple[str, ...]
    archive_content_digest: str
    compression_profile: str
    encryption_profile: str
    destination_class: str
    retention_class: str
    creation_receipt_digest: str
    created_at: datetime
    coverage_complete: bool
    digest: str


@dataclass(frozen=True, slots=True)
class ArchiveVerificationReceipt:
    """Record deterministic manifest and archive-content verification."""

    manifest_digest: str
    verified: bool
    reason_codes: tuple[str, ...]
    verified_at: datetime
    digest: str


def build_archive_manifest(
    partitions: tuple[ArchiveSourcePartition, ...],
    *,
    archive_content_digest: str,
    compression_profile: str,
    encryption_profile: str,
    destination_class: str,
    retention_class: str,
    creation_receipt_digest: str,
    created_at: datetime,
) -> ArchiveManifest:
    """Build a content-addressed manifest without treating gaps as absence."""

    if not partitions:
        raise ValueError("archive manifest requires at least one source partition")
    _digest(archive_content_digest, "archive content_digest")
    _digest(creation_receipt_digest, "archive creation receipt")
    _aware(created_at, "archive created_at")
    for name, value in (
        ("compression_profile", compression_profile),
        ("encryption_profile", encryption_profile),
        ("destination_class", destination_class),
        ("retention_class", retention_class),
    ):
        if not value or len(value) > 128:
            raise ValueError(f"archive {name} MUST be bounded and non-empty")
    ordered = tuple(sorted(partitions, key=lambda item: (item.interval_start, item.partition_id)))
    partition_ids = tuple(item.partition_id for item in ordered)
    if len(set(partition_ids)) != len(partition_ids):
        raise ValueError("archive source partition ids MUST be unique")
    for prior, current in zip(ordered, ordered[1:], strict=False):
        if current.interval_start < prior.interval_end:
            raise ValueError("archive source partition intervals MUST NOT overlap")
    coverage_complete = all(item.complete and item.conflict_count == 0 for item in ordered) and all(
        current.interval_start == prior.interval_end
        for prior, current in zip(ordered, ordered[1:], strict=False)
    )
    source_schema_versions = tuple(sorted({item.schema_version for item in ordered}))
    ontology_release_digests = tuple(sorted({item.ontology_release_digest for item in ordered}))
    body = {
        "schema_version": "1.0.0",
        "source_partitions": [_partition_body(item) for item in ordered],
        "covered_start": ordered[0].interval_start.astimezone(UTC).isoformat(),
        "covered_end": ordered[-1].interval_end.astimezone(UTC).isoformat(),
        "object_count": sum(item.object_count for item in ordered),
        "relationship_count": sum(item.relationship_count for item in ordered),
        "source_schema_versions": source_schema_versions,
        "ontology_release_digests": ontology_release_digests,
        "archive_content_digest": archive_content_digest,
        "compression_profile": compression_profile,
        "encryption_profile": encryption_profile,
        "destination_class": destination_class,
        "retention_class": retention_class,
        "creation_receipt_digest": creation_receipt_digest,
        "created_at": created_at.astimezone(UTC).isoformat(),
        "coverage_complete": coverage_complete,
    }
    return ArchiveManifest(
        schema_version="1.0.0",
        source_partitions=ordered,
        covered_start=ordered[0].interval_start,
        covered_end=ordered[-1].interval_end,
        object_count=sum(item.object_count for item in ordered),
        relationship_count=sum(item.relationship_count for item in ordered),
        source_schema_versions=source_schema_versions,
        ontology_release_digests=ontology_release_digests,
        archive_content_digest=archive_content_digest,
        compression_profile=compression_profile,
        encryption_profile=encryption_profile,
        destination_class=destination_class,
        retention_class=retention_class,
        creation_receipt_digest=creation_receipt_digest,
        created_at=created_at,
        coverage_complete=coverage_complete,
        digest=_sha256(body),
    )


def verify_archive_manifest(
    manifest: ArchiveManifest,
    *,
    observed_archive_content_digest: str,
    observed_source_partition_digests: tuple[str, ...],
    observed_source_schema_versions: tuple[str, ...],
    observed_ontology_release_digests: tuple[str, ...],
    verified_at: datetime,
) -> ArchiveVerificationReceipt:
    """Verify content and provenance without consulting a mutable current graph."""

    _digest(observed_archive_content_digest, "observed archive content_digest")
    _aware(verified_at, "archive verified_at")
    for value in observed_source_partition_digests:
        _digest(value, "observed source partition digest")
    for value in observed_ontology_release_digests:
        _digest(value, "observed ontology release")
    reasons: list[str] = []
    if _sha256(_manifest_body(manifest)) != manifest.digest:
        reasons.append("manifest_digest_mismatch")
    if observed_archive_content_digest != manifest.archive_content_digest:
        reasons.append("archive_content_digest_mismatch")
    expected_partition_digests = tuple(
        sorted(item.content_digest for item in manifest.source_partitions)
    )
    if tuple(sorted(observed_source_partition_digests)) != expected_partition_digests:
        reasons.append("source_partition_coverage_mismatch")
    if tuple(sorted(observed_source_schema_versions)) != manifest.source_schema_versions:
        reasons.append("source_schema_mismatch")
    if tuple(sorted(observed_ontology_release_digests)) != manifest.ontology_release_digests:
        reasons.append("ontology_release_mismatch")
    if not manifest.coverage_complete:
        reasons.append("incomplete_coverage")
    body = {
        "manifest_digest": manifest.digest,
        "verified": not reasons,
        "reason_codes": reasons,
        "verified_at": verified_at.astimezone(UTC).isoformat(),
    }
    return ArchiveVerificationReceipt(
        manifest_digest=manifest.digest,
        verified=not reasons,
        reason_codes=tuple(reasons),
        verified_at=verified_at,
        digest=_sha256(body),
    )


def _manifest_body(manifest: ArchiveManifest) -> dict[str, object]:
    return {
        "schema_version": manifest.schema_version,
        "source_partitions": [_partition_body(item) for item in manifest.source_partitions],
        "covered_start": manifest.covered_start.astimezone(UTC).isoformat(),
        "covered_end": manifest.covered_end.astimezone(UTC).isoformat(),
        "object_count": manifest.object_count,
        "relationship_count": manifest.relationship_count,
        "source_schema_versions": manifest.source_schema_versions,
        "ontology_release_digests": manifest.ontology_release_digests,
        "archive_content_digest": manifest.archive_content_digest,
        "compression_profile": manifest.compression_profile,
        "encryption_profile": manifest.encryption_profile,
        "destination_class": manifest.destination_class,
        "retention_class": manifest.retention_class,
        "creation_receipt_digest": manifest.creation_receipt_digest,
        "created_at": manifest.created_at.astimezone(UTC).isoformat(),
        "coverage_complete": manifest.coverage_complete,
    }


def archive_manifest_record(manifest: ArchiveManifest) -> dict[str, object]:
    """Return the canonical durable record including its content digest."""

    return {**_manifest_body(manifest), "digest": manifest.digest}


def _partition_body(partition: ArchiveSourcePartition) -> dict[str, object]:
    return {
        "partition_id": partition.partition_id,
        "content_digest": partition.content_digest,
        "interval_start": partition.interval_start.astimezone(UTC).isoformat(),
        "interval_end": partition.interval_end.astimezone(UTC).isoformat(),
        "object_count": partition.object_count,
        "relationship_count": partition.relationship_count,
        "schema_version": partition.schema_version,
        "ontology_release_digest": partition.ontology_release_digest,
        "complete": partition.complete,
        "conflict_count": partition.conflict_count,
    }


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
    "ArchiveManifest",
    "ArchiveSourcePartition",
    "ArchiveVerificationReceipt",
    "archive_manifest_record",
    "build_archive_manifest",
    "verify_archive_manifest",
]
