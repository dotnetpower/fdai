"""PR-native publication contract for inert rule-catalog collection reviews.

Mirrors ``fdai.core.operational_learning.review`` (``CatalogReviewPublisher``)
for a different producer: a verified, due source-watcher collection run
instead of an O3 operational-pattern candidate. Both publish an inert,
content-addressed JSON package as a draft pull request outside any live
catalog path - never a Rule, ActionType, or ConfigurationBaseline YAML - so
merging the PR never activates anything and never mutates the catalog. A
human still authors the ordinary catalog-as-code change (parse + normalize +
review) afterward; see
[rule-catalog-collection.md](../../../../../../docs/roadmap/rules-and-detection/rule-catalog-collection.md).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Protocol

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_REVIEW_REF_LENGTH = 512


@dataclass(frozen=True, slots=True)
class MirroredSnapshotFile:
    """One durably mirrored snapshot file (see ``snapshot_mirror.py``)."""

    relative_path: str
    storage_ref: str
    digest: str


@dataclass(frozen=True, slots=True)
class CollectionReviewPackage:
    """Inert evidence for one verified, due source collection.

    Carries the collector's own success-receipt fields plus the durable
    storage refs the snapshot was mirrored to - never the raw collected
    text and never a normalized Rule or catalog document.
    """

    source_id: str
    resolved_revision: str
    content_sha256: str
    license: str
    redistribution: str
    verified_rules: int
    verified_at: str
    snapshot_files: tuple[MirroredSnapshotFile, ...]
    content_digest: str

    @classmethod
    def build(
        cls,
        *,
        source_id: str,
        resolved_revision: str,
        content_sha256: str,
        license: str,
        redistribution: str,
        verified_rules: int,
        verified_at: str,
        snapshot_files: tuple[MirroredSnapshotFile, ...],
    ) -> CollectionReviewPackage:
        if not source_id.strip() or not resolved_revision.strip():
            raise ValueError("collection review package requires a source id and revision")
        material = {
            "source_id": source_id,
            "resolved_revision": resolved_revision,
            "content_sha256": content_sha256,
            "license": license,
            "redistribution": redistribution,
            "verified_rules": verified_rules,
            "snapshot_files": [
                {
                    "relative_path": file.relative_path,
                    "storage_ref": file.storage_ref,
                    "digest": file.digest,
                }
                for file in snapshot_files
            ],
        }
        digest = hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
                "utf-8"
            )
        ).hexdigest()
        return cls(
            source_id=source_id,
            resolved_revision=resolved_revision,
            content_sha256=content_sha256,
            license=license,
            redistribution=redistribution,
            verified_rules=verified_rules,
            verified_at=verified_at,
            snapshot_files=snapshot_files,
            content_digest=digest,
        )


@dataclass(frozen=True, slots=True)
class CollectionReviewPublicationReceipt:
    """Opaque, replayable receipt for one idempotent draft review publication."""

    package_digest: str
    review_ref: str
    already_existed: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.package_digest, str)
            or _SHA256.fullmatch(self.package_digest) is None
        ):
            raise ValueError("package_digest MUST be lowercase SHA-256")
        if (
            not isinstance(self.review_ref, str)
            or not self.review_ref
            or self.review_ref != self.review_ref.strip()
            or len(self.review_ref) > _MAX_REVIEW_REF_LENGTH
            or any(not 0x21 <= ord(character) <= 0x7E for character in self.review_ref)
        ):
            raise ValueError("review_ref MUST be bounded printable ASCII without whitespace")
        if not isinstance(self.already_existed, bool):
            raise ValueError("already_existed MUST be boolean")


class CollectionReviewPublisher(Protocol):
    """Publish one durable collection package for human review, never merges it."""

    async def publish(self, package: CollectionReviewPackage) -> CollectionReviewPublicationReceipt:
        """Return an idempotent draft-review receipt for ``package``.

        Implementations MUST be idempotent by ``package.content_digest`` -
        a second call for an unchanged package MUST return
        ``already_existed=True`` and MUST NOT open a duplicate PR.
        """
        ...


__all__ = [
    "CollectionReviewPackage",
    "CollectionReviewPublicationReceipt",
    "CollectionReviewPublisher",
    "MirroredSnapshotFile",
]
