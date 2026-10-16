"""Immutable scope bindings for independently verified competing causal evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from fdai_service_contracts.ontology_query import content_digest

MAX_COMPETITORS = 16
_MAX_REFERENCES = 64
_MAX_WINDOW_SECONDS = 604_800


class CompetitorDisposition(StrEnum):
    SUPPORTED = "supported"
    REFUTED = "refuted"
    UNKNOWN = "unknown"


def canonical_competitors(values: tuple[str, ...]) -> tuple[str, ...]:
    """Reject overflow and duplicates instead of silently dropping candidates."""

    return _references(values, "competing explanations", maximum=MAX_COMPETITORS, width=256)


@dataclass(frozen=True, slots=True)
class CausalCompetitorRequest:
    """Exact evidence scope, not an assertion of independent source authority."""

    cause_resource_id: str
    effect_resource_id: str
    cause_concept_id: str
    effect_concept_id: str
    cause_start: datetime
    cause_end: datetime
    effect_start: datetime
    effect_end: datetime
    feature_cutoff: datetime
    topology_diff_digest: str
    topology_before_digest: str
    topology_after_digest: str
    topology_generation_refs: tuple[str, ...]
    topology_source_receipt_digests: tuple[str, ...]
    competing_explanations: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("cause_resource_id", "effect_resource_id"):
            _text(getattr(self, name), name, 256)
        for name in ("cause_concept_id", "effect_concept_id"):
            _text(getattr(self, name), name, 128)
        for name in ("cause_start", "cause_end", "effect_start", "effect_end", "feature_cutoff"):
            object.__setattr__(self, name, _utc(getattr(self, name)))
        for start, end in (
            (self.cause_start, self.cause_end),
            (self.effect_start, self.effect_end),
        ):
            if not 0 < (end - start).total_seconds() <= _MAX_WINDOW_SECONDS:
                raise ValueError("competitor assessment windows MUST be positive and bounded")
            if end > self.feature_cutoff:
                raise ValueError("competitor assessment windows MUST NOT cross feature_cutoff")
        for name in ("topology_generation_refs", "topology_source_receipt_digests"):
            object.__setattr__(self, name, _references(getattr(self, name), name))
        for digest in (
            self.topology_diff_digest,
            self.topology_before_digest,
            self.topology_after_digest,
            *self.topology_source_receipt_digests,
        ):
            _digest(digest)
        if not self.topology_generation_refs:
            raise ValueError("competitor assessment MUST bind topology source generations")
        object.__setattr__(
            self, "competing_explanations", canonical_competitors(self.competing_explanations)
        )
        if not self.competing_explanations:
            raise ValueError("competitor assessment MUST name competing explanations")

    @property
    def digest(self) -> str:
        return content_digest(
            {
                "cause_resource_id": self.cause_resource_id,
                "effect_resource_id": self.effect_resource_id,
                "cause_concept_id": self.cause_concept_id,
                "effect_concept_id": self.effect_concept_id,
                "cause_start": self.cause_start.isoformat(),
                "cause_end": self.cause_end.isoformat(),
                "effect_start": self.effect_start.isoformat(),
                "effect_end": self.effect_end.isoformat(),
                "feature_cutoff": self.feature_cutoff.isoformat(),
                "topology_diff_digest": self.topology_diff_digest,
                "topology_before_digest": self.topology_before_digest,
                "topology_after_digest": self.topology_after_digest,
                "topology_generation_refs": self.topology_generation_refs,
                "topology_source_receipt_digests": self.topology_source_receipt_digests,
                "competing_explanations": self.competing_explanations,
            }
        )


@dataclass(frozen=True, slots=True)
class CausalCompetitorFinding:
    """One independently issued disposition and its exact scope-bound source receipt."""

    competitor_id: str
    disposition: CompetitorDisposition
    request_digest: str
    source_receipt_digest: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.competitor_id, "competitor_id", 256)
        if not isinstance(self.disposition, CompetitorDisposition):
            raise ValueError("competitor disposition MUST be a typed supported/refuted/unknown")
        _digest(self.request_digest)
        _digest(self.source_receipt_digest)
        object.__setattr__(self, "evidence_refs", _references(self.evidence_refs, "evidence_refs"))
        if not self.evidence_refs:
            raise ValueError("competitor finding MUST cite non-empty independent evidence")


@dataclass(frozen=True, slots=True)
class CausalCompetitorAssessment:
    """Server-bound accounting; only the injected source can establish source trust.

    Partial accounting is retained for an explicit hold. Neither constructing this value nor
    hashing its contents verifies evidence or grants execution authority.
    """

    request: CausalCompetitorRequest
    findings: tuple[CausalCompetitorFinding, ...]
    complete: bool

    def __post_init__(self) -> None:
        if not isinstance(self.request, CausalCompetitorRequest):
            raise ValueError("competitor assessment MUST bind a typed request")
        if not isinstance(self.findings, tuple) or len(self.findings) > MAX_COMPETITORS:
            raise ValueError("competitor findings exceed immutable bounds")
        if not isinstance(self.complete, bool):
            raise ValueError("competitor assessment completeness MUST be boolean")
        if any(not isinstance(item, CausalCompetitorFinding) for item in self.findings):
            raise ValueError("competitor assessment MUST contain typed findings")
        ids = tuple(item.competitor_id for item in self.findings)
        if len(set(ids)) != len(ids):
            raise ValueError("competitor assessment MUST NOT contain duplicate competitor ids")
        if any(item.request_digest != self.request.digest for item in self.findings):
            raise ValueError("competitor source receipts MUST bind the exact request digest")
        object.__setattr__(
            self, "findings", tuple(sorted(self.findings, key=lambda item: item.competitor_id))
        )

    @property
    def digest(self) -> str:
        return content_digest(
            {
                "request_digest": self.request.digest,
                "complete": self.complete,
                "findings": [
                    {
                        "competitor_id": item.competitor_id,
                        "disposition": item.disposition.value,
                        "request_digest": item.request_digest,
                        "source_receipt_digest": item.source_receipt_digest,
                        "evidence_refs": item.evidence_refs,
                    }
                    for item in self.findings
                ],
            }
        )

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    ref
                    for item in self.findings
                    for ref in (*item.evidence_refs, item.source_receipt_digest)
                }
            )
        )

    def limitation(self, request: CausalCompetitorRequest) -> str | None:
        if self.request != request:
            return "competing_assessment_scope_mismatch"
        if not self.complete:
            return "competing_assessment_incomplete"
        if tuple(item.competitor_id for item in self.findings) != request.competing_explanations:
            return "competing_assessment_set_mismatch"
        if any(item.disposition is not CompetitorDisposition.REFUTED for item in self.findings):
            return "competing_explanations_unresolved"
        return None


class CausalCompetitorSource(Protocol):
    """Reauthorize independent evidence for the exact request, or return unavailable.

    Implementations verify source receipts and their scope before returning typed findings.
    Model output, plan arguments, digests alone, and failed correlation tests cannot establish
    a refutation. Exceptions hold the join; cancellation remains the caller's responsibility.
    """

    async def resolve(
        self, *, request: CausalCompetitorRequest
    ) -> CausalCompetitorAssessment | None: ...


def _text(value: str, name: str, maximum: int) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError(f"competitor {name} MUST be bounded non-empty text")


def _references(
    values: tuple[str, ...], name: str, *, maximum: int = _MAX_REFERENCES, width: int = 512
) -> tuple[str, ...]:
    if not isinstance(values, tuple) or len(values) > maximum:
        raise ValueError(f"competitor {name} exceeds immutable bounds")
    for value in values:
        _text(value, name, width)
    if len(set(values)) != len(values):
        raise ValueError(f"competitor {name} MUST NOT contain duplicates")
    return tuple(sorted(values))


def _digest(value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(char not in "0123456789abcdef" for char in value[7:])
    ):
        raise ValueError("competitor digest MUST be a canonical SHA-256 digest")


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("competitor timestamps MUST be timezone-aware")
    try:
        return value.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise ValueError("competitor timestamps MUST have an in-range UTC value") from exc
