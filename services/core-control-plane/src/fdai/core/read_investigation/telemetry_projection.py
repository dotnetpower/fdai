"""Replay-safe RCA citation projection from adaptive telemetry Process evidence."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.core.rca.contract import Citation, CitationKind
from fdai.core.rca.telemetry_evidence import TelemetryEvidenceDisposition
from fdai.core.rca.telemetry_recipes import (
    DEFAULT_TELEMETRY_RECIPE_CATALOG,
    ReviewedTelemetryRecipeCatalog,
)

from .adaptive_contract import AdaptiveInvestigationResult

_RECEIPT_REF_PREFIX = "telemetry-receipt:"


@dataclass(frozen=True, slots=True)
class AdaptiveTelemetryEvidenceResult:
    """Process result plus bounded positive-source citations for T2 RCA."""

    investigation: AdaptiveInvestigationResult
    citations: tuple[Citation, ...]

    def __post_init__(self) -> None:
        if any(item.kind is not CitationKind.TELEMETRY for item in self.citations):
            raise ValueError("adaptive telemetry result accepts only telemetry citations")


def adaptive_telemetry_evidence_result(
    investigation: AdaptiveInvestigationResult,
    *,
    catalog: ReviewedTelemetryRecipeCatalog = DEFAULT_TELEMETRY_RECIPE_CATALOG,
) -> AdaptiveTelemetryEvidenceResult:
    """Project complete positive source receipts into secret-safe RCA citations."""

    citations: list[Citation] = []
    seen: set[str] = set()
    for iteration in investigation.iterations:
        execution = iteration.execution
        if execution is None or execution.source_metadata is None:
            continue
        metadata = execution.source_metadata
        if metadata.disposition != TelemetryEvidenceDisposition.COMPLETE.value:
            continue
        digest = metadata.receipt_digest
        reference = f"{_RECEIPT_REF_PREFIX}{digest}"
        if digest in seen or execution.evidence_refs.count(reference) != 1:
            continue
        recipe = catalog.get(metadata.recipe_id, metadata.recipe_version)
        citations.append(
            Citation(
                kind=CitationKind.TELEMETRY,
                ref=reference,
                facts=tuple(
                    sorted(
                        {
                            f"disposition:{metadata.disposition}",
                            f"mechanism:{recipe.mechanism.value}",
                        }
                    )
                ),
            )
        )
        seen.add(digest)
    return AdaptiveTelemetryEvidenceResult(
        investigation=investigation,
        citations=tuple(citations),
    )


__all__ = ["AdaptiveTelemetryEvidenceResult", "adaptive_telemetry_evidence_result"]
