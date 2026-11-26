"""Shadow-only comparison against human and API evidence."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.shared.providers.browser_evidence import (
    BrowserEvidenceReceipt,
    BrowserEvidenceReference,
)


@dataclass(frozen=True, slots=True)
class BrowserEvidenceShadowComparison:
    request_id: str
    fidelity: float | None
    conflict: bool
    unavailable_count: int
    abstained: bool
    policy_escape_count: int = 0

    @property
    def promotion_eligible(self) -> bool:
        return False


class BrowserEvidenceShadowComparator:
    """Measure browser fidelity without granting promotion authority."""

    def compare(
        self,
        receipt: BrowserEvidenceReceipt,
        references: tuple[BrowserEvidenceReference, ...],
    ) -> BrowserEvidenceShadowComparison:
        unavailable = sum(reference.status == "unavailable" for reference in references)
        available = tuple(
            reference
            for reference in references
            if reference.status == "available" and reference.content_digest is not None
        )
        if receipt.status != "captured" or receipt.content_digest is None:
            return BrowserEvidenceShadowComparison(
                request_id=receipt.request_id,
                fidelity=None,
                conflict=False,
                unavailable_count=unavailable + 1,
                abstained=True,
            )
        digests = {reference.content_digest for reference in available}
        matches = sum(reference.content_digest == receipt.content_digest for reference in available)
        conflict = len(digests) > 1 or any(
            reference.content_digest != receipt.content_digest for reference in available
        )
        return BrowserEvidenceShadowComparison(
            request_id=receipt.request_id,
            fidelity=matches / len(available) if available else None,
            conflict=conflict,
            unavailable_count=unavailable,
            abstained=unavailable > 0 or conflict or not available,
        )


__all__ = ["BrowserEvidenceShadowComparator", "BrowserEvidenceShadowComparison"]
