"""Verified source receipts and temporal scopes for operational evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, Self

_DIGEST_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
_MAX_REF_LENGTH = 512
_MAX_SCOPE_ITEMS = 64
_MAX_SUMMARY_ITEMS = 32
_MAX_MEMBERSHIP_EVIDENCE_BYTES = 65_536


class SecuredSnapshotReceipt(Protocol):
    """Minimum read-only receipt surface accepted from the secured query gateway."""

    @property
    def ontology_release(self) -> object: ...

    @property
    def projected_result_digest(self) -> str: ...

    @property
    def purpose(self) -> str: ...

    @property
    def observation_cutoff(self) -> datetime: ...

    @property
    def complete(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class EvidenceTemporalScope:
    """Canonical effective, evidence, and recorded times for one source artifact."""

    effective_from: datetime
    effective_to: datetime | None
    evidence_cutoff: datetime
    recorded_at: datetime

    def __post_init__(self) -> None:
        for field_name, value in (
            ("effective_from", self.effective_from),
            ("evidence_cutoff", self.evidence_cutoff),
            ("recorded_at", self.recorded_at),
        ):
            if value.tzinfo is None:
                raise ValueError(f"EvidenceTemporalScope.{field_name} MUST be timezone-aware")
        if self.effective_to is not None:
            if self.effective_to.tzinfo is None:
                raise ValueError("EvidenceTemporalScope.effective_to MUST be timezone-aware")
            if self.effective_to <= self.effective_from:
                raise ValueError("EvidenceTemporalScope.effective_to MUST follow effective_from")
        if self.effective_from > self.evidence_cutoff:
            raise ValueError("evidence effective time MUST NOT exceed evidence cutoff")
        if self.evidence_cutoff > self.recorded_at:
            raise ValueError("evidence cutoff MUST NOT exceed recorded time")

    def to_mapping(self) -> dict[str, object]:
        """Return the canonical temporal representation."""

        return {
            "effective_from": _timestamp(self.effective_from),
            "effective_to": _timestamp(self.effective_to) if self.effective_to else None,
            "evidence_cutoff": _timestamp(self.evidence_cutoff),
            "recorded_at": _timestamp(self.recorded_at),
        }


@dataclass(frozen=True, slots=True)
class VerifiedEvidenceSourceReceipt:
    """Content-addressed proof that a source artifact and exact evidence item were verified."""

    receipt_id: str
    ontology_release_digest: str
    catalog_revision: str
    document_revision: str | None
    source_identity: str
    source_revision: str
    authenticated_source: str
    content_digest: str
    purpose: str
    scope: tuple[str, ...]
    redaction_summary: tuple[str, ...]
    temporal_scope: EvidenceTemporalScope
    freshness_ceiling_seconds: int
    completeness: float
    synthetic: bool
    conflicts: tuple[str, ...]
    verification_method: str
    verifier_identity: str
    verification_receipt_ref: str
    evidence_lane: str | None = None
    evidence_item_digest: str | None = None
    membership_evidence: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("catalog_revision", self.catalog_revision),
            ("source_identity", self.source_identity),
            ("source_revision", self.source_revision),
            ("authenticated_source", self.authenticated_source),
            ("purpose", self.purpose),
            ("verification_method", self.verification_method),
            ("verifier_identity", self.verifier_identity),
            ("verification_receipt_ref", self.verification_receipt_ref),
        ):
            _require_text(value, field_name=field_name)
        _require_digest(self.ontology_release_digest, field_name="ontology_release_digest")
        _require_digest(self.content_digest, field_name="content_digest")
        if self.document_revision is not None:
            _require_text(self.document_revision, field_name="document_revision")
        canonical_scope = _canonical_values(
            self.scope,
            field_name="scope",
            required=True,
            max_items=_MAX_SCOPE_ITEMS,
        )
        canonical_redaction = _canonical_values(
            self.redaction_summary,
            field_name="redaction_summary",
            required=True,
            max_items=_MAX_SUMMARY_ITEMS,
        )
        canonical_conflicts = _canonical_values(
            self.conflicts,
            field_name="conflicts",
            required=False,
            max_items=_MAX_SUMMARY_ITEMS,
        )
        object.__setattr__(self, "scope", canonical_scope)
        object.__setattr__(self, "redaction_summary", canonical_redaction)
        object.__setattr__(self, "conflicts", canonical_conflicts)
        if isinstance(self.freshness_ceiling_seconds, bool) or not isinstance(
            self.freshness_ceiling_seconds, int
        ):
            raise ValueError("freshness_ceiling_seconds MUST be an integer")
        if self.freshness_ceiling_seconds < 1:
            raise ValueError("freshness_ceiling_seconds MUST be >= 1")
        if isinstance(self.completeness, bool) or not isinstance(self.completeness, (int, float)):
            raise ValueError("completeness MUST be numeric")
        if not 0.0 <= self.completeness <= 1.0:
            raise ValueError("completeness MUST be between 0 and 1")
        if not isinstance(self.synthetic, bool):
            raise ValueError("synthetic MUST be a boolean")
        if self.authenticated_source.casefold() == self.verifier_identity.casefold():
            raise ValueError(
                "source receipt verifier MUST be independent from authenticated source"
            )
        binding_values = (
            self.evidence_lane,
            self.evidence_item_digest,
            self.membership_evidence,
        )
        if any(value is not None for value in binding_values) and any(
            value is None for value in binding_values
        ):
            raise ValueError("source receipt evidence item binding MUST be complete")
        if self.evidence_lane is not None:
            if self.evidence_lane not in {"catalog", "document", "ontology", "state"}:
                raise ValueError("source receipt evidence_lane is invalid")
            item_digest = self.evidence_item_digest
            membership_evidence = self.membership_evidence
            if item_digest is None or membership_evidence is None:
                raise ValueError("source receipt evidence item binding MUST be complete")
            _require_digest(item_digest, field_name="evidence_item_digest")
            if not _decode_membership_evidence(membership_evidence):
                raise ValueError("source receipt membership_evidence MUST be non-empty")
        if self.receipt_id != self.expected_id():
            raise ValueError("source receipt id MUST match canonical content")

    @classmethod
    def create(
        cls,
        *,
        ontology_release_digest: str,
        catalog_revision: str,
        document_revision: str | None,
        source_identity: str,
        source_revision: str,
        authenticated_source: str,
        content_digest: str,
        purpose: str,
        scope: tuple[str, ...],
        redaction_summary: tuple[str, ...],
        temporal_scope: EvidenceTemporalScope,
        freshness_ceiling_seconds: int,
        completeness: float,
        synthetic: bool,
        conflicts: tuple[str, ...] = (),
        verification_method: str,
        verifier_identity: str,
        verification_receipt_ref: str,
    ) -> VerifiedEvidenceSourceReceipt:
        """Create a preverified receipt whose identity covers every source assertion."""

        canonical_scope = tuple(sorted(set(scope)))
        canonical_redaction = tuple(sorted(set(redaction_summary)))
        canonical_conflicts = tuple(sorted(set(conflicts)))
        values: dict[str, object] = {
            "ontology_release_digest": ontology_release_digest,
            "catalog_revision": catalog_revision,
            "document_revision": document_revision,
            "source_identity": source_identity,
            "source_revision": source_revision,
            "authenticated_source": authenticated_source,
            "content_digest": content_digest,
            "purpose": purpose,
            "scope": canonical_scope,
            "redaction_summary": canonical_redaction,
            "temporal_scope": temporal_scope.to_mapping(),
            "freshness_ceiling_seconds": freshness_ceiling_seconds,
            "completeness": completeness,
            "synthetic": synthetic,
            "conflicts": canonical_conflicts,
            "verification_method": verification_method,
            "verifier_identity": verifier_identity,
            "verification_receipt_ref": verification_receipt_ref,
            "evidence_lane": None,
            "evidence_item_digest": None,
            "membership_evidence": None,
        }
        return cls(
            receipt_id=f"source-receipt:sha256:{_digest(values)}",
            ontology_release_digest=ontology_release_digest,
            catalog_revision=catalog_revision,
            document_revision=document_revision,
            source_identity=source_identity,
            source_revision=source_revision,
            authenticated_source=authenticated_source,
            content_digest=content_digest,
            purpose=purpose,
            scope=canonical_scope,
            redaction_summary=canonical_redaction,
            temporal_scope=temporal_scope,
            freshness_ceiling_seconds=freshness_ceiling_seconds,
            completeness=completeness,
            synthetic=synthetic,
            conflicts=canonical_conflicts,
            verification_method=verification_method,
            verifier_identity=verifier_identity,
            verification_receipt_ref=verification_receipt_ref,
        )

    @classmethod
    def from_secured_snapshot(
        cls,
        snapshot: SecuredSnapshotReceipt,
        *,
        catalog_revision: str,
        source_identity: str,
        source_revision: str,
        authenticated_source: str,
        recorded_at: datetime,
        scope: tuple[str, ...],
        redaction_summary: tuple[str, ...],
        freshness_ceiling_seconds: int,
        verifier_identity: str,
        verification_receipt_ref: str,
    ) -> VerifiedEvidenceSourceReceipt:
        """Create a receipt from the secured ObjectSet snapshot receipt surface."""

        release_digest = getattr(snapshot.ontology_release, "digest", None)
        if not isinstance(release_digest, str):
            raise ValueError("secured snapshot MUST identify an ontology release digest")
        return cls.create(
            ontology_release_digest=release_digest,
            catalog_revision=catalog_revision,
            document_revision=None,
            source_identity=source_identity,
            source_revision=source_revision,
            authenticated_source=authenticated_source,
            content_digest=snapshot.projected_result_digest,
            purpose=snapshot.purpose,
            scope=scope,
            redaction_summary=redaction_summary,
            temporal_scope=EvidenceTemporalScope(
                effective_from=snapshot.observation_cutoff,
                effective_to=None,
                evidence_cutoff=snapshot.observation_cutoff,
                recorded_at=recorded_at,
            ),
            freshness_ceiling_seconds=freshness_ceiling_seconds,
            completeness=1.0 if snapshot.complete else 0.0,
            synthetic=False,
            verification_method="secured-object-set-query",
            verifier_identity=verifier_identity,
            verification_receipt_ref=verification_receipt_ref,
        )

    def expected_id(self) -> str:
        """Return the receipt identity implied by its canonical fields."""

        return f"source-receipt:sha256:{_digest(self.to_mapping(include_id=False))}"

    @property
    def binds_evidence_item(self) -> bool:
        """Return whether this receipt binds one exact lane item and membership proof."""

        return self.evidence_item_digest is not None

    def bind_evidence_item(
        self,
        *,
        lane: str,
        item_digest: str,
        membership_evidence: dict[str, object],
    ) -> Self:
        """Return a receipt binding an exact item and source inclusion proof."""

        canonical_membership = _canonical_json(membership_evidence)
        if len(canonical_membership.encode()) > _MAX_MEMBERSHIP_EVIDENCE_BYTES:
            raise ValueError("source receipt membership_evidence exceeds byte limit")
        values = self.to_mapping(include_id=False)
        values.update(
            {
                "evidence_lane": lane,
                "evidence_item_digest": item_digest,
                "membership_evidence": canonical_membership,
            }
        )
        return type(self)(
            receipt_id=f"source-receipt:sha256:{_digest(values)}",
            ontology_release_digest=self.ontology_release_digest,
            catalog_revision=self.catalog_revision,
            document_revision=self.document_revision,
            source_identity=self.source_identity,
            source_revision=self.source_revision,
            authenticated_source=self.authenticated_source,
            content_digest=self.content_digest,
            purpose=self.purpose,
            scope=self.scope,
            redaction_summary=self.redaction_summary,
            temporal_scope=self.temporal_scope,
            freshness_ceiling_seconds=self.freshness_ceiling_seconds,
            completeness=self.completeness,
            synthetic=self.synthetic,
            conflicts=self.conflicts,
            verification_method=self.verification_method,
            verifier_identity=self.verifier_identity,
            verification_receipt_ref=self.verification_receipt_ref,
            evidence_lane=lane,
            evidence_item_digest=item_digest,
            membership_evidence=canonical_membership,
        )

    def membership_evidence_mapping(self) -> dict[str, object]:
        """Decode immutable lane-specific membership evidence for validation."""

        if self.membership_evidence is None:
            raise ValueError("source receipt MUST bind membership evidence")
        return _decode_membership_evidence(self.membership_evidence)

    def to_mapping(self, *, include_id: bool = True) -> dict[str, object]:
        """Return the canonical source receipt representation."""

        value: dict[str, object] = {
            "authenticated_source": self.authenticated_source,
            "catalog_revision": self.catalog_revision,
            "completeness": self.completeness,
            "conflicts": self.conflicts,
            "content_digest": self.content_digest,
            "document_revision": self.document_revision,
            "evidence_item_digest": self.evidence_item_digest,
            "evidence_lane": self.evidence_lane,
            "freshness_ceiling_seconds": self.freshness_ceiling_seconds,
            "membership_evidence": self.membership_evidence,
            "ontology_release_digest": self.ontology_release_digest,
            "purpose": self.purpose,
            "redaction_summary": self.redaction_summary,
            "scope": self.scope,
            "source_identity": self.source_identity,
            "source_revision": self.source_revision,
            "synthetic": self.synthetic,
            "temporal_scope": self.temporal_scope.to_mapping(),
            "verification_method": self.verification_method,
            "verification_receipt_ref": self.verification_receipt_ref,
            "verifier_identity": self.verifier_identity,
        }
        if include_id:
            value["receipt_id"] = self.receipt_id
        return value


def _canonical_values(
    values: tuple[str, ...],
    *,
    field_name: str,
    required: bool,
    max_items: int,
) -> tuple[str, ...]:
    canonical = tuple(sorted(set(values)))
    if required and not canonical:
        raise ValueError(f"source receipt {field_name} MUST be non-empty")
    if len(canonical) > max_items:
        raise ValueError(f"source receipt {field_name} exceeds item limit")
    for value in canonical:
        _require_text(value, field_name=field_name)
    return canonical


def _require_text(value: str, *, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"source receipt {field_name} MUST be non-empty")
    if len(value) > _MAX_REF_LENGTH:
        raise ValueError(f"source receipt {field_name} exceeds length limit")


def _require_digest(value: str, *, field_name: str) -> None:
    if _DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError(f"source receipt {field_name} MUST be a SHA-256 digest")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("source receipt membership_evidence MUST be canonical JSON") from exc


def _decode_membership_evidence(value: str) -> dict[str, object]:
    if len(value.encode()) > _MAX_MEMBERSHIP_EVIDENCE_BYTES:
        raise ValueError("source receipt membership_evidence exceeds byte limit")
    try:
        decoded: Any = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("source receipt membership_evidence MUST be canonical JSON") from exc
    if not isinstance(decoded, dict) or _canonical_json(decoded) != value:
        raise ValueError("source receipt membership_evidence MUST be a canonical JSON object")
    return decoded


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "EvidenceTemporalScope",
    "SecuredSnapshotReceipt",
    "VerifiedEvidenceSourceReceipt",
]
