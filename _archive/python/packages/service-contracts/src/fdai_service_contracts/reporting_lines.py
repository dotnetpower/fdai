"""Neutral contracts for document-derived human reporting-line candidates."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReportingLineContract(BaseModel):
    """Immutable validated base for cross-service reporting-line records."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ReportingLineExtractionSource(StrEnum):
    """How a reporting-line candidate was derived."""

    DETERMINISTIC = "deterministic"
    MODEL = "model"


class ReportingLineDirectoryComparison(StrEnum):
    """Comparison with current directory manager evidence."""

    MATCHED = "matched"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"
    NOT_CHECKED = "not_checked"


class ReportingLineDraftOutcome(StrEnum):
    """Terminal outcome of one report-line extraction attempt."""

    DRAFTED = "drafted"
    ABSTAINED = "abstained"


class ReportingLineSourceSpan(ReportingLineContract):
    """One bounded locator that grounds a proposed reporting edge."""

    unit_id: Annotated[str, Field(min_length=1, max_length=128)]
    locator: Annotated[str, Field(min_length=1, max_length=256)]
    quote: Annotated[str, Field(min_length=1, max_length=200)]


class ReportingLinePerson(ReportingLineContract):
    """A person named by a document and optionally resolved to an exact identity."""

    display_name: Annotated[str, Field(min_length=1, max_length=128)]
    oid: Annotated[str, Field(min_length=1, max_length=256)] | None = None


class ReportingLineResolvedIdentity(ReportingLineContract):
    """One exact active person resolved by the deployment directory."""

    oid: Annotated[str, Field(min_length=1, max_length=256)]


class ReportingLineManagerStatus(StrEnum):
    """Availability of current directory manager evidence."""

    RESOLVED = "resolved"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"


class ReportingLineManagerObservation(ReportingLineContract):
    """Current directory manager evidence without granting approval authority."""

    status: ReportingLineManagerStatus
    manager_oid: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    observed_at: datetime | None = None

    @model_validator(mode="after")
    def _consistent(self) -> ReportingLineManagerObservation:
        if (self.status is ReportingLineManagerStatus.RESOLVED) != (self.manager_oid is not None):
            raise ValueError("resolved manager evidence requires exactly one manager")
        if self.observed_at is not None and (
            self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None
        ):
            raise ValueError("manager evidence observed_at MUST be timezone-aware")
        return self


class ReportingLineDirectory(Protocol):
    """Resolve exact people and current manager evidence without mutation authority."""

    async def resolve(self, display_name: str) -> ReportingLineResolvedIdentity | None: ...

    async def manager_for(self, subject_oid: str) -> ReportingLineManagerObservation: ...


class ReportingLineCandidate(ReportingLineContract):
    """One grounded subject-to-manager proposal that grants no authority."""

    candidate_id: Annotated[str, Field(pattern=r"^report-line-[a-f0-9]{32}$")]
    subject: ReportingLinePerson
    manager: ReportingLinePerson
    relationship_kind: Literal["primary_manager"] = "primary_manager"
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    extraction_source: ReportingLineExtractionSource
    citations: Annotated[tuple[ReportingLineSourceSpan, ...], Field(min_length=1)]
    directory_manager_oid: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    directory_comparison: ReportingLineDirectoryComparison = (
        ReportingLineDirectoryComparison.NOT_CHECKED
    )

    @model_validator(mode="after")
    def _validate_candidate(self) -> ReportingLineCandidate:
        for name, value in (
            ("effective_from", self.effective_from),
            ("effective_until", self.effective_until),
        ):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{name} MUST be timezone-aware")
        if (
            self.effective_from is not None
            and self.effective_until is not None
            and self.effective_from >= self.effective_until
        ):
            raise ValueError("reporting-line effective window MUST be non-empty")
        if (
            self.subject.oid is not None
            and self.manager.oid is not None
            and self.subject.oid.casefold() == self.manager.oid.casefold()
        ):
            raise ValueError("a person cannot report to themselves")
        expected = reporting_line_candidate_id(
            subject=self.subject,
            manager=self.manager,
            relationship_kind=self.relationship_kind,
            effective_from=self.effective_from,
            effective_until=self.effective_until,
            citations=self.citations,
        )
        if self.candidate_id != expected:
            raise ValueError("reporting-line candidate identity does not match its content")
        if self.directory_comparison is ReportingLineDirectoryComparison.MATCHED and (
            self.manager.oid is None
            or self.directory_manager_oid is None
            or self.manager.oid.casefold() != self.directory_manager_oid.casefold()
        ):
            raise ValueError("matched directory comparison requires the same exact manager")
        if self.directory_comparison is ReportingLineDirectoryComparison.CONFLICT and (
            self.manager.oid is None
            or self.directory_manager_oid is None
            or self.manager.oid.casefold() == self.directory_manager_oid.casefold()
        ):
            raise ValueError("conflicting directory comparison requires distinct managers")
        return self


class ReportingLineDraftArtifact(ReportingLineContract):
    """Review-only organization-chart extraction result for one document version."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    upload_id: UUID
    document_id: UUID
    version_id: UUID
    source_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    outcome: ReportingLineDraftOutcome
    candidates: tuple[ReportingLineCandidate, ...] = ()
    abstained: tuple[ReportingLineCandidate, ...] = ()
    unresolved_people: tuple[ReportingLinePerson, ...] = ()
    warnings: tuple[Annotated[str, Field(min_length=1, max_length=512)], ...] = ()

    @model_validator(mode="after")
    def _validate_outcome(self) -> ReportingLineDraftArtifact:
        candidate_ids = [item.candidate_id for item in (*self.candidates, *self.abstained)]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("reporting-line candidate ids MUST be unique")
        if (self.outcome is ReportingLineDraftOutcome.DRAFTED) != bool(self.candidates):
            raise ValueError("reporting-line outcome does not match its candidate set")
        return self

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible projection."""

        return self.model_dump(mode="json")


class ReportingLineDraftStore(Protocol):
    """Persist one immutable report-line draft projection."""

    async def put(self, artifact: ReportingLineDraftArtifact) -> None: ...


def reporting_line_candidate_id(
    *,
    subject: ReportingLinePerson,
    manager: ReportingLinePerson,
    relationship_kind: str,
    effective_from: datetime | None,
    effective_until: datetime | None,
    citations: tuple[ReportingLineSourceSpan, ...],
) -> str:
    """Return a stable candidate identity from exact edge and provenance fields."""

    material = {
        "subject": subject.model_dump(mode="json"),
        "manager": manager.model_dump(mode="json"),
        "relationship_kind": relationship_kind,
        "effective_from": effective_from.isoformat() if effective_from is not None else None,
        "effective_until": effective_until.isoformat() if effective_until is not None else None,
        "citations": [item.model_dump(mode="json") for item in citations],
    }
    digest = hashlib.sha256(
        json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return f"report-line-{digest[:32]}"


__all__ = [
    "ReportingLineCandidate",
    "ReportingLineDirectoryComparison",
    "ReportingLineDirectory",
    "ReportingLineDraftArtifact",
    "ReportingLineDraftOutcome",
    "ReportingLineDraftStore",
    "ReportingLineExtractionSource",
    "ReportingLineManagerObservation",
    "ReportingLineManagerStatus",
    "ReportingLinePerson",
    "ReportingLineResolvedIdentity",
    "ReportingLineSourceSpan",
    "reporting_line_candidate_id",
]
