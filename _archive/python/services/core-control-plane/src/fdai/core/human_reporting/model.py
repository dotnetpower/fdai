"""Immutable human reporting-line lifecycle models."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from fdai_service_contracts import (
    ReportingLineCandidate,
    ReportingLineDirectoryComparison,
)


class ReportingLineModelError(ValueError):
    """Raised when reporting-line state is malformed or internally inconsistent."""


class ReportingLineCaseState(StrEnum):
    """Lifecycle state for one independently reviewed reporting edge."""

    PENDING_CONFIRMATION = "pending_confirmation"
    PENDING_OWNER_REVIEW = "pending_owner_review"
    ACTIVATION_PENDING = "activation_pending"
    ACTIVE = "active"
    CONFLICT = "conflict"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class EndpointDecision(StrEnum):
    """Decision made by either endpoint of a proposed relationship."""

    CONFIRM = "confirm"
    REJECT = "reject"


class OwnerDecision(StrEnum):
    """Independent Owner decision over one confirmed edge."""

    APPROVE = "approve"
    REJECT = "reject"


def reporting_instant(value: datetime) -> datetime:
    """Return one UTC instant or reject an ambiguous timestamp."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ReportingLineModelError("reporting-line timestamps MUST be timezone-aware")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as exc:
        raise ReportingLineModelError("reporting-line timestamp is outside the UTC range") from exc


def normalize_principal(value: str) -> str:
    """Normalize one exact principal reference without accepting whitespace variants."""

    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 256:
        raise ReportingLineModelError(
            "reporting-line principal references MUST be exact non-empty strings"
        )
    return value.casefold()


@dataclass(frozen=True, slots=True)
class ReportingCitation:
    """Content-minimized source locator retained by the Core lifecycle."""

    unit_id: str
    locator: str

    def __post_init__(self) -> None:
        for value in (self.unit_id, self.locator):
            if not isinstance(value, str) or not value or value != value.strip():
                raise ReportingLineModelError("reporting-line citations MUST be exact")
        if len(self.unit_id) > 128 or len(self.locator) > 256:
            raise ReportingLineModelError("reporting-line citation exceeds its bound")

    def to_dict(self) -> dict[str, str]:
        return {"unit_id": self.unit_id, "locator": self.locator}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ReportingCitation:
        return cls(unit_id=_text(value, "unit_id"), locator=_text(value, "locator"))


