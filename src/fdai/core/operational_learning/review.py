"""PR-native publication contract for inert operational catalog reviews."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from .catalog import CatalogReviewPackage

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_REVIEW_REF_LENGTH = 512


@dataclass(frozen=True, slots=True)
class CatalogReviewPublicationReceipt:
    """Opaque receipt for one idempotent draft review publication."""

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


class CatalogReviewPublisher(Protocol):
    """Publish one immutable package for human review without merging it."""

    async def publish(
        self,
        package: CatalogReviewPackage,
    ) -> CatalogReviewPublicationReceipt:
        """Return an idempotent draft-review receipt for ``package``."""
        ...


@dataclass(frozen=True, slots=True)
class CatalogReviewOutcome:
    idempotency_key: str
    correlation_id: str
    candidate_digest: str | None
    package_digest: str | None
    outcome: str
    reason: str
    review_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.idempotency_key or not self.correlation_id:
            raise ValueError("catalog review outcome trace identity MUST be non-empty")
        for digest in (self.candidate_digest, self.package_digest):
            if digest is not None and _SHA256.fullmatch(digest) is None:
                raise ValueError("catalog review outcome digests MUST be SHA-256")
        if not self.outcome or not self.reason:
            raise ValueError("catalog review outcome decision MUST be non-empty")


__all__ = [
    "CatalogReviewOutcome",
    "CatalogReviewPublicationReceipt",
    "CatalogReviewPublisher",
]