@dataclass(frozen=True, slots=True)
class EndpointConfirmation:
    """One immutable endpoint statement about a proposed reporting edge."""

    principal_ref: str
    decision: EndpointDecision
    decided_at: datetime
    edge_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "principal_ref", normalize_principal(self.principal_ref))
        object.__setattr__(self, "decided_at", reporting_instant(self.decided_at))
        if not isinstance(self.decision, EndpointDecision):
            raise ReportingLineModelError("endpoint decision MUST be typed")
        _digest(self.edge_digest, "edge_digest")

    def to_dict(self) -> dict[str, object]:
        return {
            "principal_ref": self.principal_ref,
            "decision": self.decision.value,
            "decided_at": self.decided_at.isoformat(),
            "edge_digest": self.edge_digest,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EndpointConfirmation:
        return cls(
            principal_ref=_text(value, "principal_ref"),
            decision=EndpointDecision(_text(value, "decision")),
            decided_at=_instant(value, "decided_at"),
            edge_digest=_text(value, "edge_digest"),
        )


@dataclass(frozen=True, slots=True)
class OwnerReview:
    """One immutable Owner review over a previously confirmed edge."""

    principal_ref: str
    decision: OwnerDecision
    decided_at: datetime
    edge_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "principal_ref", normalize_principal(self.principal_ref))
        object.__setattr__(self, "decided_at", reporting_instant(self.decided_at))
        if not isinstance(self.decision, OwnerDecision):
            raise ReportingLineModelError("Owner decision MUST be typed")
        _digest(self.edge_digest, "edge_digest")

    def to_dict(self) -> dict[str, object]:
        return {
            "principal_ref": self.principal_ref,
            "decision": self.decision.value,
            "decided_at": self.decided_at.isoformat(),
            "edge_digest": self.edge_digest,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> OwnerReview:
        return cls(
            principal_ref=_text(value, "principal_ref"),
            decision=OwnerDecision(_text(value, "decision")),
            decided_at=_instant(value, "decided_at"),
            edge_digest=_text(value, "edge_digest"),
        )


@dataclass(frozen=True, slots=True)
class ReportingLineCase:
    """One revisioned subject-to-manager edge and its independent human evidence."""

    case_id: str
    candidate_id: str
    upload_id: str
    document_id: str
    version_id: str
    source_sha256: str
    subject_ref: str
    manager_ref: str
    requester_ref: str
    citations: tuple[ReportingCitation, ...]
    effective_from: datetime
    effective_until: datetime
    recorded_at: datetime
    state: ReportingLineCaseState = ReportingLineCaseState.PENDING_CONFIRMATION
    revision: int = 1
    confirmation: EndpointConfirmation | None = None
    owner_review: OwnerReview | None = None
    supersedes_case_id: str | None = None
    directory_comparison: ReportingLineDirectoryComparison = (
        ReportingLineDirectoryComparison.NOT_CHECKED
    )
    directory_manager_ref: str | None = None

    def __post_init__(self) -> None:
        try:
            if str(UUID(self.case_id)) != self.case_id:
                raise ValueError
            for value in (self.upload_id, self.document_id, self.version_id):
                if str(UUID(value)) != value:
                    raise ValueError
        except (TypeError, ValueError) as exc:
            raise ReportingLineModelError(
                "reporting-line case and document references MUST be UUIDs"
            ) from exc
        if re.fullmatch(r"report-line-[a-f0-9]{32}", self.candidate_id) is None:
            raise ReportingLineModelError("reporting-line candidate id is invalid")
        _digest(self.source_sha256, "source_sha256")
        object.__setattr__(self, "subject_ref", normalize_principal(self.subject_ref))
        object.__setattr__(self, "manager_ref", normalize_principal(self.manager_ref))
        object.__setattr__(self, "requester_ref", normalize_principal(self.requester_ref))
        if self.subject_ref == self.manager_ref:
            raise ReportingLineModelError("a person cannot report to themselves")
        if not self.citations or len(self.citations) > 32:
            raise ReportingLineModelError("reporting-line case requires 1-32 citations")
        if not all(isinstance(item, ReportingCitation) for item in self.citations):
            raise ReportingLineModelError("reporting-line citations MUST be typed")
        object.__setattr__(self, "effective_from", reporting_instant(self.effective_from))
        object.__setattr__(self, "effective_until", reporting_instant(self.effective_until))
        object.__setattr__(self, "recorded_at", reporting_instant(self.recorded_at))
        if self.effective_from >= self.effective_until:
            raise ReportingLineModelError("reporting-line effective window MUST be non-empty")
        if isinstance(self.revision, bool) or self.revision < 1:
            raise ReportingLineModelError("reporting-line revision MUST be positive")
        if self.supersedes_case_id is not None:
            try:
                if str(UUID(self.supersedes_case_id)) != self.supersedes_case_id:
                    raise ValueError
            except (TypeError, ValueError) as exc:
                raise ReportingLineModelError("superseded case id MUST be canonical") from exc
            if self.supersedes_case_id == self.case_id:
                raise ReportingLineModelError("reporting-line case cannot supersede itself")
        if self.directory_manager_ref is not None:
            object.__setattr__(
                self,
                "directory_manager_ref",
                normalize_principal(self.directory_manager_ref),
            )
        if self.state is ReportingLineCaseState.PENDING_OWNER_REVIEW and (
            self.confirmation is None
            or self.confirmation.decision is not EndpointDecision.CONFIRM
            or self.owner_review is not None
        ):
            raise ReportingLineModelError("Owner review requires endpoint confirmation")
        if self.state is ReportingLineCaseState.PENDING_CONFIRMATION and (
            self.confirmation is not None or self.owner_review is not None
        ):
            raise ReportingLineModelError(
                "pending reporting-line confirmation cannot carry a decision"
            )
        if self.confirmation is not None and self.confirmation.decision is EndpointDecision.REJECT:
            if self.state is not ReportingLineCaseState.CONFLICT:
                raise ReportingLineModelError(
                    "rejected endpoint confirmation requires conflict state"
                )
        if self.confirmation is not None and self.confirmation.principal_ref not in {
            self.subject_ref,
            self.manager_ref,
        }:
            raise ReportingLineModelError(
                "reporting-line confirmation principal MUST be a relationship endpoint"
            )
        if self.owner_review is not None:
            expected_states = (
                {
                    ReportingLineCaseState.ACTIVATION_PENDING,
                    ReportingLineCaseState.ACTIVE,
                    ReportingLineCaseState.CONFLICT,
                    ReportingLineCaseState.SUPERSEDED,
                }
                if self.owner_review.decision is OwnerDecision.APPROVE
                else {
                    ReportingLineCaseState.REJECTED,
                    ReportingLineCaseState.SUPERSEDED,
                }
            )
            if self.state not in expected_states:
                raise ReportingLineModelError(
                    "Owner review decision does not match reporting-line state"
                )
        if self.state is ReportingLineCaseState.REJECTED and (
            self.owner_review is None or self.owner_review.decision is not OwnerDecision.REJECT
        ):
            raise ReportingLineModelError("rejected report line requires an Owner rejection")
        if self.state in {
            ReportingLineCaseState.ACTIVATION_PENDING,
            ReportingLineCaseState.ACTIVE,
            ReportingLineCaseState.SUPERSEDED,
        }:
            if (
                self.confirmation is None
                or self.confirmation.decision is not EndpointDecision.CONFIRM
                or self.owner_review is None
                or self.owner_review.decision is not OwnerDecision.APPROVE
            ):
                raise ReportingLineModelError("active report line requires both human decisions")
            if self.owner_review.principal_ref in {
                self.requester_ref,
                self.subject_ref,
                self.manager_ref,
                self.confirmation.principal_ref,
            }:
                raise ReportingLineModelError("Owner review MUST be independent")
        if self.confirmation is not None and self.confirmation.edge_digest != self.edge_digest:
            raise ReportingLineModelError("endpoint confirmation is bound to another edge")
        if self.owner_review is not None and self.owner_review.edge_digest != self.edge_digest:
            raise ReportingLineModelError("Owner review is bound to another edge")
        if self.owner_review is not None and self.owner_review.principal_ref in {
            self.requester_ref,
            self.subject_ref,
            self.manager_ref,
            self.confirmation.principal_ref if self.confirmation is not None else "",
        }:
            raise ReportingLineModelError("Owner review MUST be independent")

    @property
    def edge_digest(self) -> str:
        """Return the immutable relationship and source digest reviewed by people."""

        import hashlib
        import json

        value = {
            "candidate_id": self.candidate_id,
            "upload_id": self.upload_id,
            "document_id": self.document_id,
            "version_id": self.version_id,
            "source_sha256": self.source_sha256,
            "subject_ref": self.subject_ref,
            "manager_ref": self.manager_ref,
            "citations": [item.to_dict() for item in self.citations],
            "effective_from": self.effective_from.isoformat(),
            "effective_until": self.effective_until.isoformat(),
            "supersedes_case_id": self.supersedes_case_id,
            "directory_comparison": self.directory_comparison.value,
            "directory_manager_ref": self.directory_manager_ref,
        }
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @property
    def is_currently_effective(self) -> bool:
        """Return whether the edge is active at its recorded instant."""

        return self.effective_from <= self.recorded_at < self.effective_until

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1.0.0",
            "case_id": self.case_id,
            "candidate_id": self.candidate_id,
            "upload_id": self.upload_id,
            "document_id": self.document_id,
            "version_id": self.version_id,
            "source_sha256": self.source_sha256,
            "subject_ref": self.subject_ref,
            "manager_ref": self.manager_ref,
            "requester_ref": self.requester_ref,
            "citations": [item.to_dict() for item in self.citations],
            "effective_from": self.effective_from.isoformat(),
            "effective_until": self.effective_until.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
            "state": self.state.value,
            "revision": self.revision,
            "confirmation": self.confirmation.to_dict() if self.confirmation else None,
            "owner_review": self.owner_review.to_dict() if self.owner_review else None,
            "supersedes_case_id": self.supersedes_case_id,
            "directory_comparison": self.directory_comparison.value,
            "directory_manager_ref": self.directory_manager_ref,
            "edge_digest": self.edge_digest,
            "execution_authority": False,
            "approval_authority": False,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ReportingLineCase:
        if value.get("schema_version") != "1.0.0":
            raise ReportingLineModelError("unsupported reporting-line case schema")
        citations = value.get("citations")
        if not isinstance(citations, list):
            raise ReportingLineModelError("reporting-line citations MUST be an array")
        confirmation = value.get("confirmation")
        owner_review = value.get("owner_review")
        case = cls(
            case_id=_text(value, "case_id"),
            candidate_id=_text(value, "candidate_id"),
            upload_id=_text(value, "upload_id"),
            document_id=_text(value, "document_id"),
            version_id=_text(value, "version_id"),
            source_sha256=_text(value, "source_sha256"),
            subject_ref=_text(value, "subject_ref"),
            manager_ref=_text(value, "manager_ref"),
            requester_ref=_text(value, "requester_ref"),
            citations=tuple(ReportingCitation.from_dict(_mapping(item)) for item in citations),
            effective_from=_instant(value, "effective_from"),
            effective_until=_instant(value, "effective_until"),
            recorded_at=_instant(value, "recorded_at"),
            state=ReportingLineCaseState(_text(value, "state")),
            revision=_integer(value, "revision"),
            confirmation=(
                EndpointConfirmation.from_dict(_mapping(confirmation))
                if confirmation is not None
                else None
            ),
            owner_review=(
                OwnerReview.from_dict(_mapping(owner_review)) if owner_review is not None else None
            ),
            supersedes_case_id=_optional_text(value, "supersedes_case_id"),
            directory_comparison=ReportingLineDirectoryComparison(
                _text(value, "directory_comparison")
            ),
            directory_manager_ref=_optional_text(value, "directory_manager_ref"),
        )
        if value.get("edge_digest") != case.edge_digest:
            raise ReportingLineModelError("reporting-line stored edge digest does not match")
        if (
            value.get("execution_authority") is not False
            or value.get("approval_authority") is not False
        ):
            raise ReportingLineModelError("reporting-line case cannot carry authority")
        return case

    @classmethod
    def from_candidate(
        cls,
        *,
        case_id: str,
        artifact_upload_id: UUID,
        artifact_document_id: UUID,
        artifact_version_id: UUID,
        artifact_source_sha256: str,
        candidate: ReportingLineCandidate,
        requester_ref: str,
        effective_from: datetime,
        effective_until: datetime,
        recorded_at: datetime,
        supersedes_case_id: str | None = None,
    ) -> ReportingLineCase:
        """Create one case from an exact, resolved document candidate."""

        if candidate.subject.oid is None or candidate.manager.oid is None:
            raise ReportingLineModelError("reporting-line candidate identities MUST be resolved")
        state = (
            ReportingLineCaseState.CONFLICT
            if candidate.directory_comparison.value == "conflict"
            else ReportingLineCaseState.PENDING_CONFIRMATION
        )
        return cls(
            case_id=case_id,
            candidate_id=candidate.candidate_id,
            upload_id=str(artifact_upload_id),
            document_id=str(artifact_document_id),
            version_id=str(artifact_version_id),
            source_sha256=artifact_source_sha256,
            subject_ref=candidate.subject.oid,
            manager_ref=candidate.manager.oid,
            requester_ref=requester_ref,
            citations=tuple(
                ReportingCitation(unit_id=item.unit_id, locator=item.locator)
                for item in candidate.citations
            ),
            effective_from=effective_from,
            effective_until=effective_until,
            recorded_at=recorded_at,
            state=state,
            supersedes_case_id=supersedes_case_id,
            directory_comparison=candidate.directory_comparison,
            directory_manager_ref=candidate.directory_manager_oid,
        )


def _digest(value: str, name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ReportingLineModelError(f"{name} MUST be a lowercase SHA-256")


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReportingLineModelError("reporting-line nested value MUST be an object")
    return value


def _text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ReportingLineModelError(f"{key} MUST be a non-empty string")
    return item


def _optional_text(value: dict[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str) or not item:
        raise ReportingLineModelError(f"{key} MUST be null or a non-empty string")
    return item


def _integer(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int):
        raise ReportingLineModelError(f"{key} MUST be an integer")
    return item


def _instant(value: dict[str, Any], key: str) -> datetime:
    raw = _text(value, key)
    try:
        return reporting_instant(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError as exc:
        raise ReportingLineModelError(f"{key} MUST be an ISO timestamp") from exc


__all__ = [
    "EndpointConfirmation",
    "EndpointDecision",
    "OwnerDecision",
    "OwnerReview",
    "ReportingCitation",
    "ReportingLineCase",
    "ReportingLineCaseState",
    "ReportingLineModelError",
    "normalize_principal",
    "reporting_instant",
]
